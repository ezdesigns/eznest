"""Whole-piece sheet allocation with a valid fallback for every optimized sheet."""
import copy
import math
from collections import Counter
from shapely.geometry import Polygon
from shapely.affinity import rotate
from engine import solve, validate_result, number


def subset(job, placements):
    counts=Counter(p['id'] for p in placements)
    return {**job,'parts':[{**p,'quantity':counts[p['id']]} for p in job['parts'] if counts[p['id']]]}


def split_nest(job):
    settings=job['settings']
    limit=number(settings.get('sheetLength'),'Sheet length',10,5000)
    width=settings['width']; margin=settings['margin']; gap=settings['gap']
    if 2*margin>=limit: raise ValueError('Sheet margins leave no usable length.')
    usable_w=width-2*margin; usable_h=limit-2*margin
    # Bounding rectangles give a conservative, deterministic feasible seed. Each
    # sheet is then optimized with true contours; a worse/failed solve is discarded.
    bins=[]; copies=[]
    for part in job['parts']:
        poly=Polygon(part['points'])
        angles=settings['rotations']
        if angles is None:
            corners=list(poly.minimum_rotated_rectangle.exterior.coords)
            angles=list(range(0,360,15))+[90-math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])) for a,b in zip(corners,corners[1:])]
        variants=[]
        for angle in angles:
            x0,y0,x1,y1=rotate(poly,angle,origin=(0,0)).bounds
            w=x1-x0+.22; h=y1-y0+.22
            if w<=usable_w and h<=usable_h: variants.append((w,h,x0,y0,angle))
        if not variants: raise ValueError(f"{part.get('name',part['id'])} cannot fit on one sheet. Increase the dimensions; pieces are never cut into sections.")
        for _ in range(part.get('quantity',1)): copies.append((part,variants))
    copies.sort(key=lambda item:max(v[0]*v[1] for v in item[1]),reverse=True)
    for part,variants in copies:
        choices=[]
        for bi,bin in enumerate(bins):
            for ri,(x,y,w,h) in enumerate(bin['free']):
                for variant in variants:
                    vw,vh,*_=variant
                    if vw<=w+1e-8 and vh<=h+1e-8: choices.append((w*h-vw*vh,bi,ri,variant))
        if choices:
            _,bi,ri,variant=min(choices,key=lambda v:v[0])
        else:
            bins.append({'free':[(margin,margin,usable_w,usable_h)],'placements':[]})
            bi=len(bins)-1; ri=0; variant=min(variants,key=lambda v:(v[1],v[0]))
        bin=bins[bi]; x,y,w,h=bin['free'].pop(ri); vw,vh,x0,y0,angle=variant
        bin['placements'].append({'id':part['id'],'x':x+.11-x0,'y':y+.11-y0,'rotation':angle})
        if w-vw-gap>.01: bin['free'].append((x+vw+gap,y,w-vw-gap,vh))
        if h-vh-gap>.01: bin['free'].append((x,y+vh+gap,w,h-vh-gap))
    all_placements=[]; sheets=[]; offset=0; total_area=0; elapsed=0
    for index,bin in enumerate(bins):
        local_job=subset(job,bin['placements'])
        local_job['settings']={**settings,'maxLength':limit,'seconds':max(1,int(settings['seconds']/len(bins)))}
        local_job['settings'].pop('sheetLength',None)
        result={'width':width,'placements':bin['placements']}
        shapes=validate_result(local_job,result)
        result['usedLength']=max(s.bounds[3] for s in shapes)+margin
        try:
            optimized=solve(local_job)
            if optimized['usedLength']<result['usedLength']: result=optimized
        except ValueError:
            pass
        shapes=validate_result(local_job,result)
        area=sum(s.area for s in shapes); total_area+=area; elapsed+=result.get('elapsed',0)
        sheets.append({'index':index,'offset':offset,'usedLength':result['usedLength'],'pieces':len(result['placements']),'area':area})
        all_placements.extend({**p,'sheet':index,'y':p['y']+offset} for p in result['placements'])
        offset+=result['usedLength']
    if settings.get('maxLength') is not None and offset>settings['maxLength']+.001:
        raise ValueError('The sheets exceed the available total roll length. Increase the roll limit or select fewer jobs.')
    result={'width':width,'usedLength':offset,'placements':all_placements,'sheets':sheets,'area':total_area,
            'utilization':total_area/(width*offset),'elapsed':elapsed,'validated':True,'engine':'Sparrow with whole-piece sheet allocation'}
    validate_result(job,result)
    return result


def validate_sheets(job,result):
    sheets=result['sheets']; placements=result['placements']
    if not isinstance(sheets,list) or not 1<=len(sheets)<=100: raise ValueError('Invalid sheet list.')
    if Counter(p['id'] for p in placements)!=Counter({p['id']:p.get('quantity',1) for p in job['parts']}):
        raise ValueError('Engine returned the wrong number of parts across sheets.')
    offset=0; shapes={}
    from shapely.affinity import translate
    for index,sheet in enumerate(sheets):
        if sheet['index']!=index or abs(sheet['offset']-offset)>.001: raise ValueError('Invalid sheet numbering or offsets.')
        length=number(sheet['usedLength'],'Sheet used length',.01,5000)
        if length>job['settings'].get('sheetLength',5000)+.001: raise ValueError('A sheet exceeds the selected maximum length.')
        indices=[i for i,p in enumerate(placements) if p.get('sheet')==index]
        local=[{**placements[i],'y':placements[i]['y']-offset} for i in indices]
        if not local: raise ValueError('Empty sheets are not valid.')
        local_job=subset(job,local); local_job['settings']={**job['settings'],'maxLength':length}
        local_result={'width':result['width'],'usedLength':length,'placements':local}
        for i,shape in zip(indices,validate_result(local_job,local_result)): shapes[i]=translate(shape,yoff=offset)
        offset+=length
    if any(type(p.get('sheet')) is not int or not 0<=p['sheet']<len(sheets) for p in placements): raise ValueError('A piece has an invalid sheet.')
    if abs(offset-result['usedLength'])>.001: raise ValueError('Total sheet length does not match the batch.')
    if job['settings'].get('maxLength') is not None and offset>job['settings']['maxLength']+.001: raise ValueError('Sheets exceed the total roll limit.')
    return [shapes[i] for i in range(len(placements))]
