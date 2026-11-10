"""Recover complete printable pieces from the PDF's existing clipping groups.

Coordinates, paint operators, source masks, and cuts are never rewritten here.
The result is an ownership plan, not new artwork or new bleed.
"""
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

from artwork_bounds import MM, PAD, compact_enclosure
from pdf_piece_objects import analyze_objects


def clipping_scopes(operations):
    from pdf_io import IDENTITY, matrix, point, flattened_path, clipping_region
    stack, commands, paths, clips = [], [], [], []
    transform, pending = IDENTITY, None

    def finish():
        if commands:
            paths.append((list(commands), flattened_path(commands), True))
            commands.clear()

    for index, (values, op) in enumerate(operations):
        if op == b'q':
            stack.append((index, transform))
        elif op == b'Q':
            if not stack:
                return []
            start, transform = stack.pop()
            for clip in clips:
                if clip['start'] == start:
                    clip['end'] = index
        elif op == b'cm':
            transform = matrix(transform, tuple(map(float, values)))
        elif op == b'm':
            finish(); commands.append(('m', point(transform, values)))
        elif op == b'l':
            commands.append(('l', point(transform, values)))
        elif op in (b'c', b'v', b'y'):
            pts = [point(transform, values[i:i+2]) for i in range(0, len(values), 2)]
            if op == b'v':
                if not commands:
                    return []
                pts.insert(0, commands[-1][1][-2:])
            if op == b'y':
                pts.append(pts[-1])
            commands.append(('c', [v for p in pts for v in p]))
        elif op == b'h':
            commands.append(('h', []))
            # PDF allows another segment after h. Keep the start point available.
        elif op == b're':
            finish()
            x, y, w, h = map(float, values)
            pts = [point(transform, p) for p in ((x,y),(x+w,y),(x+w,y+h),(x,y+h))]
            commands.extend([('m',pts[0])] + [('l',p) for p in pts[1:]] + [('h',[])])
            finish()
        elif op in (b'W', b'W*'):
            pending = op
        elif op in (b'n', b'f', b'f*', b'F', b'S', b's', b'B', b'B*', b'b', b'b*'):
            finish()
            if pending and stack:
                shape = clipping_region(paths, pending)
                polygons = list(shape.geoms) if shape.geom_type == 'MultiPolygon' else [shape]
                if all(p.geom_type == 'Polygon' for p in polygons):
                    clips.append({'start':stack[-1][0], 'clip':index, 'shape':shape,
                                  'region':unary_union([Polygon(p.exterior) for p in polygons])})
            paths.clear(); pending = None
    return [c for c in clips if 'end' in c] if not stack else []


def prepare_groups(page, reader, paths):
    """Return a complete plan, or None. Every paint operation must be retained.

    Source clipping identifies the main groups. A loose complete paint object
    can be attached by a clear majority match, recorded for operator review.
    No object is sliced and no nearest-neighbour guess is used for orphan art.
    """
    from cut_mapping import counts
    if not paths or len(paths) > 200:
        return None
    closed = {i:Polygon(p['pdfPoints']) for i,p in enumerate(paths) if p.get('boundary',p['closed'])}
    # Exact safe duplicates have already been removed by the importer. Any
    # remaining coincident paths carry conflicting identity/style or are open
    # tool strokes; source grouping must not bypass their rejection.
    boundaries = list(closed.values())
    open_cuts = [LineString(p['pdfPoints']) for p in paths if not p.get('boundary',p['closed'])]
    if any(a.equals(b) for n,a in enumerate(boundaries) for b in boundaries[n+1:]):
        return None
    if any(a.equals(b) for n,a in enumerate(open_cuts) for b in open_cuts[n+1:]):
        return None
    outer = [i for i,p in closed.items() if not any(j != i and q.covers(p) for j,q in closed.items())]
    if not outer:
        return None
    analyzed = analyze_objects(page, reader, keep_unseen=True)
    if analyzed is None:
        return None
    operations, spans, shapes = analyzed
    clips = clipping_scopes(operations)
    matched = {}
    for i in outer:
        candidates = [n for n,c in enumerate(clips)
                      if c['region'].area < closed[i].area * 2 and c['region'].buffer(.03).covers(closed[i])]
        if not candidates:
            continue
        # Distinct enclosing silhouettes are not equivalent ownership evidence.
        smallest = min(candidates, key=lambda n:clips[n]['region'].area)
        region = clips[smallest]['region']
        candidates = [n for n in candidates if clips[n]['region'].equals(region)]
        for n in candidates:
            matched.setdefault(n, set()).add(i)
    groups = []
    for members in matched.values():
        merged = set(members)
        for old in groups[:]:
            if old & merged:
                merged |= old; groups.remove(old)
        groups.append(merged)
    groups.sort(key=min)
    if not groups:
        return None
    groups.extend({i} for i in outer if not any(i in g for g in groups))
    groups.sort(key=min)
    owner = {i:n for n,g in enumerate(groups) for i in g}
    clip_owner = {n:owner[next(iter(g))] for n,g in matched.items()}
    regions = [unary_union([clips[i]['region'] for i,o in clip_owner.items() if o == n] + [closed[i] for i in g])
               for n,g in enumerate(groups)]
    owned_cuts = [[] for _ in groups]
    for i,path in enumerate(paths):
        if i in owner:
            assigned = {owner[i]}
        else:
            shape = closed.get(i) if i in closed else LineString(path['pdfPoints'])
            assigned = {owner[j] for j in outer if closed[j].buffer(.001).covers(shape)}
        if len(assigned) != 1:
            return None
        owned_cuts[assigned.pop()].append(path)
    ids = [[] for _ in groups]
    enclosures = [[] for _ in groups]
    inferred = [[] for _ in groups]
    orphans = []
    for ident, shape in shapes.items():
        position = spans[ident][0]
        scoped = [n for n in clip_owner if clips[n]['clip'] < position < clips[n]['end']]
        owners = {clip_owner[n] for n in scoped}
        if len(owners) > 1:
            return None
        if shape is None:
            # Keep paint optimized away by PDFium in its original explicit mask.
            # Reserve the whole mask, rather than pretending its paint is empty.
            if len(owners) != 1:
                return None
            shape = unary_union([clips[n]['shape'] for n in scoped]).buffer(PAD)
        if not owners and shape.is_empty:
            # Preserve even fully clipped operations; they paint nothing anywhere.
            owners = {0}
        if not owners:
            owners = {n for n,r in enumerate(regions) if r.buffer(PAD*1.05).covers(shape)}
        automatic = False
        scores = []
        if len(owners) != 1 and shape.area > 0:
            scores = sorted(((shape.intersection(r).area/shape.area,n) for n,r in enumerate(regions)),reverse=True)
            if scores[0][0] >= .67 and (len(scores) == 1 or scores[0][0] > 2*scores[1][0]):
                owners = {scores[0][1]}; automatic = True
        if len(owners) != 1:
            if not owners and shape is not None and not shape.is_empty and scores and scores[0][0] < .01:
                orphans.append((ident,shape))
                continue
            return None
        target = owners.pop(); ids[target].append(ident); enclosures[target].append(shape)
        if automatic:
            inferred[target].append(ident)
    # Preserve truly separate print-only artwork as its own item, clearly named
    # as having no cuts. Do not invent trim geometry or attach it to a neighbour.
    if orphans:
        tree = STRtree([s for _,s in orphans])
        parent = list(range(len(orphans)))
        def root(n):
            while parent[n] != n:
                parent[n] = parent[parent[n]]; n = parent[n]
            return n
        for n,(_,shape) in enumerate(orphans):
            for j in tree.query(shape, predicate='intersects'):
                parent[root(int(j))] = root(n)
        components = {}
        for n,member in enumerate(orphans):
            components.setdefault(root(n),[]).append(member)
        existing = [unary_union(shapes) for shapes in enclosures]
        for members in components.values():
            paint = unary_union([s for _,s in members])
            connected = [n for n,shape in enumerate(existing) if paint.distance(shape) <= 2*PAD]
            if len(connected) == 1:
                target = connected[0]
                ids[target].extend(i for i,_ in members)
                enclosures[target].extend(s for _,s in members)
                continue
            groups.append(set()); owned_cuts.append([])
            ids.append([i for i,_ in members]); enclosures.append([s for _,s in members]); inferred.append([])
    if sorted(i for owned in ids for i in owned) != list(range(len(spans))):
        return None
    pieces = []
    for n,g in enumerate(groups):
        # Disconnected decoration stays intact with its proven owner. Reserve
        # extra blank space if needed; never crop or enlarge the printed object.
        footprint = unary_union(enclosures[n] + [Polygon(p['pdfPoints']) for p in owned_cuts[n] if p['closed']]).buffer(PAD)
        if footprint.geom_type != 'Polygon':
            footprint = footprint.convex_hull
        envelope = compact_enclosure(Polygon(footprint.exterior))
        x0,y0,x1,y1 = envelope.bounds
        piece = dict(paths[min(g)]) if g else {'page':paths[0]['page'], 'printOnly':True}
        cut_shapes = [Polygon(p['pdfPoints']) for p in owned_cuts[n] if p.get('boundary',p['closed'])]
        crossing = sum(a.intersection(b).area > .001 and not a.covers(b) and not b.covers(a)
                       for index,a in enumerate(cut_shapes) for b in cut_shapes[index+1:])
        piece.update(cutPaths=owned_cuts[n], sourceObjectIds=ids[n],
                     sourceObjectCount=len(spans), automaticArtworkMatches=len(inferred[n]),
                     retainedCrossingCuts=crossing,
                     sourcePieceCount=1, bounds=[x0,y0,x1,y1], anchor=[x0,y1],
                     points=[[(x-x0)*MM,(y1-y)*MM] for x,y in envelope.exterior.coords[:-1]],
                     clipCommands=[('m',list(envelope.exterior.coords[0]))]+
                                  [('l',list(p)) for p in envelope.exterior.coords[1:]]+[('h',[])])
        piece['cutCounts'] = counts(piece)
        pieces.append(piece)
    return pieces
