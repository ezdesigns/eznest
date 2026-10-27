"""Bounded neighborhood reinsertion; source geometry and safety rules stay exact."""
import copy
import time
from statistics import median

from shapely.affinity import rotate, translate
from shapely.geometry import box
from shapely.strtree import STRtree


def repack(job, result, budget, additions=()):
    """Move at most six existing pieces per trial; roll back incomplete trials.

    Search sparse horizontal neighborhoods and the tail, freezing everything
    else. With additions, job describes the complete proposed set and result
    is its incumbent without those additions. Only a fully validated layout can
    replace it. Search is heuristic, never a proof that a hole cannot be filled.
    """
    from engine import part_polygon, placed_polygon, validate_result
    deadline = time.monotonic() + max(0, budget)
    settings = job['settings']
    width, margin = settings['width'], settings['margin']
    clearance = settings['gap'] + .22
    limit = result['usedLength']
    by_id = {p['id']: p for p in job['parts']}
    best = result
    shapes = [placed_polygon(by_id[p['id']], p) for p in result['placements']]
    if not shapes or time.monotonic() >= deadline:
        return best
    band = max(1, median(s.bounds[3]-s.bounds[1] for s in shapes)*2)
    # Rank actual occupied bands by protected-area coverage. Always try the
    # tail too, since shortening the roll is the primary objective.
    bands = {}
    for i, shape in enumerate(shapes):
        y0, y1 = shape.bounds[1], shape.bounds[3]
        key = int(((y0+y1)/2-margin)/band)
        bands.setdefault(key, []).append(i)
    ranked = sorted(bands, key=lambda k: sum(shapes[i].area for i in bands[k]) /
                    max(1, (width-2*margin)*min(band, limit-margin-(margin+k*band))))
    anchors = [max(0, limit-margin-band/2)] + [margin+(k+.5)*band for k in ranked[:3]]
    rotations = {}

    def find(ident, occupied, tree, original_angle=0):
        if ident not in rotations:
            angles = settings['rotations']
            angles = angles if angles is not None else sorted({original_angle % 360, *range(0,360,15)})
            rotations[ident] = [(a, rotate(part_polygon(by_id[ident]), a, origin=(0,0))) for a in angles]
        left, top, right, bottom = margin+.1, margin+.1, width-margin-.1, limit-margin-.1
        for angle, polygon in rotations[ident]:
            x0,y0,x1,y1 = polygon.bounds
            w,h = x1-x0,y1-y0
            if w > right-left or h > bottom-top:
                continue
            xs, ys = {left, right-w}, {top, bottom-h}
            for shape in occupied:
                a,b,c,d = shape.bounds
                xs.update((a, c-w, c+clearance, a-w-clearance))
                ys.update((b, d-h, d+clearance, b-h-clearance))
            step = max(1, min(w,h)/2, (bottom-top)/40)
            xs.update(left+i*step for i in range(int((right-left-w)/step)+1))
            ys.update(top+i*step for i in range(int((bottom-top-h)/step)+1))
            xs = sorted(x for x in xs if left <= x <= right-w)
            ys = sorted(y for y in ys if top <= y <= bottom-h)
            for y in ys:
                for x in xs:
                    if time.monotonic() >= deadline:
                        return None
                    neighbors = tree.query(box(x-clearance,y-clearance,x+w+clearance,y+h+clearance)) if tree is not None else []
                    candidate = translate(polygon,x-x0,y-y0)
                    if all(not candidate.intersects(occupied[i]) and candidate.distance(occupied[i]) >= clearance-1e-8 for i in neighbors):
                        return {'id':ident,'x':x-x0,'y':y-y0,'rotation':angle}, candidate
        return None

    for anchor in anchors:
        for small_first in (False, True):
            if time.monotonic() >= deadline:
                return best
            placements = best['placements']
            shapes = [placed_polygon(by_id[p['id']], p) for p in placements]
            tail = sorted(range(len(shapes)), key=lambda i: shapes[i].bounds[3], reverse=True)[:2]
            near = sorted(range(len(shapes)), key=lambda i: abs((shapes[i].bounds[1]+shapes[i].bounds[3])/2-anchor))[:4]
            moving = set(tail+near)
            occupied = [s for i,s in enumerate(shapes) if i not in moving]
            trial = [copy.deepcopy(p) for i,p in enumerate(placements) if i not in moving]
            pending = [placements[i] for i in sorted(moving)] + [{'id':ident,'rotation':0} for ident in additions]
            pending.sort(key=lambda p: part_polygon(by_id[p['id']]).area, reverse=not small_first)
            complete = True
            for part in pending:
                found = find(part['id'],occupied,STRtree(occupied) if occupied else None,part['rotation'])
                if found is None:
                    complete = False
                    break
                placement, shape = found
                trial.append(placement); occupied.append(shape)
            if not complete:
                continue
            length = max(s.bounds[3] for s in occupied)+margin
            if length > limit+1e-7:
                continue
            old_moment = sum(s.bounds[3] for s in shapes)
            if not additions and length >= best['usedLength']-1e-7 and sum(s.bounds[3] for s in occupied) >= old_moment-1e-7:
                continue
            area = sum(s.area for s in occupied)
            candidate = {**best, 'placements':trial, 'usedLength':length,
                         'area':area, 'utilization':area/(width*length), 'validated':True,
                         'localRepackAccepted':best.get('localRepackAccepted',0)+1}
            try:
                validate_result(job,candidate)
            except ValueError:
                continue
            best = candidate
            limit = length
            if additions:
                return best
    return best
