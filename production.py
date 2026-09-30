"""Job identity, verified set manifests, and immutable local batch packages."""
import csv
import io
import json
import html
import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET
from engine import validate_result
from shop_profiles import validate_profile, inspect_output
from costing import material_cost


def validate_identity(job):
    jobs = job.get('productionJobs', [])
    if not jobs:
        raise ValueError('This layout has no production job identities. Load files in the production queue.')
    by_id = {}
    codes = set()
    expected = set()
    for source in jobs:
        for field in ('customer','order','kit'):
            value=source.get(field,'')
            if not isinstance(value,str) or len(value)>120 or any(ord(c)<32 for c in value):
                raise ValueError('Invalid '+field+' identifier.')
        ident, code = source['id'], source['code']
        if ident in by_id or code in codes:
            raise ValueError('Duplicate production job identity.')
        if type(source['sets']) is not int or not 1 <= source['sets'] <= 100:
            raise ValueError('Sets must be an integer from 1 to 100.')
        if source.get('materialId') != job.get('materialId'):
            raise ValueError('Only jobs assigned to the same material preset can be combined.')
        if not source.get('partIds') or len(source['partIds']) != len(set(source['partIds'])):
            raise ValueError('A production job has missing or repeated part identities.')
        for part_id in source['partIds']:
            if part_id in expected:
                raise ValueError('A part belongs to more than one job.')
            expected.add(part_id)
        by_id[ident] = source
        codes.add(code)
    if Counter(p['id'] for p in job['parts']) != Counter({p: 1 for p in expected}):
        raise ValueError('The job is missing a source part or contains an unexpected part.')
    for part in job['parts']:
        source = by_id.get(part.get('sourceJobId'))
        base = part.get('perSet', 1)
        if not source or part['id'] not in source['partIds'] or type(base) is not int or not 1 <= base <= 100:
            raise ValueError('A part has an invalid source job or per-set quantity.')
        if part['quantity'] != base * source['sets']:
            raise ValueError('Part quantities do not make complete requested sets.')
    return by_id


def manifest(job, result, run_id):
    sources = validate_identity(job)
    shapes = validate_result(job, result)
    parts = {p['id']: p for p in job['parts']}
    seen = defaultdict(int)
    instances = []
    for index, (placement, shape) in enumerate(zip(result['placements'], shapes)):
        part = parts[placement['id']]
        source = sources[part['sourceJobId']]
        ordinal = seen[part['id']]
        seen[part['id']] += 1
        set_number, copy_number = divmod(ordinal, part.get('perSet', 1))
        part_number = source['partIds'].index(part['id']) + 1
        label = f"{source['code']}{set_number + 1}.{part_number:02}"
        if part.get('perSet', 1) > 1:
            label += f'.{copy_number + 1}'
        center = shape.representative_point()
        instances.append({'label': label, 'jobId': source['id'], 'jobCode': source['code'], 'jobName': source['name'],
                          'customer':source.get('customer',''),'order':source.get('order',''),'kit':source.get('kit',''),
                          'sheet':placement.get('sheet',0)+1,
                          'sheetX':placement['x'],'sheetY':placement['y']-(result.get('sheets') or [{'offset':0}])[placement.get('sheet',0)]['offset'],
                          'sourceFile': source.get('sourceFile', source['name']), 'sourceRevision': source['revision'],
                          'partId': part['id'], 'partName': part.get('name', part['id']), 'set': set_number + 1,
                          'copy': copy_number + 1, 'placementIndex': index, 'x': placement['x'], 'y': placement['y'],
                          'rotation': placement['rotation'], 'labelX': center.x, 'labelY': center.y})
    summaries = []
    for source in sources.values():
        per_set = sum(parts[p].get('perSet', 1) for p in source['partIds'])
        summaries.append({**source, 'piecesPerSet': per_set, 'expected': per_set * source['sets'],
                          'placed': sum(i['jobId'] == source['id'] for i in instances), 'complete': True})
    profile = validate_profile(job['outputProfile']) if 'outputProfile' in job else None
    requirements = {'outputProfile':profile,'outputCheck':inspect_output(profile)} if profile else {}
    return {'batchId': run_id, 'createdAt': datetime.now(timezone.utc).isoformat(), 'material': job.get('materialName'),
            'settings': job['settings'], 'width': result['width'], 'usedLength': result['usedLength'],
            'jobs': summaries, 'pieces': instances, 'totalPieces': len(instances), 'complete': True,
            'stickerFill': result.get('fillSummary', []), 'fillLimited': result.get('fillLimited', False),
            'sheets':result.get('sheets',[{'index':0,'offset':0,'usedLength':result['usedLength'],'pieces':len(instances)}]),
            'materialCost':material_cost(job,result,shapes), **requirements}


def validate_svg_payload(text):
    # The browser preserves artwork through its stricter SVG allowlist. Check the
    # release boundary too: packages must never contain executable SVG content.
    if not isinstance(text, str) or len(text) > 30_000_000 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Invalid or oversized SVG export.')
    root = ET.fromstring(text)
    ns = '{http://www.w3.org/2000/svg}'
    if root.tag != ns + 'svg':
        raise ValueError('Export must be an SVG document.')
    forbidden = {'script', 'foreignObject', 'animate', 'animateTransform', 'set', 'style', 'a'}
    for node in root.iter():
        if not node.tag.startswith(ns) or node.tag.split('}')[-1] in forbidden:
            raise ValueError('Unsupported active SVG export content.')
        for key, value in node.attrib.items():
            local = key.split('}')[-1]
            if local.lower().startswith('on') or local == 'style':
                raise ValueError('Unsupported SVG event or style content.')
            if local == 'href' and not (value.startswith('#') or value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,'))):
                raise ValueError('External SVG references cannot be released.')
    return root


def make_package(job, result, run_id, artwork, sheet_map, pdf_documents=None, output_check=None):
    data = manifest(job, result, run_id)
    root = validate_svg_payload(artwork) if pdf_documents is None else None
    validate_svg_payload(sheet_map)
    if output_check is not None: data['outputCheck']=output_check
    try:
        dimensions = [float(v) for v in root.attrib['viewBox'].split()] if root is not None else [0,0,result['width'],result['usedLength']]
    except (KeyError, ValueError):
        raise ValueError('Export is missing physical layout dimensions.')
    if dimensions != [0.0, 0.0, result['width'], result['usedLength']]:
        raise ValueError('Artwork size does not match the validated layout.')
    groups = root.findall('{http://www.w3.org/2000/svg}g') if root is not None else []
    if root is not None and (len(groups) != len(result['placements']) or [g.get('id') for g in groups] != ['ez-part-'+str(i+1) for i in range(len(groups))]):
        raise ValueError('Exported artwork does not contain every placed piece.')
    data['releasedAt'] = datetime.now(timezone.utc).isoformat()
    listing = io.StringIO(newline='')
    columns = ['label','customer','order','kit','sheet','sheetX','sheetY', 'jobName', 'sourceFile', 'sourceRevision', 'set', 'partName', 'copy', 'x', 'y', 'rotation']
    writer = csv.DictWriter(listing, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for item in data['pieces']:
        # Avoid spreadsheet formula interpretation of user-provided file names.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for k, v in item.items()})
    rows = ''.join('<tr><td>☐</td><td>'+html.escape(p['label'])+'</td><td>'+html.escape(' / '.join(filter(None,[p['customer'],p['order'],p['kit'],p['jobName']])))+'</td><td>'+str(p['sheet'])+'</td><td>'+str(p['set'])+'</td><td>'+html.escape(p['partName'])+'</td></tr>' for p in sorted(data['pieces'], key=lambda p:(p['customer'],p['order'],p['jobCode'],p['set'],p['label'])))
    readiness = data.get('outputCheck',{})
    notice = '<p><strong>Working files only.</strong> These files do not meet the selected shop requirements.</p>' if readiness.get('ready') is False else ''
    guide = '<!doctype html><html lang="en"><meta charset="utf-8"><title>EZ Nest sorting guide</title><style>body{font:15px Arial;margin:32px;color:#182a25}svg{width:100%;max-height:850px}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}h2{break-before:page}@media print{body{margin:12mm}}</style><h1>Batch '+html.escape(run_id[:8])+'</h1>'+notice+'<p>'+str(len(data['jobs']))+' jobs · '+str(data['totalPieces'])+' pieces. Match each map label to the checklist. Labels are on this guide only, not on the print artwork.</p>'+sheet_map+'<h2>Piece checklist</h2><table><tr><th>Collected</th><th>Map ID</th><th>Job</th><th>Set</th><th>Piece</th></tr>'+rows+'</table></html>'
    instructions = ('WORKING SVG PACKAGE - NOT READY FOR '+data['outputProfile']['rip']+'\n'+'\n'.join('- '+issue for issue in readiness['issues'])+'\n' if readiness.get('ready') is False else 'Artwork is in artwork.svg. Confirm compatibility with your print software before production.\n')
    if data.get('outputProfile'):
        p=data['outputProfile']
        instructions += 'Shop profile: '+p['name']+'\nRequired format: '+p['format'].upper()+'; color: '+p['colorMode']+'\nCut spot: '+(p['cutSpot'] or 'None')+'; cut layer: '+(p['cutLayer'] or 'None')+'\nRegistration owner: '+p['registrationOwner']+'; finishing: '+(p['finishingSoftware'] or 'Unspecified')+'\nMedia presets: '+p['mediaOwner']+'; printed job log: '+p['jobLogOwner']+'\n'
    guide=guide.removesuffix('</html>').replace('<th>Job</th><th>Set</th>','<th>Customer / order / kit / job</th><th>Sheet</th><th>Set</th>')
    cost=data.get('materialCost')
    if cost:
        guide+='<h2>Material estimate</h2><p>'+html.escape(cost['currency'])+' '+format(cost['total'],'.2f')+' total. '+html.escape(cost['allocation'])+' Excludes ink, laminate, labor, overhead and profit.</p>'
        for item in cost['jobs']:
            source=next(s for s in data['jobs'] if s['id']==item['jobId'])
            guide+='<p>'+html.escape(' / '.join(filter(None,[source.get('customer'),source.get('order'),source['name']])))+': '+html.escape(cost['currency'])+' '+format(item['cost'],'.2f')+'</p>'
    guide+='</html>'
    print_files={}
    if pdf_documents is not None:
        from pdf_io import export_pdf
        profile=job.get('outputProfile',{})
        for sheet in data['sheets']:
            name='artwork.pdf' if len(data['sheets'])==1 else f"sheet-{sheet['index']+1:03}.pdf"
            print_files[name]=export_pdf(job,result,pdf_documents,profile.get('cutSpot') or 'CutContour',profile.get('cutLayer') or 'CutContour',sheet['index'])
        instructions='PDF artwork preserves source drawing objects and named cut contours. Color conversion and registration marks belong in your RIP.\nBleed coverage was reviewed by the operator, not automatically certified. Verify this beta in your RIP before production.\n'
        if readiness.get('ready') is False: instructions='WORKING PDF PACKAGE - REQUIREMENTS NOT MET\n'+'\n'.join(readiness['issues'])+'\n'+instructions
    elif len(data['sheets'])==1:
        print_files['artwork.svg']=artwork
    else:
        ns='{http://www.w3.org/2000/svg}'
        for sheet in data['sheets']:
            page=ET.Element(root.tag,dict(root.attrib)); page.set('height',str(sheet['usedLength'])+'mm'); page.set('viewBox',f"0 0 {result['width']} {sheet['usedLength']}")
            for child in root:
                if child.tag!=ns+'g': page.append(copy.deepcopy(child))
            for i,placement in enumerate(result['placements']):
                if placement.get('sheet',0)!=sheet['index']: continue
                holder=ET.SubElement(page,ns+'g',{'transform':f"translate(0 {-sheet['offset']})"}); holder.append(copy.deepcopy(groups[i]))
            print_files[f"sheet-{sheet['index']+1:03}.svg"]=ET.tostring(page,encoding='unicode')
        instructions='Each numbered sheet SVG is a separate print file. Do not print the sorting map.\n'+instructions.replace('Artwork is in artwork.svg.','Artwork is in the numbered sheet files.')
    data['printFiles']=list(print_files)
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for name,content in print_files.items(): archive.writestr(name,content)
        archive.writestr('sheet-map.svg', sheet_map)
        archive.writestr('sorting-guide.html', guide)
        archive.writestr('piece-checklist.csv', listing.getvalue().encode('utf-8-sig'))
        archive.writestr('batch.json', json.dumps(data, indent=2))
        archive.writestr('READ ME.txt', instructions+'Sheet-map.svg and sorting-guide.html are separate assembly aids. Do not print the map as the artwork.\nThe manifest verifies counts against imported source pieces, not the completeness of the original design file.\nConfirm bleed, physical size, and RIP cut-color mapping before production. Downloaded/exported does not mean printed.\nThis is a frozen snapshot. Later nesting searches do not update these files.\n')
    return buffer.getvalue(), data
