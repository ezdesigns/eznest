"""Whole-piece sheet allocation with a valid fallback for every optimized sheet."""
import copy
import math
import time
from collections import Counter
from shapely.geometry import Polygon
from shapely.affinity import rotate
from engine import part_polygon, solve, validate_job, validate_result, number, publish_result, compact_result, PIECE_CAP, ORDER_PIECE_CAP


def subset(job, placements):
    counts=Counter(p['id'] for p in placements)
    return {**job,'parts':[{**p,'quantity':counts[p['id']]} for p in job['parts'] if counts[p['id']]]}


def continuous_nest(job, progress_path=None):
    """One physical page, with bounded search and full independent validation."""
    started = time.monotonic()
    validate_job(job)
    settings = job['settings']
    width, margin, gap = settings['width'], settings['margin'], settings['gap']
    limit = min(5000, settings.get('maxLength') or 5000)
    count = sum(p.get('quantity', 1) for p in job['parts'])
    bounded = {**job, 'settings': {**settings, 'maxLength': None, 'sheetLength': limit, 'continuous': False}}
    candidates = []
    polygons = [part_polygon(p) for p in job['parts']]
    area_needed = sum(p.area*part.get('quantity',1) for p,part in zip(polygons,job['parts']))
    if area_needed > (width-2*margin)*(limit-2*margin):
        raise ValueError('This order cannot fit the continuous PDF limit (196.85 in / 16.4 ft) or the available roll. Use shorter print sections or fewer copies.')
    # Repeated almost-rectangular envelopes benefit from comparing whole-order
    # row orientations. No outline, print pixels, bleed or spacing is reduced.
    dims = [(p.bounds[2]-p.bounds[0], p.bounds[3]-p.bounds[1]) for p in polygons]
    repeated = (all(p.area >= w*h*.98 for p, (w,h) in zip(polygons,dims))
                and max(w for w,h in dims)-min(w for w,h in dims) < .02
                and max(h for w,h in dims)-min(h for w,h in dims) < .02)
    if repeated:
        for angle in settings['rotations'] or range(0, 180, 5):
            bounds = [rotate(p, angle, origin=(0,0)).bounds for p in polygons]
            cell_w = max(b[2]-b[0] for b in bounds) + .22
            cell_h = max(b[3]-b[1] for b in bounds) + .22
            columns = int((width-2*margin+gap)/(cell_w+gap))
            if columns < 1: continue
            length = 2*margin + math.ceil(count/columns)*(cell_h+gap)-gap
            if length > limit: continue
            placements = []
            for part, b in zip(job['parts'], bounds):
                for _ in range(part.get('quantity',1)):
                    row, col = divmod(len(placements), columns)
                    placements.append({'id':part['id'], 'x':margin+.11+col*(cell_w+gap)-b[0],
                                       'y':margin+.11+row*(cell_h+gap)-b[1], 'rotation':angle})
            candidates.append({'width':width,'usedLength':length,'placements':placements})
    # For other shapes, preserve bounded solver inputs and join the checked
    # strips without repeated top/bottom margins. Mixed jobs share each strip.
    if not candidates:
        seed = split_nest(bounded)
        placements = []; offset = 0
        for sheet in seed['sheets']:
            placements.extend({**p, 'y':p['y']-sheet['offset']+offset, 'sheet':0}
                              for p in seed['placements'] if p['sheet']==sheet['index'])
            offset += sheet['usedLength'] - 2*margin + gap
        length = offset + 2*margin-gap
        if length > limit:
            raise ValueError('This order exceeds the continuous PDF limit (196.85 in / 16.4 ft) or the available roll. Use shorter print sections or fewer copies.')
        candidates.append({'width':width,'usedLength':length,'placements':placements})
    best = min(candidates, key=lambda r:r['usedLength'])
    # Validation uses the whole order, including spacing across former seams.
    checked_job = {**job, 'settings':{**settings,'maxLength':limit}}
    # The row pitch includes a small coordinate guard. Settle onto the operator
    # gap when that is shorter. A failed settle keeps the guarded rows.
    tightened = compact_result(checked_job, best)
    if tightened['usedLength'] < best['usedLength'] - 1e-4:
        best = tightened
    shapes = validate_result(checked_job, best)
    area = sum(p.area for p in shapes)
    baseline = candidates[0]['usedLength']
    best.update(placements=[{**p,'sheet':0} for p in best['placements']], area=area,
                utilization=area/(width*best['usedLength']), elapsed=time.monotonic()-started,
                validated=True, engine='Continuous roll with checked row orientations and bounded search',
                sheets=[{'index':0,'offset':0,'usedLength':best['usedLength'],'pieces':count,'area':area}])
    if baseline > best['usedLength']+.01:
        best['layoutComparison'] = {'baselineLengthMm':baseline,'reference':'the initial row arrangement'}
    validate_result(job,best)
    publish_result(progress_path,best)
    return best


def split_nest(job, progress_path=None):
    started=time.monotonic()
    validate_job(job)
    settings=job['settings']
    limit=number(settings.get('sheetLength'),'Sheet length',10,5000)
    width=settings['width']; margin=settings['margin']; gap=settings['gap']
    if 2*margin>=limit: raise ValueError('Sheet margins leave no usable length.')
    usable_w=width-2*margin; usable_h=limit-2*margin
    # Bounding rectangles give a conservative, deterministic feasible seed. Each
    # sheet is then optimized with true contours; a worse/failed solve is discarded.
    bins=[]; copies=[]
    for part in job['parts']:
        poly=part_polygon(part)
        angles=settings['rotations']
        if angles is None:
            corners=list(poly.minimum_rotated_rectangle.exterior.coords)
            angles=list(range(0,360,15))+[90-math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])) for a,b in zip(corners,corners[1:])]
        variants=[]
        for angle in angles:
            x0,y0,x1,y1=rotate(poly,angle,origin=(0,0)).bounds
            # Tiny source-coordinate differences between repeated stickers
            # should not prevent them sharing a row. Round outward only.
            w=math.ceil((x1-x0+.22)*10)/10; h=math.ceil((y1-y0+.22)*10)/10
            if w<=usable_w and h<=usable_h: variants.append((w,h,x0,y0,angle))
        if not variants: raise ValueError(f"{part.get('name',part['id'])} cannot fit on one sheet. Increase the dimensions; pieces are never cut into sections.")
        for _ in range(part.get('quantity',1)): copies.append((part,variants))
    copies.sort(key=lambda item:max(v[0]*v[1] for v in item[1]),reverse=True)
    for part,variants in copies:
        choices=[]
        for bi,bin in enumerate(bins):
            if len(bin['placements']) >= PIECE_CAP:
                continue
            for ri,(x,y,w,h) in enumerate(bin['free']):
                for variant in variants:
                    vw,vh,*_=variant
                    if vw<=w+1e-8 and vh<=h+1e-8: choices.append((vw*vh,w*h-vw*vh,bi,ri,variant))
        if choices:
            _,_,bi,ri,variant=min(choices,key=lambda v:(v[0],v[1]))
        else:
            bins.append({'free':[(margin,margin,usable_w,usable_h)],'placements':[]})
            bi=len(bins)-1; ri=0; variant=min(variants,key=lambda v:(v[0]*v[1],v[1],v[0]))
        bin=bins[bi]; x,y,w,h=bin['free'].pop(ri); vw,vh,x0,y0,angle=variant
        bin['placements'].append({'id':part['id'],'x':x+.11-x0,'y':y+.11-y0,'rotation':angle})
        if w-vw-gap>.01: bin['free'].append((x+vw+gap,y,w-vw-gap,vh))
        if h-vh-gap>.01: bin['free'].append((x,y+vh+gap,w,h-vh-gap))
    all_placements=[]; sheets=[]; offset=0; total_area=0
    # Bounding boxes cannot interlock. Before committing several bins, let the
    # contour solver try the complete job on one sheet when its area permits it.
    area=sum(part_polygon(p).area*p.get('quantity',1) for p in job['parts'])
    if len(bins)>1 and len(copies) <= PIECE_CAP and area <= usable_w*usable_h:
        whole={**job,'settings':{**settings,'maxLength':min(limit,settings.get('maxLength') or limit)}}
        whole['settings'].pop('sheetLength',None)
        attempted=time.monotonic()
        try:
            candidate=solve(whole, progress_path)
            validate_result(whole,candidate)
            candidate['placements']=[{**p,'sheet':0} for p in candidate['placements']]
            candidate['sheets']=[{'index':0,'offset':0,'usedLength':candidate['usedLength'],'pieces':len(candidate['placements']),'area':candidate['area']}]
            validate_result(job,candidate)
            candidate['elapsed']=time.monotonic()-started
            return candidate
        except ValueError:
            pass
        # If the contour search used its budget, retain the already valid bins.
        # Do not run another full search budget for each fallback sheet.
        remaining=max(0,settings['seconds']-(time.monotonic()-attempted))
    else:
        remaining=settings['seconds']
    for index,bin in enumerate(bins):
        local_job=subset(job,bin['placements'])
        local_job['settings']={**settings,'maxLength':limit,'seconds':max(1,int(remaining/len(bins)))}
        local_job['settings'].pop('sheetLength',None)
        result={'width':width,'placements':bin['placements']}
        shapes=validate_result(local_job,result)
        result['usedLength']=max(s.bounds[3] for s in shapes)+margin
        try:
            if remaining>=1:
                optimized=solve(local_job, progress_path if len(bins)==1 else None)
                if optimized['usedLength']<result['usedLength']: result=optimized
        except ValueError:
            pass
        shapes=validate_result(local_job,result)
        area=sum(s.area for s in shapes); total_area+=area
        sheets.append({'index':index,'offset':offset,'usedLength':result['usedLength'],'pieces':len(result['placements']),'area':area})
        all_placements.extend({**p,'sheet':index,'y':p['y']+offset} for p in result['placements'])
        offset+=result['usedLength']
    if settings.get('maxLength') is not None and offset>settings['maxLength']+.001:
        raise ValueError('The sheets exceed the available total roll length. Increase the roll limit or select fewer jobs.')
    result={'width':width,'usedLength':offset,'placements':all_placements,'sheets':sheets,'area':total_area,
            'utilization':total_area/(width*offset),'elapsed':time.monotonic()-started,'validated':True,'engine':'Sparrow with whole-piece sheet allocation'}
    validate_result(job,result)
    publish_result(progress_path, result)
    return result


def validate_sheets(job,result):
    validate_job(job)
    sheets=result['sheets']; placements=result['placements']
    if not isinstance(sheets,list) or not 1<=len(sheets)<=100: raise ValueError('Invalid sheet list.')
    if job['settings'].get('continuous') and len(sheets) != 1:
        raise ValueError('A continuous print must have exactly one page.')
    if Counter(p['id'] for p in placements)!=Counter({p['id']:p.get('quantity',1) for p in job['parts']}):
        raise ValueError('Engine returned the wrong number of parts across sheets.')
    offset=0; shapes={}
    from shapely.affinity import translate
    for index,sheet in enumerate(sheets):
        if sheet['index']!=index or abs(sheet['offset']-offset)>.001: raise ValueError('Invalid sheet numbering or offsets.')
        length=number(sheet['usedLength'],'Sheet used length',.01,5000)
        if length>(5000 if job['settings'].get('continuous') else job['settings'].get('sheetLength',5000))+.001: raise ValueError('A sheet exceeds the selected maximum length.')
        indices=[i for i,p in enumerate(placements) if p.get('sheet')==index]
        local=[{**placements[i],'y':placements[i]['y']-offset} for i in indices]
        if not local: raise ValueError('Empty sheets are not valid.')
        cap = ORDER_PIECE_CAP if job['settings'].get('continuous') and len(sheets)==1 else PIECE_CAP
        if len(local) > cap: raise ValueError('A print section exceeds the safe piece limit.')
        local_job=subset(job,local); local_job['settings']={**job['settings'],'maxLength':length}
        local_job['settings'].pop('sheetLength',None)
        local_result={'width':result['width'],'usedLength':length,'placements':local}
        for i,shape in zip(indices,validate_result(local_job,local_result)): shapes[i]=translate(shape,yoff=offset)
        offset+=length
    if any(type(p.get('sheet')) is not int or not 0<=p['sheet']<len(sheets) for p in placements): raise ValueError('A piece has an invalid sheet.')
    if abs(offset-result['usedLength'])>.001: raise ValueError('Total sheet length does not match the batch.')
    if job['settings'].get('maxLength') is not None and offset>job['settings']['maxLength']+.001: raise ValueError('Sheets exceed the total roll limit.')
    return [shapes[i] for i in range(len(placements))]
