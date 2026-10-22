"""Original EZ Nest adapter. No commercial suite code is used."""
import math

# Shop v1 cap. Search time still bounds a nest; history and intake stay outside this module.
PIECE_CAP = 800
import time
from collections import Counter
import spyrrow
from shapely.geometry import Polygon, box
from shapely.affinity import rotate, translate


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}.')
    return float(value)


def validate_job(job):
    settings = job['settings']
    width = number(settings['width'], 'Material width', 10, 5000)
    length = None if settings.get('maxLength') is None else number(settings['maxLength'], 'Maximum length', 10, 5000)
    gap = number(settings['gap'], 'Gap', 0, 100)
    margin = number(settings['margin'], 'Edge margin', 0, 100)
    seconds = number(settings['seconds'], 'Search time', 1, 120)
    if margin * 2 >= width or (length is not None and margin * 2 >= length):
        raise ValueError('Margins leave no printable material.')
    rotations = settings['rotations']
    if rotations is not None and rotations not in ([0], [0, 180], [0, 90, 180, 270]):
        raise ValueError('Choose a supported rotation mode.')
    number(settings.get('seed', 42), 'Search seed', 0, 2147483647)
    parts = job.get('parts', [])
    if not 1 <= len(parts) <= PIECE_CAP:
        raise ValueError(f'Select between 1 and {PIECE_CAP} closed paths.')
    seen = set()
    total = 0
    for part in parts:
        ident = part['id']
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError('Each part needs a unique ID.')
        seen.add(ident)
        quantity = part.get('quantity', 1)
        if type(quantity) is not int or not 1 <= quantity <= PIECE_CAP:
            raise ValueError(f'Quantity must be an integer from 1 to {PIECE_CAP}.')
        total += quantity
        points = part.get('nestingPoints', part['points'])
        if not 3 <= len(points) <= 5000:
            raise ValueError(f'{ident}: invalid contour size.')
        for point in points:
            if len(point) != 2:
                raise ValueError('Each contour point must have two coordinates.')
            for coordinate in point:
                number(coordinate, 'Coordinate', -10000, 10000)
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area < 0.01:
            raise ValueError(f'{ident}: contour intersects itself or has no usable area.')
        # Compare every permitted orientation, not only the unrotated bounds.
        # Continuous rotation has no finite list of angles. Do not falsely reject
        # a shape that fits only at an angle between sampled orientations.
        fits = rotations is None
        for angle in rotations or []:
            bounds = rotate(polygon, angle, origin=(0, 0)).bounds
            if bounds[2] - bounds[0] <= width - 2 * margin and (length is None or bounds[3] - bounds[1] <= length - 2 * margin):
                fits = True
        if not fits:
            raise ValueError(f'{ident}: part is too large for this material and rotation mode.')
    if total > PIECE_CAP:
        raise ValueError(f'This build supports {PIECE_CAP} pieces.')
    return width, length, gap, margin, seconds


def part_polygon(part):
    # Original source/cut points stay unchanged; the server derives print space.
    return Polygon(part.get('nestingPoints', part['points']))


def placed_polygon(part, placement):
    return translate(rotate(part_polygon(part), placement['rotation'], origin=(0, 0)), placement['x'], placement['y'])


def validate_result(job, result):
    if 'sheets' in result:
        from sheets import validate_sheets
        return validate_sheets(job, result)
    width, length, gap, margin, _ = validate_job(job)
    expected = Counter({p['id']: p.get('quantity', 1) for p in job['parts']})
    actual = Counter(p['id'] for p in result['placements'])
    if expected != actual:
        raise ValueError('Engine returned the wrong number of parts.')
    by_id = {p['id']: p for p in job['parts']}
    # With no operator limit, a conservative one-piece-per-row stack bounds the
    # expected strip extent. This is derived from the artwork, not a roll preset.
    if length is None:
        length = 2 * margin + 1
        for part in job['parts']:
            x0, y0, x1, y1 = part_polygon(part).bounds
            length += (math.hypot(x1-x0, y1-y0) + gap + .5) * part.get('quantity', 1)
    boundary = box(margin, margin, width - margin, length - margin)
    shapes = []
    if 'usedLength' in result:
        reported = number(result['usedLength'], 'Reported material length', 0.01, length + 0.001)
        boundary = box(margin, margin, width - margin, reported - margin)
    if 'width' in result and abs(number(result['width'], 'Reported width', 10, 5000) - width) > 0.001:
        raise ValueError('Result width does not match the material.')
    for placement in result['placements']:
        for key in ['x', 'y', 'rotation']:
            number(placement[key], key, -4_000_000, 4_000_000)
        angle = placement['rotation'] % 360
        if job['settings']['rotations'] is not None and not any(abs((angle - allowed + 180) % 360 - 180) < 0.001 for allowed in job['settings']['rotations']):
            raise ValueError('Engine returned a disallowed rotation.')
        shape = placed_polygon(by_id[placement['id']], placement)
        if not boundary.buffer(0.001).covers(shape):
            raise ValueError('No valid layout fits within the maximum material length.')
        for previous in shapes:
            if shape.intersection(previous).area > 0.0001 or shape.distance(previous) + 0.001 < gap:
                raise ValueError('Layout failed the independent overlap/spacing check.')
        shapes.append(shape)
    return shapes


def solve(job, progress_path=None):
    width, length, gap, margin, seconds = validate_job(job)
    started = time.monotonic()
    # Sparrow's finite axis is Y. Reflect x/y at the boundary of the adapter.
    # 0.10 mm outward guard exceeds the host's 0.05 mm curve flattening target.
    orientations = None if job['settings']['rotations'] is None else [-a for a in job['settings']['rotations']]
    items, base_rotations = [], {}
    for part in job['parts']:
        polygon = part_polygon(part)
        base = 0
        if orientations is None:
            # Native initialization can fail if a freely rotating shape starts
            # wider than the strip. Start it at its narrow caliper orientation.
            corners = list(polygon.minimum_rotated_rectangle.exterior.coords)
            candidates = [90 - math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) for a, b in zip(corners, corners[1:])]
            def cross_width(angle):
                bounds = rotate(polygon, angle, origin=(0, 0)).bounds
                return bounds[2] - bounds[0]
            base = min(candidates, key=cross_width)
            polygon = rotate(polygon, base, origin=(0, 0))
            if polygon.bounds[2] - polygon.bounds[0] + 0.2 > width - 2 * margin:
                raise ValueError(f"{part['id']}: part is too wide at every rotation.")
        base_rotations[part['id']] = base
        envelope = polygon.buffer(0.10, join_style=2)
        items.append(spyrrow.Item(part['id'], [(y, x) for x, y in envelope.exterior.coords], part.get('quantity', 1), orientations))
    # Small extra clearance absorbs native floating-point error; zero gap remains valid.
    config = spyrrow.StripPackingConfig(total_computation_time=int(seconds), min_items_separation=gap + 0.02, num_workers=2, seed=int(job['settings'].get('seed', 42)), early_termination=True)
    instance = spyrrow.StripPackingInstance('eznest', width - 2 * margin, items)
    progress_path = progress_path or job.pop('_progress', None)

    def build(solution):
        result = {'placements': [{'id': p.id, 'rotation': base_rotations[p.id] - p.rotation, 'x': p.translation[1] + margin, 'y': p.translation[0] + margin} for p in solution.placed_items]}
        shapes = validate_result(job, result)
        used_length = max(p.bounds[3] for p in shapes) + margin
        area = sum(p.area for p in shapes)
        result.update({'width': width, 'usedLength': used_length, 'area': area, 'utilization': area / (width * used_length), 'elapsed': time.monotonic() - started, 'engine': 'Sparrow via spyrrow ' + spyrrow.__version__, 'validated': True})
        return result

    if not progress_path:
        return build(instance.solve(config))
    import json
    import threading
    from pathlib import Path
    queue = spyrrow.ProgressQueue()
    holder, failure, best = {}, {}, -1
    feasible = (spyrrow.ReportType.ExplFeas, spyrrow.ReportType.CmprFeas, spyrrow.ReportType.Final)

    def run():
        try:
            holder['solution'] = instance.solve(config, queue)
        except BaseException as error:
            failure['error'] = error

    def publish(reports):
        nonlocal best
        for kind, solution in reports:
            if kind not in feasible:
                continue
            try:
                partial = build(solution)
            except (ValueError, ZeroDivisionError):
                continue
            if partial['utilization'] <= best + 1e-9:
                continue
            best = partial['utilization']
            path = Path(progress_path)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'ok': True, 'result': partial}), encoding='utf-8')
            temporary.replace(path)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    while thread.is_alive():
        publish(queue.drain())
        thread.join(0.2)
    publish(queue.drain())
    if 'error' in failure:
        raise failure['error']
    return build(holder['solution'])


if __name__ == '__main__':
    import json
    import sys
    from pathlib import Path
    request, output = map(Path, sys.argv[1:3])
    try:
        payload = {'ok': True, 'result': solve(json.loads(request.read_text(encoding='utf-8-sig')))}
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        payload = {'ok': False, 'error': str(error)}
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload), encoding='utf-8')
    temporary.replace(output)
