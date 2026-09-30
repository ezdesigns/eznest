"""Material-only estimates with explicitly allocated shared waste."""
import math


def material_cost(job,result,shapes):
    price=job['settings'].get('costPerSquareMeter')
    if price is None: return None
    if type(price) not in (int,float) or not math.isfinite(price) or not 0<=price<=1_000_000:
        raise ValueError('Material cost must be a nonnegative amount per square meter.')
    currency=job['settings'].get('currency','USD')
    if not isinstance(currency,str) or len(currency)!=3 or not currency.isascii() or not currency.isalpha():
        raise ValueError('Use a three-letter currency code.')
    by_part={p['id']:p for p in job['parts']}; areas={}
    for placement,shape in zip(result['placements'],shapes):
        ident=by_part[placement['id']]['sourceJobId']; areas[ident]=areas.get(ident,0)+shape.area
    total_area=sum(areas.values()); material_area=result['width']*result['usedLength']/1_000_000
    total_cents=round(material_area*price*100)
    # Largest remainder avoids rounding several orders above/below the batch total.
    exact={k:total_cents*v/total_area for k,v in areas.items()}
    cents={k:math.floor(v) for k,v in exact.items()}
    for k in sorted(exact,key=lambda k:exact[k]-cents[k],reverse=True)[:total_cents-sum(cents.values())]: cents[k]+=1
    return {'currency':currency.upper(),'costPerSquareMeter':price,'materialAreaM2':material_area,
            'total':total_cents/100,'allocation':'Shared unused material allocated by occupied piece area, including reserved bleed.',
            'excludes':['ink','laminate','labor','overhead','profit'],
            'jobs':[{'jobId':k,'pieceAreaM2':areas[k]/1_000_000,'allocatedMaterialAreaM2':material_area*areas[k]/total_area,'cost':cents[k]/100} for k in areas]}
