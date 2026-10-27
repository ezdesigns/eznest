"""Original EZ Nest adapter. No commercial suite code is used."""
import math
import copy

# Shop v1 cap. Search time still bounds a nest; history and intake stay outside this module.
PIECE_CAP = 800
ORDER_PIECE_CAP = 5000  # Automatic sections keep each solver input <= PIECE_CAP.
import time
from collections import Counter
import spyrrow
from shapely.geometry import Polygon, box
from shapely.affinity import rotate, translate
from shapely.strtree import STRtree


def solver_part(part, rotations, strip_width):
    """Check the guarded contour before handing it to the native solver."""
    envelope = search_envelope(part_polygon(part))
    base = 0
    if rotations is None:
        corners = list(envelope.minimum_rotated_rectangle.exterior.coords)
        candidates = [90 - math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
                      for a, b in zip(corners, corners[1:])]
    else:
        candidates = rotations
    # strip_width is the physical usable width. The buffered envelope has to
    # fit before the native solver runs. solve() expands the native strip only
    # when that envelope would not fit after container-edge padding.
    def cross_width(angle):
        bounds = rotate(envelope, angle, origin=(0, 0)).bounds
        return bounds[2] - bounds[0]
    fitting = [a for a in candidates if cross_width(a) < strip_width - 0.001]
    if not fitting:
        raise ValueError(f"{part['id']}: not enough material width for the safety clearance. "
                         "Use wider material, reduce the edge margin, or allow rotation.")
    if rotations is None:
        base = min(fitting, key=cross_width)
        envelope = rotate(envelope, base, origin=(0, 0))
    return envelope, base, None if rotations is None else [-a for a in fitting]


def edge_padding_blocks_fit(envelope, orientations, usable, separation):
    """True when native container-edge padding would reject a handed orientation.

    Sparrow insets every piece from the strip edge by min_items_separation.
    Ordinary parts still fit the unexpanded strip, and expanding it changes
    the search. Compensate only for an orientation that fits the physical
    usable width but not that inset.
    """
    limit = usable - 2 * separation
    if orientations is None:
        left, _, right, _ = envelope.bounds
        return right - left > limit + 1e-6
    for sparrow_angle in orientations:
        bounds = rotate(envelope, -sparrow_angle, origin=(0, 0)).bounds
        if bounds[2] - bounds[0] > limit + 1e-6:
            return True
    return False

def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}.')
    return float(value)


def validate_job(job):
    settings = job['settings']
    if 'continuous' in settings and type(settings['continuous']) is not bool:
        raise ValueError('Continuous print must be on or off.')
    cap = ORDER_PIECE_CAP if settings.get('sheetLength') is not None or settings.get('continuous') else PIECE_CAP
    width = number(settings['width'], 'Material width', 10, 5000)
    length = None if settings.get('maxLength') is None else number(settings['maxLength'], 'Available roll length', 10, 1000000)
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
    if not 1 <= len(parts) <= cap:
        raise ValueError(f'Select between 1 and {cap} closed paths.')
    seen = set()
    total = 0
    for part in parts:
        ident = part['id']
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError('Each part needs a unique ID.')
        seen.add(ident)
        quantity = part.get('quantity', 1)
        if type(quantity) is not int or not 1 <= quantity <= cap:
            raise ValueError(f'Quantity must be an integer from 1 to {cap}.')
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
    if total > cap:
        raise ValueError(f'This build supports {cap} pieces. Use automatic print sections for larger quantities.')
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
    covered_boundary = boundary.buffer(0.001)
    polygons = {ident: part_polygon(part) for ident, part in by_id.items()}
    orientations = {}
    for placement in result['placements']:
        for key in ['x', 'y', 'rotation']:
            number(placement[key], key, -4_000_000, 4_000_000)
        angle = placement['rotation'] % 360
        if job['settings']['rotations'] is not None and not any(abs((angle - allowed + 180) % 360 - 180) < 0.001 for allowed in job['settings']['rotations']):
            raise ValueError('Engine returned a disallowed rotation.')
        key = (placement['id'], placement['rotation'])
        if key not in orientations:
            orientations[key] = rotate(polygons[placement['id']], placement['rotation'], origin=(0, 0))
        shape = translate(orientations[key], placement['x'], placement['y'])
        if not covered_boundary.covers(shape):
            raise ValueError('No valid layout fits within the maximum material length.')
        shapes.append(shape)
    # Broad phase only: the tree narrows candidates. Expanded bounding boxes
    # cannot exclude an overlapping pair or a pair nearer than gap. Exact
    # polygon overlap and distance checks still decide validity, including
    # concave pieces and small gaps.
    tree = STRtree(shapes)
    for index, shape in enumerate(shapes):
        x0, y0, x1, y1 = shape.bounds
        for other in tree.query(box(x0-gap, y0-gap, x1+gap, y1+gap)):
            if other >= index:
                continue
            previous = shapes[other]
            if shape.intersection(previous).area > 0.0001 or shape.distance(previous) + 0.001 < gap:
                raise ValueError('Layout failed the independent overlap/spacing check.')
    return shapes


def search_envelope(polygon):
    """Reduce search work only; never change the source or its safety envelope."""
    envelope = polygon.buffer(0.10, join_style=2)
    if len(envelope.exterior.coords) <= 200:
        return envelope
    candidate = envelope.simplify(0.05, preserve_topology=True).buffer(0.051, quad_segs=2)
    # Simplification is not inherently outward. Prove containment rather than
    # trusting a tolerance, and retain the exact envelope if it cannot be proved.
    if candidate.geom_type == 'Polygon' and candidate.is_valid and candidate.covers(envelope) and len(candidate.exterior.coords) < len(envelope.exterior.coords):
        return candidate
    return envelope


def _box_gap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(0.0, bx0 - ax1, ax0 - bx1)
    dy = max(0.0, by0 - ay1, ay0 - by1)
    if dx == 0.0 and dy == 0.0:
        return 0.0
    return math.hypot(dx, dy)


def shelf_layout(job):
    """Row layout from bounding boxes. Kept only when it is shorter than search.

    Identical rectangles often fall into a regular grid faster than a short
    search. Concave parts stay with the search result when the rows are longer.
    """
    width = float(job['settings']['width'])
    gap = float(job['settings']['gap'])
    margin = float(job['settings']['margin'])
    angles = job['settings']['rotations'] if job['settings']['rotations'] is not None else (0, 90, 180, 270)
    usable = width - 2 * margin
    copies = []
    for part in job['parts']:
        polygon = part_polygon(part)
        envelope = search_envelope(polygon)
        variants = []
        for angle in angles:
            # Same fit rule as the native solver: a buffered outline that does
            # not fit this way is not a legal shelf orientation.
            guard = rotate(envelope, angle, origin=(0, 0)).bounds
            if guard[2] - guard[0] >= usable - 0.001:
                continue
            moved = rotate(polygon, angle, origin=(0, 0))
            x0, y0, x1, y1 = moved.bounds
            piece_width, piece_height = x1 - x0, y1 - y0
            if piece_width <= usable + 1e-6:
                variants.append((piece_width, piece_height, x0, y0, angle))
        if not variants:
            return None
        for copy in range(part.get('quantity', 1)):
            copies.append((part['id'], copy, variants))
    copies.sort(key=lambda item: (max(variant[1] for variant in item[2]), max(variant[0] for variant in item[2]), item[0], item[1]), reverse=True)
    cursor_x, cursor_y, row_height = margin, margin, 0.0
    placements = []
    for ident, _copy, variants in copies:
        room = width - margin - cursor_x
        fitting = [variant for variant in variants if variant[0] <= room + 1e-6]
        if not fitting:
            cursor_y += row_height + gap
            cursor_x, row_height = margin, 0.0
            fitting = variants
        piece_width, piece_height, x0, y0, angle = min(fitting, key=lambda variant: (variant[1], variant[0], variant[4]))
        placements.append({'id': ident, 'x': cursor_x - x0, 'y': cursor_y - y0, 'rotation': angle})
        cursor_x += piece_width + gap
        row_height = max(row_height, piece_height)
    used = cursor_y + row_height + margin
    result = {'placements': placements, 'width': width, 'usedLength': used}
    try:
        validate_result(job, result)
    except (ValueError, ZeroDivisionError):
        return None
    return result


def compact_result(job, result):
    """Slide each piece toward the start of the roll. Rotation stays put.

    Sparrow searches a slightly enlarged outline, so a finished layout can sit
    a fraction of a millimetre further apart than the operator gap. This pass
    uses the real outlines. It never lengthens the roll, and a layout that
    fails the independent check is discarded.
    """
    from shapely.affinity import translate as move_shape
    placements = [dict(item) for item in result.get('placements') or []]
    if not placements or 'usedLength' not in result:
        return result
    width = float(job['settings']['width'])
    gap = float(job['settings']['gap'])
    margin = float(job['settings']['margin'])
    by_id = {part['id']: part for part in job['parts']}
    shapes = [placed_polygon(by_id[item['id']], item) for item in placements]
    cell = max(20.0, gap * 4)

    def cell_keys(bounds, pad=0.0):
        x0 = math.floor((bounds[0] - pad) / cell)
        x1 = math.floor((bounds[2] + pad) / cell)
        y0 = math.floor((bounds[1] - pad) / cell)
        y1 = math.floor((bounds[3] + pad) / cell)
        return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    buckets = {}
    members = [[] for _ in shapes]

    def add(index):
        keys = cell_keys(shapes[index].bounds)
        members[index] = keys
        for key in keys:
            buckets.setdefault(key, []).append(index)

    def remove(index):
        for key in members[index]:
            buckets[key].remove(index)
        members[index] = []

    for index in range(len(shapes)):
        add(index)

    def blocked(index, shape):
        bounds = shape.bounds
        if bounds[0] < margin - 1e-6 or bounds[1] < margin - 1e-6 or bounds[2] > width - margin + 1e-6:
            return True
        seen = set()
        for key in cell_keys(bounds, pad=gap):
            for other_index in buckets.get(key, ()):
                if other_index == index or other_index in seen:
                    continue
                seen.add(other_index)
                other = shapes[other_index]
                if _box_gap(bounds, other.bounds) >= gap:
                    continue
                if shape.intersection(other).area > 0.0001 or shape.distance(other) < gap:
                    return True
        return False

    passes = 0
    for _pass in range(6):
        passes += 1
        order = sorted(range(len(placements)), key=lambda i: (shapes[i].bounds[1], shapes[i].bounds[0], placements[i]['id'], i))
        moved = False
        for index in order:
            drop_room = shapes[index].bounds[1] - margin
            if drop_room < 0.01:
                continue
            origin = shapes[index]
            low, high = 0.0, drop_room
            best_drop, best_shape = 0.0, None
            for _step in range(24):
                mid = (low + high) / 2
                shape = move_shape(origin, yoff=-mid)
                if blocked(index, shape):
                    high = mid
                else:
                    best_drop, best_shape = mid, shape
                    low = mid
            # When the whole drop is legal, the last midpoint stops just short of the margin.
            exact = move_shape(origin, yoff=-high)
            if not blocked(index, exact):
                best_drop, best_shape = high, exact
            if best_shape is not None and best_drop >= 0.01:
                remove(index)
                placements[index]['y'] = placements[index]['y'] - best_drop
                shapes[index] = best_shape
                add(index)
                moved = True
        if not moved:
            break
    used = max(shape.bounds[3] for shape in shapes) + margin
    if used >= result['usedLength'] - 1e-4:
        return result
    compacted = {**result, 'placements': placements, 'usedLength': used}
    try:
        checked = validate_result(job, compacted)
    except (ValueError, ZeroDivisionError):
        return result
    area = sum(shape.area for shape in checked)
    compacted['area'] = area
    compacted['utilization'] = area / (width * used)
    compacted['lengthBeforeCompaction'] = result['usedLength']
    compacted['compactionPasses'] = passes
    return compacted


def publish_result(path, result):
    if not path:
        return
    import json
    from pathlib import Path
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    payload = json.dumps({'ok': True, 'result': result})
    try:
        temporary.write_text(payload, encoding='utf-8')
        temporary.replace(path)
    except OSError:
        # Windows can briefly lock the preview while the server reads it.
        # Keep the last complete preview and the in-memory best solution; a
        # later update can retry. Final worker output is written separately and
        # its failures must still surface instead of claiming a saved result.
        return False
    return True


def solve(job, progress_path=None, incumbent=None):
    width, length, gap, margin, seconds = validate_job(job)
    if sum(p.get('quantity', 1) for p in job['parts']) > PIECE_CAP:
        raise ValueError('Use bounded allocation for more than 800 pieces.')
    started = time.monotonic()
    # Sparrow's finite axis is Y. Reflect x/y at the boundary of the adapter.
    # 0.10 mm outward guard exceeds the host's 0.05 mm curve flattening target.
    items, base_rotations, span = [], {}, 0.0
    separation = gap + 0.02
    usable = width - 2 * margin
    compensate = False
    for part in job['parts']:
        envelope, base, orientations = solver_part(part, job['settings']['rotations'], usable)
        base_rotations[part['id']] = base
        left, bottom, right, top = envelope.bounds
        span += (math.hypot(right - left, top - bottom) + separation) * part.get('quantity', 1)
        items.append(spyrrow.Item(part['id'], [(y, x) for x, y in envelope.exterior.coords], part.get('quantity', 1), orientations))
        if edge_padding_blocks_fit(envelope, orientations, usable, separation):
            compensate = True
    # Small extra clearance absorbs native floating-point error; zero gap remains valid.
    # Sparrow initializes strip length from area / width. For a tiny job on a
    # wide roll this can be smaller than its separation offset and panic.
    # No part needs more cross-roll space than its envelope diagonal. The sum
    # plus clearances accommodates every part side by side, at any orientation.
    # Restrict only the search region; retain the customer's full output width.
    # Native separation also applies to container edges. Expand the strip and
    # shift the origin back only when a handed envelope would not fit that
    # inset. Jobs that already fit keep the unexpanded strip, so their search
    # matches a full-time run without the shift.
    pad = separation if compensate else 0.0
    instance = spyrrow.StripPackingInstance('eznest', min(usable, span) + 2 * pad, items)
    progress_path = progress_path or job.get('_progress')

    def build(solution):
        result = {'placements': [{'id': p.id, 'rotation': base_rotations[p.id] - p.rotation, 'x': p.translation[1] + margin - pad, 'y': p.translation[0] + margin - pad} for p in solution.placed_items]}
        shapes = validate_result(job, result)
        used_length = max(p.bounds[3] for p in shapes) + margin
        area = sum(p.area for p in shapes)
        result.update({'width': width, 'usedLength': used_length, 'area': area, 'utilization': area / (width * used_length), 'elapsed': time.monotonic() - started, 'engine': 'Sparrow via spyrrow ' + spyrrow.__version__, 'validated': True})
        return result

    import threading
    best = copy.deepcopy(incumbent)
    if best is not None:
        validate_result(job, best)
    first_length = best['usedLength'] if best else None
    last_error = None
    part_polygons = {p['id']: part_polygon(p) for p in job['parts']}
    rotated_tops = {}
    feasible = (spyrrow.ReportType.ExplFeas, spyrrow.ReportType.CmprFeas, spyrrow.ReportType.Final)

    def extent(solution):
        tops = []
        for placement in solution.placed_items:
            angle = base_rotations[placement.id] - placement.rotation
            key = (placement.id, angle)
            if key not in rotated_tops:
                rotated_tops[key] = rotate(part_polygons[placement.id], angle, origin=(0,0)).bounds[3]
            tops.append(rotated_tops[key] + placement.translation[0] + 2 * margin - pad)
        return max(tops, default=math.inf)

    def consider(solution):
        nonlocal best, first_length
        if best is not None and extent(solution) >= best['usedLength'] - 1e-7:
            return
        candidate = build(solution)
        if first_length is None:
            first_length = candidate['usedLength']
        if best is None or candidate['usedLength'] < best['usedLength'] - 1e-7:
            best = candidate
            publish_result(progress_path, best)

    # The configured search time stays with the native solver. Reserving part
    # of a short budget for local repair made 180-piece rolls longer than the
    # same full-time search, so that reserve is not spent here.
    attempts = 3 if seconds >= 15 else 1
    deadline = time.monotonic() + seconds
    completed = 0
    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if attempt and remaining < 1:
            break
        budget = max(1, int(remaining / (attempts - attempt)))
        if attempts == 1:
            budget = int(seconds)
        if attempts > 1 and attempt == 0:
            budget = min(5, budget)
        config = spyrrow.StripPackingConfig(total_computation_time=budget,
            min_items_separation=gap + 0.02, num_workers=2,
            seed=(int(job['settings'].get('seed', 42)) + attempt * 104729) % 2147483648,
            early_termination=True)
        queue = spyrrow.ProgressQueue()
        holder, failure = {}, {}

        def run():
            try:
                holder['solution'] = instance.solve(config, queue)
            except BaseException as error:
                failure['error'] = error

        def drain():
            nonlocal last_error
            # Validate the shortest report first. Rechecking every tiny native
            # improvement can otherwise consume the search budget on complex art.
            reports = [s for kind,s in queue.drain() if kind in feasible]
            for solution in sorted(reports,key=extent):
                try:
                    consider(solution)
                    break
                except (ValueError, ZeroDivisionError) as error:
                    last_error = error

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        while thread.is_alive():
            drain()
            thread.join(0.2)
        drain()
        completed += 1
        if 'error' in failure:
            if isinstance(failure['error'], (KeyboardInterrupt, SystemExit)):
                raise failure['error']
            error = failure['error']
            if type(error).__module__ == 'pyo3_runtime' and type(error).__name__ == 'PanicException':
                error = ValueError('The nesting engine could not find a safe fit. Try a wider material or another search.')
            last_error = error
        if 'solution' in holder:
            try:
                consider(holder['solution'])
            except (ValueError, ZeroDivisionError) as error:
                last_error = error
    if best is None:
        raise last_error or ValueError('No valid layout was found within the search time.')
    # searchGain is the native search only. Settling onto the operator gap
    # happens after the budget is spent and does not change that figure.
    search_gain = max(0, (first_length - best['usedLength']) / first_length) if first_length else 0
    best = compact_result(job, best)
    rows = shelf_layout(job)
    if rows is not None and rows['usedLength'] < best['usedLength'] - 1e-4:
        rows = compact_result(job, rows)
        if rows['usedLength'] < best['usedLength'] - 1e-4:
            rows['engine'] = best.get('engine', 'eznest') + '; shorter shelf rows'
            rows['searchAttempts'] = completed
            best = rows
    best.update(elapsed=time.monotonic() - started, searchAttempts=completed, searchGain=search_gain)
    publish_result(progress_path, best)
    return best


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
