#!/usr/bin/env python3
"""Repeatable nesting benchmark for the local engine.

Runs a fixed, committed set of jobs through the same entry point as the shop
(`nesting.run`). Prints a table and writes machine-readable JSON. A compare
mode flags length or utilization regressions beyond 0.3 percent.

No network access. Given the same seed, case list and engine, a case is
deterministic. Wall time is reported and is not a pass/fail gate.

Usage:
  python tools/nest_bench.py --out tools/fixtures/nest_bench_baseline.json
  python tools/nest_bench.py --out /tmp/nest-new.json
  python tools/nest_bench.py --compare tools/fixtures/nest_bench_baseline.json /tmp/nest-new.json
  python tools/nest_bench.py --cases workshop_quarters_seed42,sticker_sheet_quarters_seed42
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / 'tools' / 'fixtures' / 'nest_outlines.json'
REGRESSION = 0.003  # 0.3 percent. Smaller moves are treated as noise.

# Seconds are the solver budget the shop would pass in. Continuous rectangular
# orders leave that budget unused; the row layout is closed-form.
_QUARTERS = [0, 90, 180, 270]


def _case(case_id, seed, seconds, parts, rotations, width=180, gap=3, margin=5,
          continuous=False, sheet_length=None):
    return {
        'id': case_id,
        'seed': seed,
        'seconds': seconds,
        'width': width,
        'gap': gap,
        'margin': margin,
        'rotations': rotations,
        'continuous': continuous,
        'sheetLength': sheet_length,
        'parts': parts,
    }


def case_table():
    """Fixed jobs. Edit this list, then regenerate outlines only when shapes change."""
    sticker = [('sticker_24x18', 16)]
    demo = [
        ('trail_panel', 2), ('trail_badge', 2), ('trail_triangle', 2), ('trail_label', 2),
        ('helmet_side', 2), ('helmet_plate', 2),
    ]
    mix60 = [
        ('rect_24x18', 20), ('rect_40x15', 10), ('rect_18x18', 12),
        ('ell_panel', 8), ('triangle_60', 6), ('small_10x8', 4),
    ]
    mix180 = [(name, qty * 3) for name, qty in mix60]
    odd = [
        ('c_notch', 5), ('arrow', 4), ('ell_panel', 3), ('trail_badge', 3),
        ('triangle_60', 4), ('small_10x8', 8),
    ]
    workshop = [
        ('workshop_L', 1), ('workshop_T', 1), ('workshop_R', 1),
        ('workshop_P', 1), ('workshop_L2', 1), ('workshop_T2', 1),
    ]
    rows = [
        _case('sticker_sheet_quarters_seed42', 42, 3, sticker, _QUARTERS, width=120),
        _case('sticker_sheet_quarters_seed7', 7, 3, sticker, _QUARTERS, width=120),
        _case('sticker_sheet_locked_seed42', 42, 3, sticker, [0], width=120),
        _case('sticker_pages_quarters_seed42', 42, 3, [('sticker_24x18', 12)], _QUARTERS,
              width=100, sheet_length=140),
        _case('mixed_demo_quarters_seed42', 42, 4, demo, _QUARTERS),
        _case('mixed_demo_quarters_seed99', 99, 4, demo, _QUARTERS),
        _case('mixed_demo_locked_seed42', 42, 4, demo, [0]),
        _case('pieces60_quarters_seed42', 42, 4, mix60, _QUARTERS),
        _case('pieces60_quarters_seed7', 7, 4, mix60, _QUARTERS),
        _case('pieces60_locked_seed42', 42, 4, mix60, [0]),
        _case('pieces180_quarters_seed42', 42, 5, mix180, _QUARTERS),
        _case('pieces180_quarters_seed3', 3, 5, mix180, _QUARTERS),
        _case('pieces180_locked_seed42', 42, 5, mix180, [0]),
        _case('continuous_1000_quarters_seed42', 42, 1, [('rect_24x18', 1000)], _QUARTERS, continuous=True),
        _case('continuous_1000_locked_seed42', 42, 1, [('rect_24x18', 1000)], [0], continuous=True),
        _case('continuous_1000_free_seed42', 42, 1, [('rect_24x18', 1000)], None, continuous=True),
        _case('concave_quarters_seed42', 42, 4, odd, _QUARTERS),
        _case('concave_quarters_seed11', 11, 4, odd, _QUARTERS),
        _case('concave_free_seed42', 42, 4, odd, None),
        _case('concave_locked_seed42', 42, 4, odd, [0]),
        _case('workshop_quarters_seed42', 42, 3, workshop, _QUARTERS),
        _case('workshop_quarters_seed1', 1, 3, workshop, _QUARTERS),
        _case('workshop_locked_seed42', 42, 3, workshop, [0]),
    ]
    return rows


def _round_points(points):
    cleaned = []
    for x, y in points:
        point = [round(float(x), 4), round(float(y), 4)]
        if cleaned and math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) < 1e-4:
            continue
        cleaned.append(point)
    if len(cleaned) > 1 and math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) < 1e-4:
        cleaned.pop()
    return cleaned


def _normalize(points):
    pts = [(float(x), float(y)) for x, y in points]
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    return _round_points((x - minx, y - miny) for x, y in pts)


def _rounded_rect(width, height, radius):
    """Rounded rectangle inside the requested box. Corner error stays under 0.02 mm."""
    from shapely.geometry import box
    radius = min(float(radius), width / 2, height / 2)
    core = box(radius, radius, width - radius, height - radius)
    polygon = core.buffer(radius, quad_segs=16)
    return _normalize(polygon.exterior.coords)


def _flatten_cubic(p0, p1, p2, p3, tolerance=0.02):
    def midpoint(a, b):
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    def deviation(point, start, end):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.hypot(point[0] - start[0], point[1] - start[1])
        t = max(0, min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
        return math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)

    output = [p0]

    def walk(a, b, c, d, depth):
        if depth > 24 or (deviation(b, a, d) <= tolerance and deviation(c, a, d) <= tolerance):
            output.append(d)
            return
        ab, bc, cd = midpoint(a, b), midpoint(b, c), midpoint(c, d)
        abc, bcd = midpoint(ab, bc), midpoint(bc, cd)
        mid = midpoint(abc, bcd)
        walk(a, ab, abc, mid, depth + 1)
        walk(mid, bcd, cd, d, depth + 1)

    walk(p0, p1, p2, p3, 0)
    return output


def _rotate(point, degrees, origin):
    theta = math.radians(degrees)
    cos, sin = math.cos(theta), math.sin(theta)
    x, y = point[0] - origin[0], point[1] - origin[1]
    return (origin[0] + x * cos - y * sin, origin[1] + x * sin + y * cos)


def build_outlines():
    """Polygons traced from the shop demos and the workshop sample.

    Straight demo paths are exact. Curves use the same 0.02 mm chord limit the
    SVG importer targets. These are synthetic stand-ins, not customer files.
    """
    sticker = _rounded_rect(24, 18, 4)
    plate = _rounded_rect(35, 55, 8)
    badge = _flatten_cubic((0, 17), (0, -5), (66, -5), (66, 17))
    badge.extend([(66, 51), (0, 51)])
    label = _rounded_rect(72, 25, 6)
    label = _normalize(_rotate(point, -8, (0, 0)) for point in label)
    # The demo label is rotated about a page point. Rotation about the local
    # origin is the same outline; only the page position changes.
    sample = json.loads((ROOT / 'sample.json').read_text(encoding='utf-8'))
    by_id = {part['id']: part['points'] for part in sample['parts']}
    outlines = {
        'sticker_24x18': sticker,
        'rect_24x18': [[0, 0], [24, 0], [24, 18], [0, 18]],
        'rect_40x15': [[0, 0], [40, 0], [40, 15], [0, 15]],
        'rect_18x18': [[0, 0], [18, 0], [18, 18], [0, 18]],
        'small_10x8': [[0, 0], [10, 0], [10, 8], [0, 8]],
        'triangle_60': [[0, 0], [60, 0], [0, 60]],
        'ell_panel': [[0, 0], [68, 0], [68, 23], [25, 23], [25, 67], [0, 67]],
        'c_notch': [[0, 0], [50, 0], [50, 12], [14, 12], [14, 28], [50, 28], [50, 40], [0, 40]],
        'arrow': [[0, 15], [36, 0], [36, 10], [70, 10], [70, 20], [36, 20], [36, 30]],
        'trail_panel': [[0, 0], [68, 0], [68, 23], [25, 23], [25, 67], [0, 67]],
        'trail_badge': _normalize(badge),
        'trail_triangle': [[0, 0], [62, 55], [0, 55]],
        'trail_label': label,
        'helmet_side': [[0, 0], [60, 0], [60, 18], [25, 18], [25, 40], [0, 40]],
        'helmet_plate': plate,
        'workshop_L': by_id['L-01'],
        'workshop_T': by_id['T-01'],
        'workshop_R': by_id['R-01'],
        'workshop_P': by_id['P-01'],
        'workshop_L2': by_id['L-02'],
        'workshop_T2': by_id['T-02'],
    }
    sources = {
        'sticker_24x18': 'queue-app.js Shop stickers.svg, 24 mm by 18 mm, corner radius 4',
        'rect_24x18': 'Same sticker size with square corners, used for the 60/180/1000 counts',
        'rect_40x15': 'Synthetic label in the 60 and 180 piece mixes',
        'rect_18x18': 'Synthetic square in the 60 and 180 piece mixes',
        'small_10x8': 'Synthetic filler used to exercise gaps in odd layouts',
        'triangle_60': 'Synthetic right triangle',
        'ell_panel': 'sample-artwork.svg clipped panel, translate removed',
        'c_notch': 'Synthetic concave C. Not a customer file',
        'arrow': 'Synthetic concave arrow. Not a customer file',
        'trail_panel': 'sample-artwork.svg #clipped-panel clip path',
        'trail_badge': 'sample-artwork.svg #EZN_BOUNDARY_badge cubic, flattened to 0.02 mm',
        'trail_triangle': 'sample-artwork.svg #CutContour_Kiss-cut triangle',
        'trail_label': 'sample-artwork.svg #small-label rounded rect rotated -8 degrees',
        'helmet_side': 'queue-app.js Helmet graphics.svg #side-panel',
        'helmet_plate': 'queue-app.js Helmet graphics.svg #name-plate, 35 by 55, radius 8',
        'workshop_L': 'sample.json L-01',
        'workshop_T': 'sample.json T-01',
        'workshop_R': 'sample.json R-01',
        'workshop_P': 'sample.json P-01',
        'workshop_L2': 'sample.json L-02',
        'workshop_T2': 'sample.json T-02',
    }
    return {'version': 1, 'sources': sources, 'outlines': outlines}


def write_fixtures(path=FIXTURE):
    payload = build_outlines()
    from shapely.geometry import Polygon
    for name, points in payload['outlines'].items():
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area < 0.01 or len(points) < 3:
            raise SystemExit(f'Outline {name} is not a usable polygon.')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


def load_outlines(path=FIXTURE):
    payload = json.loads(path.read_text(encoding='utf-8'))
    return payload['outlines'], payload


def fixture_digest(path=FIXTURE):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job_from_case(case, outlines):
    parts = []
    for index, (name, quantity) in enumerate(case['parts'], start=1):
        if name not in outlines:
            raise KeyError(f"{case['id']} references unknown outline {name}")
        parts.append({
            'id': f'{name}-{index}',
            'name': name,
            'points': outlines[name],
            'quantity': quantity,
        })
    settings = {
        'width': case['width'],
        'maxLength': None,
        'gap': case['gap'],
        'margin': case['margin'],
        'seconds': case['seconds'],
        'rotations': case['rotations'],
        'seed': case['seed'],
    }
    if case['continuous']:
        settings['continuous'] = True
    if case['sheetLength'] is not None:
        settings['sheetLength'] = case['sheetLength']
    return {'name': case['id'], 'parts': parts, 'settings': settings}


def _bbox_gap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(0.0, bx0 - ax1, ax0 - bx1)
    dy = max(0.0, by0 - ay1, ay0 - by1)
    if dx == 0 and dy == 0:
        return 0.0
    return math.hypot(dx, dy)


def exact_all_pairs(shapes, gap):
    """Exact pairwise clearance.

    A bounding-box gap is a lower bound on the true distance, so a pair can be
    skipped only when that bound is already past both the required gap and the
    closest distance found so far. Overlaps have a box gap of zero and are never
    skipped.
    """
    overlaps = 0
    closest = None
    for index, shape in enumerate(shapes):
        bounds = shape.bounds
        for other_index in range(index):
            other = shapes[other_index]
            separation = _bbox_gap(bounds, other.bounds)
            if closest is not None and separation >= max(closest, gap):
                continue
            distance = shape.distance(other)
            if closest is None or distance < closest:
                closest = distance
            too_close = distance + 0.001 < gap
            if too_close or shape.intersection(other).area > 0.0001:
                overlaps += 1
    return {'overlapPairs': overlaps, 'minGapMm': closest}


def validate_case(job, result):
    """Independent of the solver's spatial index. Sheets are checked separately."""
    from shapely.geometry import box
    from engine import placed_polygon, validate_result

    engine_error = None
    try:
        validate_result(job, result)
    except (ValueError, ZeroDivisionError) as error:
        engine_error = str(error)
    expected = sum(part.get('quantity', 1) for part in job['parts'])
    placements = result.get('placements') or []
    if len(placements) != expected:
        return {
            'ok': False,
            'engineError': engine_error or 'Piece count does not match the job.',
            'overlapPairs': None,
            'minGapMm': None,
            'marginOk': False,
            'pieces': len(placements),
        }
    by_id = {part['id']: part for part in job['parts']}
    gap = job['settings']['gap']
    margin = job['settings']['margin']
    width = job['settings']['width']
    sheets = result.get('sheets') or [{'index': 0, 'offset': 0, 'usedLength': result['usedLength']}]
    overlap_pairs = 0
    min_gap = None
    margin_ok = True
    for sheet in sheets:
        local = []
        for placement in placements:
            if placement.get('sheet', 0) != sheet['index']:
                continue
            moved = dict(placement)
            moved['y'] = placement['y'] - sheet['offset']
            shape = placed_polygon(by_id[placement['id']], moved)
            local.append(shape)
            boundary = box(margin, margin, width - margin, sheet['usedLength'] - margin)
            if not boundary.buffer(0.001).covers(shape):
                margin_ok = False
        report = exact_all_pairs(local, gap)
        overlap_pairs += report['overlapPairs']
        if report['minGapMm'] is not None and (min_gap is None or report['minGapMm'] < min_gap):
            min_gap = report['minGapMm']
    ok = engine_error is None and overlap_pairs == 0 and margin_ok and len(placements) == expected
    return {
        'ok': ok,
        'engineError': engine_error,
        'overlapPairs': overlap_pairs,
        'minGapMm': min_gap,
        'marginOk': margin_ok,
        'pieces': len(placements),
    }


def piece_area(job):
    from shapely.geometry import Polygon
    total = 0.0
    for part in job['parts']:
        total += Polygon(part['points']).area * part.get('quantity', 1)
    return total


def run_case(case, outlines):
    from nesting import run
    job = job_from_case(case, outlines)
    started = time.perf_counter()
    error = None
    result = None
    try:
        payload = run(job)
        result = payload['result']
    except (ValueError, ZeroDivisionError, KeyError) as exc:
        error = str(exc)
    elapsed = time.perf_counter() - started
    area = piece_area(job)
    record = {
        'id': case['id'],
        'seed': case['seed'],
        'seconds': case['seconds'],
        'rotations': case['rotations'],
        'continuous': case['continuous'],
        'sheetLength': case['sheetLength'],
        'widthMm': case['width'],
        'gapMm': case['gap'],
        'marginMm': case['margin'],
        'pieces': sum(qty for _, qty in case['parts']),
        'pieceAreaMm2': round(area, 4),
        'wallTimeS': round(elapsed, 4),
        'error': error,
    }
    if result is None:
        record.update({
            'rollLengthMm': None,
            'materialAreaMm2': None,
            'wastedAreaMm2': None,
            'utilizationPct': None,
            'overlapPairs': None,
            'minGapMm': None,
            'marginOk': False,
            'validationOk': False,
            'engine': None,
            'searchAttempts': None,
        })
        return record
    length = float(result['usedLength'])
    material = case['width'] * length
    check = validate_case(job, result)
    record.update({
        'rollLengthMm': round(length, 4),
        'materialAreaMm2': round(material, 4),
        'wastedAreaMm2': round(material - area, 4),
        'utilizationPct': round(100 * area / material, 4) if material else None,
        'overlapPairs': check['overlapPairs'],
        'minGapMm': None if check['minGapMm'] is None else round(check['minGapMm'], 4),
        'marginOk': check['marginOk'],
        'validationOk': check['ok'],
        'engineError': check['engineError'],
        'engine': result.get('engine'),
        'searchAttempts': result.get('searchAttempts'),
        'sheetCount': len(result.get('sheets') or [1]),
    })
    return record


def summarize(cases):
    valid = [case for case in cases if case.get('validationOk') and case.get('rollLengthMm')]
    lengths = [case['rollLengthMm'] for case in valid]
    utils = [case['utilizationPct'] for case in valid]
    return {
        'cases': len(cases),
        'valid': len(valid),
        'invalid': len(cases) - len(valid),
        'totalRollLengthMm': round(sum(lengths), 4) if lengths else None,
        'meanRollLengthMm': round(sum(lengths) / len(lengths), 4) if lengths else None,
        'meanUtilizationPct': round(sum(utils) / len(utils), 4) if utils else None,
        'totalWastedAreaMm2': round(sum(case['wastedAreaMm2'] for case in valid), 4) if valid else None,
        'totalWallTimeS': round(sum(case['wallTimeS'] for case in cases), 4),
    }


def rotation_label(rotations):
    if rotations is None:
        return 'free'
    if rotations == [0]:
        return 'locked'
    if rotations == [0, 90, 180, 270]:
        return 'quarters'
    return ','.join(str(angle) for angle in rotations)


def format_table(report):
    headers = ('case', 'pcs', 'seed', 'rot', 'length_mm', 'util_%', 'waste_mm2', 'min_gap', 'time_s', 'ok')
    rows = []
    for case in report['cases']:
        rows.append((
            case['id'],
            str(case['pieces']),
            str(case['seed']),
            rotation_label(case['rotations']),
            '' if case['rollLengthMm'] is None else f"{case['rollLengthMm']:.2f}",
            '' if case['utilizationPct'] is None else f"{case['utilizationPct']:.2f}",
            '' if case['wastedAreaMm2'] is None else f"{case['wastedAreaMm2']:.1f}",
            '' if case['minGapMm'] is None else f"{case['minGapMm']:.3f}",
            f"{case['wallTimeS']:.2f}",
            'yes' if case['validationOk'] else 'NO',
        ))
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    def line(cells):
        return '  '.join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()
    out = [line(headers), line(tuple('-' * width for width in widths))]
    out.extend(line(row) for row in rows)
    summary = report['summary']
    out.append('')
    out.append(
        f"valid {summary['valid']}/{summary['cases']}  "
        f"mean length {summary['meanRollLengthMm']} mm  "
        f"mean utilization {summary['meanUtilizationPct']}%  "
        f"total length {summary['totalRollLengthMm']} mm  "
        f"total waste {summary['totalWastedAreaMm2']} mm2  "
        f"wall {summary['totalWallTimeS']} s"
    )
    return '\n'.join(out)


def build_report(selected, outlines):
    records = []
    for index, case in enumerate(selected, start=1):
        print(f'[{index}/{len(selected)}] {case["id"]}', file=sys.stderr, flush=True)
        records.append(run_case(case, outlines))
    return {
        'benchmark': 'eznest-nest-bench',
        'version': 1,
        'fixtureSha256': fixture_digest(),
        'caseIds': [case['id'] for case in selected],
        'regressionThreshold': REGRESSION,
        'summary': summarize(records),
        'cases': records,
    }


def _relative_worse_length(baseline, new):
    if baseline is None or new is None:
        return new != baseline
    if baseline <= 0:
        return new > baseline
    return new > baseline * (1 + REGRESSION)


def _relative_worse_util(baseline, new):
    if baseline is None or new is None:
        return baseline != new
    if baseline <= 0:
        return False
    return new < baseline * (1 - REGRESSION)


def compare_reports(baseline, new):
    """Return a compare payload. A case regresses when length grows or utilization falls by more than 0.3%."""
    base_cases = {case['id']: case for case in baseline['cases']}
    new_cases = {case['id']: case for case in new['cases']}
    ids = list(dict.fromkeys([*baseline.get('caseIds', base_cases), *new.get('caseIds', new_cases)]))
    rows = []
    regressions = []
    improvements = []
    fixture_changed = baseline.get('fixtureSha256') != new.get('fixtureSha256')
    for case_id in ids:
        before = base_cases.get(case_id)
        after = new_cases.get(case_id)
        if before is None or after is None:
            regressions.append(case_id)
            rows.append({'id': case_id, 'status': 'missing', 'detail': 'Case is not in both reports.'})
            continue
        reasons = []
        if before.get('pieces') != after.get('pieces') or abs((before.get('pieceAreaMm2') or 0) - (after.get('pieceAreaMm2') or 0)) > 0.05:
            reasons.append('piece set changed')
        if not after.get('validationOk'):
            reasons.append('validation failed')
        elif not before.get('validationOk'):
            reasons.append('baseline validation failed')
        if _relative_worse_length(before.get('rollLengthMm'), after.get('rollLengthMm')):
            reasons.append('roll length regressed')
        if _relative_worse_util(before.get('utilizationPct'), after.get('utilizationPct')):
            reasons.append('utilization regressed')
        length_delta = None
        util_delta = None
        if before.get('rollLengthMm') and after.get('rollLengthMm'):
            length_delta = (after['rollLengthMm'] - before['rollLengthMm']) / before['rollLengthMm']
        if before.get('utilizationPct') and after.get('utilizationPct'):
            util_delta = (after['utilizationPct'] - before['utilizationPct']) / before['utilizationPct']
        status = 'regression' if reasons else 'same'
        if not reasons and length_delta is not None and length_delta < -REGRESSION:
            status = 'improved'
            improvements.append(case_id)
        if reasons:
            regressions.append(case_id)
        rows.append({
            'id': case_id,
            'status': status,
            'reasons': reasons,
            'baselineLengthMm': before.get('rollLengthMm'),
            'newLengthMm': after.get('rollLengthMm'),
            'lengthDeltaPct': None if length_delta is None else round(100 * length_delta, 4),
            'baselineUtilPct': before.get('utilizationPct'),
            'newUtilPct': after.get('utilizationPct'),
            'utilDeltaPct': None if util_delta is None else round(100 * util_delta, 4),
            'baselineValid': before.get('validationOk'),
            'newValid': after.get('validationOk'),
        })
    base_summary = baseline['summary']
    new_summary = new['summary']
    mean_length_delta = None
    mean_util_delta = None
    if base_summary.get('meanRollLengthMm') and new_summary.get('meanRollLengthMm'):
        mean_length_delta = (new_summary['meanRollLengthMm'] - base_summary['meanRollLengthMm']) / base_summary['meanRollLengthMm']
    if base_summary.get('meanUtilizationPct') and new_summary.get('meanUtilizationPct'):
        mean_util_delta = (new_summary['meanUtilizationPct'] - base_summary['meanUtilizationPct']) / base_summary['meanUtilizationPct']
    return {
        'fixtureChanged': fixture_changed,
        'regressions': regressions,
        'improvements': improvements,
        'thresholdPct': REGRESSION * 100,
        'meanLengthDeltaPct': None if mean_length_delta is None else round(100 * mean_length_delta, 4),
        'meanUtilDeltaPct': None if mean_util_delta is None else round(100 * mean_util_delta, 4),
        'baselineSummary': base_summary,
        'newSummary': new_summary,
        'cases': rows,
    }


def format_compare(report):
    lines = []
    if report['fixtureChanged']:
        lines.append('Fixture hash changed. Length deltas are not comparable until a new baseline is recorded.')
    lines.append(
        f"mean length {report['meanLengthDeltaPct']}%  mean utilization {report['meanUtilDeltaPct']}%  "
        f"improved {len(report['improvements'])}  regressed {len(report['regressions'])}  "
        f"threshold {report['thresholdPct']}%"
    )
    lines.append(f"{'case':<40} {'status':<12} {'base_mm':>10} {'new_mm':>10} {'d_len_%':>8} {'d_util_%':>8}")
    for row in report['cases']:
        lines.append(
            f"{row['id']:<40} {row['status']:<12} "
            f"{'' if row.get('baselineLengthMm') is None else format(row['baselineLengthMm'], '.2f'):>10} "
            f"{'' if row.get('newLengthMm') is None else format(row['newLengthMm'], '.2f'):>10} "
            f"{'' if row.get('lengthDeltaPct') is None else format(row['lengthDeltaPct'], '.3f'):>8} "
            f"{'' if row.get('utilDeltaPct') is None else format(row['utilDeltaPct'], '.3f'):>8}"
            + (('  ' + '; '.join(row['reasons'])) if row.get('reasons') else '')
        )
    return '\n'.join(lines)


def select_cases(names):
    table = case_table()
    if not names:
        return table
    wanted = {name.strip() for name in names.split(',') if name.strip()}
    selected = [case for case in table if case['id'] in wanted]
    missing = wanted - {case['id'] for case in selected}
    if missing:
        raise SystemExit('Unknown case: ' + ', '.join(sorted(missing)))
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description='Benchmark EZ Nest material use on a fixed job set.')
    parser.add_argument('--out', type=Path, help='Write the JSON report here.')
    parser.add_argument('--compare', nargs=2, metavar=('BASELINE', 'NEW'), help='Compare two JSON reports.')
    parser.add_argument('--cases', help='Comma-separated case ids. Default is the full set.')
    parser.add_argument('--write-fixtures', action='store_true', help='Regenerate tools/fixtures/nest_outlines.json and exit.')
    parser.add_argument('--list', action='store_true', help='List case ids and exit.')
    args = parser.parse_args(argv)
    if args.write_fixtures:
        path = write_fixtures()
        print(path)
        return 0
    if args.list:
        for case in case_table():
            print(case['id'])
        return 0
    if args.compare:
        baseline = json.loads(Path(args.compare[0]).read_text(encoding='utf-8'))
        new = json.loads(Path(args.compare[1]).read_text(encoding='utf-8'))
        report = compare_reports(baseline, new)
        print(format_compare(report))
        if args.out:
            args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if report['fixtureChanged'] or report['regressions']:
            return 1
        return 0
    outlines, _payload = load_outlines()
    report = build_report(select_cases(args.cases), outlines)
    print(format_table(report))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if report['summary']['invalid']:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
