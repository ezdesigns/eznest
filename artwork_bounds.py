"""Conservative print envelopes. Original PDF paint is never rewritten or scaled.

PDFium supplies path/text/image/shading bounds and source clipping. These are
used only to keep neighbouring artwork apart and reserve nesting space. Paint
that connects multiple cut pieces keeps those pieces together as one unit.
"""
import ctypes
import math

from shapely.affinity import affine_transform
from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union

MM = 25.4 / 72
PAD = .40 / MM  # Conservative enclosure/antialias guard; never changes PDF paint.
IDENTITY = (1, 0, 0, 1, 0, 0)


def transformed(shape, matrix):
    a, b, c, d, e, f = matrix
    return affine_transform(shape, (a, c, b, d, e, f))


def enclosing_polygon(points):
    shape = Polygon(points)
    # Compound/self-intersecting fill rules may leave holes. Overestimating the
    # footprint is safe; repairing with buffer(0) can discard painted lobes.
    return shape if shape.is_valid else shape.convex_hull


def compact_enclosure(envelope):
    """Keep detailed paint inside a bounded-complexity nesting outline."""
    if len(envelope.exterior.coords) <= 5001:
        return envelope
    # A small outward guard lets near-collinear paint vertices be removed.
    # Prove coverage: a plain simplify can cut corners off existing bleed.
    for tolerance_mm in (.02, .05, .1):
        tolerance = tolerance_mm / MM
        candidate = envelope.simplify(tolerance, preserve_topology=True).buffer(tolerance * 1.02, quad_segs=2)
        if candidate.geom_type == 'Polygon' and candidate.is_valid and len(candidate.exterior.coords) <= 5001 and candidate.covers(envelope):
            return candidate
    raise ValueError('Artwork outline is too complex to nest safely. Keep this group together in Illustrator.')


def path_parts(count, segment_at, tolerance):
    import pypdfium2.raw as api
    from pdf_io import curve_points
    if not 0 <= count <= 100000:
        raise ValueError('Artwork path is too complex to separate safely.')
    paths, points, controls = [], [], []
    for index in range(count):
        segment = segment_at(index)
        x, y = ctypes.c_float(), ctypes.c_float()
        if not segment or not api.FPDFPathSegment_GetPoint(segment, x, y):
            raise ValueError('An artwork path could not be read.')
        point = [x.value, y.value]
        kind = api.FPDFPathSegment_GetType(segment)
        if kind == api.FPDF_SEGMENT_MOVETO:
            if points:
                paths.append(points)
            points = [point]
        elif kind == api.FPDF_SEGMENT_LINETO:
            points.append(point)
        elif kind == api.FPDF_SEGMENT_BEZIERTO:
            controls.append(point)
            if len(controls) == 3:
                if not points:
                    raise ValueError('An artwork curve has no start.')
                points += curve_points(points[-1], *controls, tolerance=tolerance)
                controls = []
        else:
            raise ValueError('An artwork path uses an unsupported segment.')
        if api.FPDFPathSegment_GetClose(segment) and points:
            if points[0] != points[-1]:
                points.append(points[0])
            paths.append(points)
            points = []
    if controls:
        raise ValueError('An artwork curve is incomplete.')
    if points:
        paths.append(points)
    return paths


def paint_envelopes(page):
    import pypdfium2.raw as api
    from pdf_io import matrix
    budget = [0]
    crop = box(*page.get_bbox())

    def visit(objects, parent=IDENTITY, inherited=crop, depth=0):
        if depth > 15:
            raise ValueError('Artwork forms are nested too deeply.')
        for obj in objects:
            budget[0] += 1
            if budget[0] > 100000:
                raise ValueError('Too many artwork objects to separate safely.')
            local = obj.get_matrix().get() if obj.type in (api.FPDF_PAGEOBJ_PATH, api.FPDF_PAGEOBJ_FORM) else IDENTITY
            total = matrix(parent, local)
            # Frobenius norm bounds amplification under nonuniform transforms.
            amplification = max(1, math.sqrt(sum(v*v for v in total[:4])))
            tolerance = .01 / MM / amplification
            clipping = inherited
            clip = api.FPDFPageObj_GetClipPath(obj)
            if clip:
                for index in range(max(0, api.FPDFClipPath_CountPaths(clip))):
                    paths = path_parts(api.FPDFClipPath_CountPathSegments(clip, index),
                                       lambda k: api.FPDFClipPath_GetPathSegment(clip, index, k), tolerance)
                    polygons = [enclosing_polygon(p) for p in paths if len(p) >= 3]
                    clipping = clipping.intersection(transformed(unary_union(polygons), parent).buffer(PAD))
            if obj.type == api.FPDF_PAGEOBJ_FORM:
                yield from visit(page.get_objects(form=obj, max_depth=1), total, clipping, depth+1)
                continue
            bounds = transformed(box(*obj.get_bounds()), parent)
            shape = bounds
            if obj.type == api.FPDF_PAGEOBJ_PATH:
                fill, stroke = ctypes.c_int(), ctypes.c_int()
                if not api.FPDFPath_GetDrawMode(obj, fill, stroke):
                    raise ValueError('Artwork paint style could not be read.')
                paths = path_parts(api.FPDFPath_CountSegments(obj), lambda k: api.FPDFPath_GetPathSegment(obj, k), tolerance)
                parts = [enclosing_polygon(p) for p in paths if fill.value and len(p) >= 3]
                if stroke.value:
                    width = ctypes.c_float()
                    if not api.FPDFPageObj_GetStrokeWidth(obj, width):
                        raise ValueError('Artwork stroke width could not be read.')
                    # Continuous square-cap/miter envelopes cover dashed, bevel
                    # and round strokes too. PDFium object bounds can omit curved
                    # stroke extrema, so they must not truncate this envelope.
                    parts += [LineString(p).buffer(max(width.value/2, .05/MM), cap_style=3,
                              join_style=2, mitre_limit=1000000) for p in paths if len(p) >= 2]
                shape = transformed(unary_union(parts), total).buffer(PAD)
            else:
                # Bounds-based paint needs the same enclosure guard as paths.
                shape = shape.buffer(PAD)
            if not shape.is_empty:
                yield shape.intersection(clipping)

    return list(visit(page.get_objects(max_depth=1)))


def preserve_artwork(clean, meta):
    import pypdfium2 as pdfium
    from cut_mapping import counts
    pieces = []
    original_count = len(meta['pieces'])
    with pdfium.PdfDocument(clean) as document:
        for page_index in range(len(document)):
            page = document[page_index]
            try:
                source = [p for p in meta['pieces'] if p['page'] == page_index]
                cuts = [Polygon(p['pdfPoints']) for p in source]
                paint = paint_envelopes(page)
                # Paint already includes its first enclosure guard. Preserve the
                # extra export guard too: PDF edge antialiasing can reach beyond
                # a flattened paint boundary. Only blank guard overlap may split.
                combined = unary_union([p.buffer(PAD) for p in cuts] + [p for p in paint if not p.is_empty])
                cores = list(combined.geoms) if combined.geom_type == 'MultiPolygon' else [combined]
                cores = [g for g in cores if g.geom_type == 'Polygon']
                guarded = [Polygon(g.exterior).buffer(PAD) for g in cores]
                combined = unary_union(guarded)
                groups = list(combined.geoms) if combined.geom_type == 'MultiPolygon' else [combined]
                envelopes = [Polygon(g.exterior) for g in groups if g.geom_type == 'Polygon']
                combined = unary_union([g.convex_hull if len(g.exterior.coords) > 5000 else g for g in envelopes])
                groups = list(combined.geoms) if combined.geom_type == 'MultiPolygon' else [combined]
                # A union can create a new enclosed void. Include anything in
                # that void before using exterior-only clips and envelopes.
                while True:
                    combined = unary_union([Polygon(g.exterior) for g in groups])
                    filled = list(combined.geoms) if combined.geom_type == 'MultiPolygon' else [combined]
                    stable = len(filled) == len(groups)
                    groups = filled
                    if stable:
                        break
                separated = []
                for group in groups:
                    members = [i for i, core in enumerate(cores) if group.intersects(core)]
                    # Each candidate retains both guards and must exclude every
                    # other protected paint core, including cores outside this
                    # component. Otherwise retain the conservative whole group.
                    safe = members and all(
                        any(cores[i].intersects(cut) for cut in cuts) and
                        all(guarded[i].disjoint(core) for j, core in enumerate(cores) if i != j)
                        for i in members)
                    if safe:
                        separated.extend(guarded[i] for i in members)
                    else:
                        separated.append(group)
                groups = separated
                owned = []
                missing = 0
                for group in groups:
                    owners = [i for i, cut in enumerate(cuts) if group.intersects(cut)]
                    if not owners:
                        missing += 1
                        continue
                    if group.geom_type != 'Polygon':
                        raise ValueError('An artwork outline could not be read safely. Check its shape in Illustrator; nothing was removed.')
                    owned.append((min(owners), group, owners))
                if missing:
                    label = 'artwork group has' if missing == 1 else 'artwork groups have'
                    raise ValueError(f'Page {page_index+1}: {missing} separate {label} no cut boundary. '
                                     'Add closed cut lines for separate stickers, or place decoration with its intended piece in Illustrator. '
                                     'Nothing was removed.')
                if sorted(i for _, _, owners in owned for i in owners) != list(range(len(cuts))):
                    raise ValueError('Artwork ownership is ambiguous. Keep connected pieces together in Illustrator.')
                for _, group, owners in sorted(owned, key=lambda item: item[0]):
                    # Search simplification may grow an outline. Keep that
                    # growth out of the export clip so it cannot copy nearby ink.
                    clip = Polygon(group.exterior)
                    envelope = compact_enclosure(clip)
                    x0, y0, x1, y1 = envelope.bounds
                    piece = dict(source[owners[0]])
                    piece.update(id='pdf-'+str(len(pieces)+1), sourcePieceCount=len(owners),
                                 name=source[owners[0]]['name'] if len(owners)==1 else f'Page {page_index+1} · group {len(pieces)+1} ({len(owners)} pieces)',
                                 anchor=[x0,y1], bounds=[x0,y0,x1,y1],
                                 points=[[(x-x0)*MM,(y1-y)*MM] for x,y in envelope.exterior.coords[:-1]],
                                 clipCommands=[('m',list(clip.exterior.coords[0]))]+[('l',list(p)) for p in clip.exterior.coords[1:]]+[('h',[])],
                                 cutPaths=[cut for i in owners for cut in source[i]['cutPaths']])
                    piece['cutCounts'] = counts(piece)
                    pieces.append(piece)
            finally:
                page.close()
    meta.update(pieces=pieces, artworkPreserved=True, sourcePieceCount=original_count,
                warnings=['Original artwork and existing bleed retained without resizing. Connected artwork stays together. Review artwork, scale and cuts before printing.'])
    return meta
