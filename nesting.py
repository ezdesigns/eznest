"""Required jobs first, followed by optional complete sticker sets in spare space."""
import copy
import json
import math
import sys
import time
from pathlib import Path
from shapely.geometry import Polygon
from shapely.affinity import rotate, translate
from shapely.strtree import STRtree
from engine import part_polygon, PIECE_CAP, solve, validate_job, validate_result, number
from production import validate_identity


def validate_request(job):
    if job['settings'].get('sheetLength') is not None:
        number(job['settings']['sheetLength'],'Maximum sheet length',10,5000)
        if job.get('fillJobs') and job.get('fillArea')=='length':
            raise ValueError('For automatic sheets, fill only leftover space. Use a single length for fixed-area sticker fill.')
    fills = job.get('fillJobs', [])
    if not isinstance(fills, list) or len(fills) > PIECE_CAP:
        raise ValueError(f'Choose up to {PIECE_CAP} sticker designs.')
    if job.get('fillArea', 'gaps') not in ('gaps', 'length'):
        raise ValueError('Choose a supported sticker fill area.')
    if not job.get('parts') and not fills:
        raise ValueError('Select a job or sticker fill design.')
    if fills and (not job.get('parts') or job.get('fillArea') == 'length') and job['settings'].get('maxLength') is None:
        raise ValueError('Enter a roll length to fill with stickers, or add required jobs and fill only their leftover space.')
    identities, codes, part_ids = set(), set(), set()
    groups = list(job.get('productionJobs', []))
    if job.get('parts'):
        validate_job(job)
        if groups:
            validate_identity(job)
    for fill in fills:
        limit = fill['maxSets']
        if type(limit) is not int or not 1 <= limit <= PIECE_CAP:
            raise ValueError(f'Sticker fill limit must be 1–{PIECE_CAP} complete sets.')
        source = fill['source']
        if source.get('role') != 'fill' or source['sets'] != limit:
            raise ValueError('Invalid sticker fill identity.')
        sample = {**job, 'parts': [{**p, 'quantity': p['perSet']} for p in fill['parts']],
                  'productionJobs': [{**source, 'sets': 1}]}
        validate_job(sample)
        validate_identity(sample)
        groups.append(source)
    for group in groups:
        if group['id'] in identities or group['code'] in codes or part_ids.intersection(group['partIds']):
            raise ValueError('Repeated job or piece identity in the queue.')
        identities.add(group['id']); codes.add(group['code']); part_ids.update(group['partIds'])
    if len(part_ids) > PIECE_CAP:
        raise ValueError(f'This build supports {PIECE_CAP} different piece designs.')


def fill_stickers(job, result, budget=None, copy_limit=PIECE_CAP):
    """Greedy contact/grid search; preserve all required placements and quantities.

    Attempts complete sets in queue order, one per job per round. The finite
    grid/time/copy limits mean the result is a best-found fill, not an optimum.
    """
    started = time.monotonic()
    fills = job.get('fillJobs', [])
    resolved = copy.deepcopy(job)
    resolved.pop('fillJobs', None)
    shapes = validate_result(job, result) if job.get('parts') else []
    settings = job['settings']
    width, margin, gap = settings['width'], settings['margin'], settings['gap']
    length = settings['maxLength'] if job.get('fillArea') == 'length' or not shapes else result['usedLength']
    guard = 0.10
    left, top, right, bottom = margin + guard, margin + guard, width - margin - guard, length - margin - guard
    deadline = started + (budget if budget is not None else min(15, max(3, settings['seconds'])))
    angles = settings['rotations'] if settings['rotations'] is not None else list(range(0, 360, 15))
    placed = list(result.get('placements', []))
    counts = [0] * len(fills)
    failed = set()
    orientations = {}
    buffered = {}
    for fill in fills:
        for part in fill['parts']:
            orientations[part['id']] = [(angle, rotate(part_polygon(part), angle, origin=(0, 0))) for angle in angles]

    def find(part, occupied):
        # The same conservative buffers, indexed without rebuilding their union
        # for every attempted piece. Exact intersection still decides each fit.
        for polygon in occupied:
            if polygon not in buffered:
                buffered[polygon] = polygon.buffer(gap + guard * 2, join_style=2)
        forbidden = STRtree([buffered[p] for p in occupied]) if occupied else None
        for angle, polygon in orientations[part['id']]:
            x0, y0, x1, y1 = polygon.bounds
            w, h = x1 - x0, y1 - y0
            if w > right - left or h > bottom - top:
                continue
            # Contacts recover close fits; a bounded grid also enters concavities.
            step = max(0.5, min(w, h) / 4, max(right-left, bottom-top) / 120)
            xs = {left, right-w}; ys = {top, bottom-h}
            xs.update(left+i*step for i in range(int((right-left-w)/step)+1))
            ys.update(top+i*step for i in range(int((bottom-top-h)/step)+1))
            for other in occupied:
                a,b,c,d = other.bounds
                xs.update((c+gap+0.201, a-gap-w-0.201))
                ys.update((d+gap+0.201, b-gap-h-0.201))
            xs = sorted(x for x in xs if left-1e-8 <= x <= right-w+1e-8)
            ys = sorted(y for y in ys if top-1e-8 <= y <= bottom-h+1e-8)
            for y in ys:
                for x in xs:
                    if time.monotonic() >= deadline:
                        return None
                    candidate = translate(polygon, x-x0, y-y0)
                    if forbidden is None or not len(forbidden.query(candidate, predicate='intersects')):
                        return candidate, {'id':part['id'], 'x':x-x0, 'y':y-y0, 'rotation':angle}
        return None

    while len(placed) < copy_limit and time.monotonic() < deadline:
        progress = False
        for index, fill in enumerate(fills):
            per_set = sum(p['perSet'] for p in fill['parts'])
            if index in failed or counts[index] >= fill['maxSets'] or len(placed)+per_set > copy_limit:
                continue
            trial_shapes, trial_placements = [], []
            # Place the most restrictive pieces first, retaining whole-set rollback.
            ordered = sorted(fill['parts'], key=lambda p: part_polygon(p).area, reverse=True)
            complete = True
            for part in ordered:
                for _ in range(part['perSet']):
                    found = find(part, shapes + trial_shapes)
                    if found is None:
                        complete = False
                        break
                    shape, placement = found
                    trial_shapes.append(shape); trial_placements.append(placement)
                if not complete:
                    break
            if len(trial_placements) != per_set:
                failed.add(index)
                continue
            shapes.extend(trial_shapes); placed.extend(trial_placements)
            counts[index] += 1; progress = True
        if not progress:
            break
    summaries = []
    for index, fill in enumerate(fills):
        count = counts[index]
        summaries.append({'id':fill['source']['id'], 'name':fill['source']['name'], 'code':fill['source']['code'],
                          'sets':count, 'maxSets':fill['maxSets'], 'pieces':count*sum(p['perSet'] for p in fill['parts'])})
        if count:
            resolved['productionJobs'].append({**fill['source'], 'sets':count, 'maxSets':fill['maxSets']})
            resolved['parts'].extend({**p, 'quantity':p['perSet']*count} for p in fill['parts'])
    if not placed:
        raise ValueError('No complete sticker set fitted in this area. Increase the length or check the preset.')
    used = length if job.get('fillArea') == 'length' or not job.get('parts') else result['usedLength']
    area = sum(p.area for p in shapes)
    final = {**result, 'placements':placed, 'width':width, 'usedLength':used, 'area':area,
             'utilization':area/(width*used), 'validated':True, 'fillSummary':summaries,
             'fillLimited': len(placed) >= copy_limit or time.monotonic() >= deadline,
             'fillElapsed':time.monotonic()-started}
    validate_result(resolved, final)
    validate_identity(resolved)
    return resolved, final


def refine_fill(job, resolved, result, budget):
    """Repack required pieces plus complete filler sets within the existing length.

    A failed trial never replaces the validated incumbent. No extra material,
    relaxed gaps, new angles, or partial sets are accepted to improve coverage.
    """
    limit = result['usedLength']
    counts = {s['id']: s['sets'] for s in result['fillSummary']}
    fills = sorted(job['fillJobs'], key=lambda f: sum(part_polygon(p).area*p['perSet'] for p in f['parts']), reverse=True)
    deadline = time.monotonic() + budget
    remaining = float(budget)
    attempts = 0
    failed = set()
    while remaining > 0 and attempts < 3 and time.monotonic() < deadline:
        eligible = [f for f in fills if f['source']['id'] not in failed
                    and counts[f['source']['id']] < f['maxSets']
                    and len(result['placements']) + sum(p['perSet'] for p in f['parts']) <= PIECE_CAP]
        if not eligible:
            break
        fill = eligible[0]
        trial_counts = {**counts, fill['source']['id']: counts[fill['source']['id']] + 1}
        trial = copy.deepcopy(job)
        trial.pop('fillJobs', None)
        for f in job['fillJobs']:
            count = trial_counts[f['source']['id']]
            if count:
                trial['productionJobs'].append({**f['source'], 'sets':count, 'maxSets':f['maxSets']})
                trial['parts'].extend({**p, 'quantity':p['perSet']*count} for p in f['parts'])
        trial['settings'].update(maxLength=limit,
                                 seed=(int(job['settings'].get('seed',42)) + attempts + 1) % 2147483648)
        attempts += 1
        from local_search import repack
        local_budget = min(1, remaining*.3, max(0,deadline-time.monotonic()))
        remaining -= local_budget
        additions = [p['id'] for p in fill['parts'] for _ in range(p['perSet'])]
        try:
            validate_identity(trial)
            # First freeze most of the incumbent and reinsert a small local
            # neighborhood plus the complete new set. Restart globally only
            # when local repair fails and the remaining budget can support it.
            candidate = repack(trial,result,local_budget,additions)
            if candidate is result:
                seconds = min(int(remaining), int(max(0,deadline-time.monotonic())))
                if seconds < 1:
                    failed.add(fill['source']['id'])
                    continue
                seconds = max(1, seconds // max(1, 3-attempts))
                remaining -= seconds
                trial['settings']['seconds'] = seconds
                candidate = solve(trial)
            validate_result(trial, candidate)
        except ValueError:
            failed.add(fill['source']['id'])
            continue
        candidate['usedLength'] = limit
        candidate['utilization'] = candidate['area'] / (candidate['width'] * limit)
        candidate['fillSummary'] = [{**s, 'sets':trial_counts[s['id']],
                                    'pieces':trial_counts[s['id']] * sum(p['perSet'] for p in next(f for f in job['fillJobs'] if f['source']['id']==s['id'])['parts'])}
                                   for s in result['fillSummary']]
        candidate['fillLimited'] = True  # Bounded search, not a proof of maximal fill.
        # Restore the operator's settings; the temporary length cap was a trial constraint.
        trial['settings'] = copy.deepcopy(job['settings'])
        validate_result(trial, candidate)
        validate_identity(trial)
        resolved, result, counts = trial, candidate, trial_counts
    result['fillRepackAttempts'] = attempts
    return resolved, result

def _run(job):
    progress = job.pop('_progress', None)
    validate_request(job)
    if job['settings'].get('sheetLength') is not None:
        from sheets import split_nest, subset
        if not job.get('parts'):
            raise ValueError('For sticker-only fill, use a roll length and leave automatic sheets off.')
        result = split_nest(job, progress if not job.get('fillJobs') else None)
        if job.get('fillJobs'):
            # Fill each sheet without extending it; carry remaining whole-set limits.
            merged=copy.deepcopy(job); merged.pop('fillJobs',None)
            summaries={f['source']['id']:{'id':f['source']['id'],'name':f['source']['name'],'code':f['source']['code'],'sets':0,'maxSets':f['maxSets'],'pieces':0} for f in job['fillJobs']}
            placements=[]; remaining=PIECE_CAP-len(result['placements'])
            for sheet in result['sheets']:
                local=[{**p,'y':p['y']-sheet['offset']} for p in result['placements'] if p['sheet']==sheet['index']]
                local_job=subset(job,local); local_job['settings']={**job['settings'],'maxLength':sheet['usedLength']}; local_job['fillArea']='gaps'
                local_job['productionJobs']=[]
                local_job['fillJobs']=[]
                for fill in job['fillJobs']:
                    available=min(fill['maxSets']-summaries[fill['source']['id']]['sets'],remaining//sum(p['perSet'] for p in fill['parts']))
                    if available>0: local_job['fillJobs'].append({**fill,'maxSets':available})
                # fill_stickers validates identities; sheet subsets are incomplete
                # sets, so run geometry fill with a per-sheet synthetic identity.
                if local_job['fillJobs']:
                    local_job['productionJobs']=[{**s,'sets':1,'partIds':[p['id'] for p in local_job['parts'] if p['sourceJobId']==s['id']]} for s in job['productionJobs'] if any(p['sourceJobId']==s['id'] for p in local_job['parts'])]
                    local_job['parts']=[{**p,'perSet':p['quantity']} for p in local_job['parts']]
                    resolved,filled=fill_stickers(local_job,{'width':result['width'],'usedLength':sheet['usedLength'],'placements':local},budget=max(1,min(5,job['settings']['seconds']/len(result['sheets']))),copy_limit=len(local)+remaining)
                    local=filled['placements']
                    for summary in filled['fillSummary']:
                        target=summaries[summary['id']]; target['sets']+=summary['sets']; target['pieces']+=summary['pieces']; remaining-=summary['pieces']
                placements.extend({**p,'sheet':sheet['index'],'y':p['y']+sheet['offset']} for p in local)
            for fill in job['fillJobs']:
                count=summaries[fill['source']['id']]['sets']
                if count:
                    merged['productionJobs'].append({**fill['source'],'sets':count})
                    merged['parts'].extend({**p,'quantity':p['perSet']*count} for p in fill['parts'])
            result.update(placements=placements,fillSummary=list(summaries.values()),fillLimited=remaining<=0)
            shapes=validate_result(merged,result); result['area']=sum(s.area for s in shapes); result['utilization']=result['area']/(result['width']*result['usedLength'])
            for sheet in result['sheets']:
                sheet['pieces']=sum(p['sheet']==sheet['index'] for p in result['placements'])
                sheet['area']=sum(shape.area for p,shape in zip(result['placements'],shapes) if p['sheet']==sheet['index'])
            return {'ok':True,'job':merged,'result':result,'requestJob':job}
        return {'ok':True,'result':result}
    budget = int(job['settings']['seconds'])
    repack_budget = max(1, budget // 3) if job.get('parts') and job.get('fillJobs') and budget >= 3 else 0
    required = {**job, 'settings':{**job['settings'], 'seconds':budget-repack_budget}}
    result = solve(required, progress) if job.get('parts') else {'placements':[], 'usedLength':job['settings']['maxLength'], 'elapsed':0, 'engine':'eznest sticker fill'}
    if job.get('fillJobs'):
        # Continue a productive required-piece search before filling; when it
        # has plateaued, spend the reserve on complete-set hole repair instead.
        # A continuation is an independent start with a validated incumbent,
        # not a claim that the native engine supports warm starts.
        strategy = 'fill'
        if repack_budget and job.get('fillArea','gaps') == 'gaps' and result.get('searchGain',0) >= .01:
            continuation = {**required, 'settings':{**required['settings'], 'seconds':repack_budget,
                'seed':(int(job['settings'].get('seed',42))+524287) % 2147483648}}
            result = solve(continuation, progress, incumbent=result)
            repack_budget = 0
            strategy = 'required'
        resolved, result = fill_stickers(job, result)
        if repack_budget:
            resolved, result = refine_fill(job, resolved, result, repack_budget)
        result['reserveStrategy'] = strategy
        return {'ok':True, 'job':resolved, 'result':result, 'requestJob':job}
    return {'ok':True, 'result':result}


def run(job):
    started=time.monotonic()
    payload=_run(job)
    payload['result']['elapsed']=time.monotonic()-started
    return payload


def worker(request, output):
    request, output = Path(request), Path(output)
    try:
        job = json.loads(request.read_text(encoding='utf-8-sig'))
        job['_progress'] = str(output.with_name('progress.json'))
        payload = run(job)
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        payload = {'ok':False, 'error':str(error)}
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload), encoding='utf-8')
    temporary.replace(output)


if __name__ == '__main__':
    worker(*sys.argv[1:3])
