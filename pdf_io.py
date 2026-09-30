"""PDF-native artwork isolation. Preview pixels are never used for PDF export.

Supported cut geometry is closed, stroked Separation paths (including curves and
transformed Form XObjects). Unsupported/ambiguous content fails closed.
"""
import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, ContentStream, DecodedStreamObject,
                           DictionaryObject, NameObject, NumberObject,
                           TextStringObject)
from shapely.geometry import Polygon, box

MM = 25.4 / 72
IDENTITY = (1, 0, 0, 1, 0, 0)


def matrix(a, b):
    """a after b; PDF matrices map column vectors."""
    A, B, C, D, E, F = a
    g, h, i, j, k, l = b
    return (A*g+C*h, B*g+D*h, A*i+C*j, B*i+D*j, A*k+C*l+E, B*k+D*l+F)


def point(m, p):
    a, b, c, d, e, f = m
    x, y = map(float, p)
    return [a*x+c*y+e, b*x+d*y+f]


def curve_points(p0, p1, p2, p3, depth=0):
    from shapely.geometry import LineString, Point
    chord = LineString([p0, p3])
    if depth >= 14 or max(chord.distance(Point(p1)), chord.distance(Point(p2))) <= .02/MM:
        return [p3]
    mid = lambda a, b: [(a[0]+b[0])/2, (a[1]+b[1])/2]
    a, b, c = mid(p0, p1), mid(p1, p2), mid(p2, p3)
    d, e = mid(a, b), mid(b, c)
    f = mid(d, e)
    return curve_points(p0, a, d, f, depth+1) + curve_points(f, e, c, p3, depth+1)


def path_text(commands):
    return '\n'.join(' '.join(format(float(v), '.9f').rstrip('0').rstrip('.') or '0' for v in values)
                     + (' ' if values else '') + op for op, values in commands)


def spot_name(resources, name):
    spaces = resources['/ColorSpace'] if '/ColorSpace' in resources else {}
    value = spaces.get(name)
    if value is not None:
        value = value.get_object()
        if isinstance(value, ArrayObject) and str(value[0]) == '/Separation':
            return str(value[1]).removeprefix('/')
    return None


def extract_page(page, writer, cut_spot, page_index):
    """Remove only recognized cut strokes and collect their exact path geometry."""
    pieces = []
    budget = [0]

    def visit(stream, resources, initial=IDENTITY, depth=0, inherited=None, clips=None):
        if depth > 16:
            raise ValueError('PDF forms are nested too deeply.')
        content = ContentStream(stream, writer)
        resources = DictionaryObject(resources.get_object())
        xobjects = DictionaryObject(resources['/XObject'] if '/XObject' in resources else {})
        resources[NameObject('/XObject')] = xobjects
        state = copy.deepcopy(inherited or {'stroke':None, 'fill':None})
        state.update(matrix=initial, clips=list(clips or []))
        stack, paths, commands, points = [], [], [], []
        output = []
        pending_clip = None

        def check_visibility(value):
            if value is None: return
            value=value.get_object()
            if isinstance(value, DictionaryObject) and (value.get('/Type')=='/OCMD' or value.get('/Usage')):
                raise ValueError('Conditional PDF layer visibility is not supported. Export a print-only PDF with all layers visible.')

        for value in resources.get('/Properties',DictionaryObject()).get_object().values():
            check_visibility(value)

        def finish_path(close=False):
            nonlocal commands, points
            if points:
                closed = close or (len(points)>2 and math.dist(points[0], points[-1]) < 1e-5)
                if close and (not commands or commands[-1][0] != 'h'):
                    commands.append(('h', []))
                paths.append((commands, points, closed))
            commands, points = [], []

        for operands, op in content.operations:
            budget[0] += 1
            if budget[0] > 300_000:
                raise ValueError('PDF page is too complex. Export a smaller print-only file.')
            if op == b'q':
                stack.append(copy.deepcopy(state))
            elif op == b'Q':
                if not stack:
                    raise ValueError('PDF graphics state is unbalanced.')
                state = stack.pop()
            elif op == b'cm':
                state['matrix'] = matrix(state['matrix'], tuple(map(float, operands)))
            elif op in (b'CS', b'cs'):
                state['stroke' if op == b'CS' else 'fill'] = spot_name(resources, operands[0])
            elif op in (b'G', b'RG', b'K'):
                state['stroke'] = None
            elif op in (b'g', b'rg', b'k'):
                state['fill'] = None
            elif op == b'BDC' and operands[0] == '/OC':
                check_visibility(operands[1])
            elif op == b'm':
                finish_path()
                p = point(state['matrix'], operands)
                points = [p]; commands = [('m', p)]
            elif op == b'l':
                p = point(state['matrix'], operands)
                points.append(p); commands.append(('l', p))
            elif op in (b'c', b'v', b'y'):
                if not points:
                    raise ValueError('PDF curve has no starting point.')
                coords = [point(state['matrix'], operands[i:i+2]) for i in range(0, len(operands), 2)]
                if op == b'v': coords.insert(0, points[-1])
                if op == b'y': coords.append(coords[-1])
                points.extend(curve_points(points[-1], *coords))
                commands.append(('c', [v for p in coords for v in p]))
            elif op == b're':
                finish_path()
                x, y, w, h = map(float, operands)
                points = [point(state['matrix'], p) for p in [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]]
                commands = [('m', points[0])] + [('l', p) for p in points[1:]]
                finish_path(True)
            elif op == b'h':
                finish_path(True)
            elif op in (b'W', b'W*'):
                pending_clip = op
            elif op in (b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'n'):
                finish_path(op in (b's', b'b', b'b*'))
                strokes = op in (b'S', b's', b'B', b'B*', b'b', b'b*')
                fills = op in (b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*')
                if fills and state['fill'] == cut_spot:
                    raise ValueError('Cut paths must be strokes, not filled spot-color shapes.')
                if strokes and state['stroke'] == cut_spot:
                    if len(paths) != 1:
                        raise ValueError('Compound cut paths need separate closed contours before import.')
                    cmd, pts, closed = paths[0]
                    poly = Polygon(pts)
                    if not closed or not poly.is_valid or poly.area*MM*MM < .01:
                        raise ValueError('A cut path is open, self-intersecting, or too small.')
                    if len(pts) > 5000:
                        raise ValueError('A cut contour is too complex (over 5000 sampled points).')
                    if any(not c.buffer(.001).covers(poly) for c in state['clips']):
                        raise ValueError('A cut contour is clipped. Flatten its clipping structure first.')
                    pieces.append({'page':page_index, 'commands':cmd, 'pdfPoints':pts})
                    if len(pieces) > 100:
                        raise ValueError('Use no more than 100 cut contours per file.')
                    # Keep any ordinary fill, but remove the original cut stroke.
                    if op in (b'b', b'b*'): output.append(([], b'h'))
                    op = (b'f*' if op.endswith(b'*') else b'f') if fills else b'n'
                if pending_clip:
                    if len(paths) != 1 or not paths[0][2]:
                        # Complex artwork clips are valid, but cuts inside one cannot
                        # be certified by this importer. Represent an empty clip.
                        state['clips'].append(Polygon())
                    else:
                        state['clips'].append(Polygon(paths[0][1]))
                    pending_clip = None
                paths = []
            elif op == b'Do':
                obj = xobjects.get(operands[0])
                if obj is not None: check_visibility(obj.get_object().get('/OC'))
                if obj is not None and obj.get_object().get('/Subtype') == '/Form':
                    form = obj.get_object()
                    transform = matrix(state['matrix'], tuple(map(float, form.get('/Matrix', IDENTITY))))
                    form_clips = list(state['clips'])
                    if '/BBox' in form:
                        x0,y0,x1,y1 = map(float, form['/BBox'])
                        form_clips.append(Polygon([point(transform,p) for p in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]]))
                    body, nested_resources = visit(form, form['/Resources'] if '/Resources' in form else resources, transform, depth+1, state, form_clips)
                    clone = DecodedStreamObject()
                    for k, v in form.items():
                        if k not in ('/Length', '/Filter', '/DecodeParms', '/Resources'):
                            clone[k] = v
                    clone.set_data(body)
                    clone[NameObject('/Resources')] = nested_resources
                    key = NameObject('/EZNForm'+str(budget[0]))
                    xobjects[key] = writer._add_object(clone)
                    operands = [key]
            output.append((operands, op))
        if stack:
            raise ValueError('PDF graphics state is unbalanced.')
        content.operations = output
        return content.get_data(), resources

    body, resources = visit(page.get_contents(), page['/Resources'])
    stream = DecodedStreamObject(); stream.set_data(body)
    page[NameObject('/Contents')] = writer._add_object(stream)
    page[NameObject('/Resources')] = resources
    return pieces


def read_document(raw, bleed_mm=0, cut_spot='CutContour'):
    if not raw[:1024].lstrip().startswith(b'%PDF-'):
        raise ValueError('Use PDF, or save the AI file with Create PDF Compatible File enabled.')
    if not isinstance(cut_spot,str) or not cut_spot or len(cut_spot)>80 or any(ord(c)<32 for c in cut_spot):
        raise ValueError('Enter a valid cut spot-color name.')
    if type(bleed_mm) not in (int,float) or not math.isfinite(bleed_mm) or not 0<=bleed_mm<=25:
        raise ValueError('Existing artwork bleed must be between 0 and 25 mm.')
    reader = PdfReader(io.BytesIO(raw), strict=False)
    if reader.is_encrypted:
        raise ValueError('Export an unencrypted PDF for nesting.')
    if not 1 <= len(reader.pages) <= 25:
        raise ValueError('Import between 1 and 25 PDF pages at a time.')
    if '/OCProperties' in reader.root_object:
        properties=reader.root_object['/OCProperties']; default=properties.get('/D',DictionaryObject()).get_object()
        if str(default.get('/BaseState','/ON'))!='/ON' or default.get('/OFF') or default.get('/AS'):
            raise ValueError('Export a print-only PDF with all layers visible. Hidden or conditional layer visibility is not supported.')
        for group in properties.get('/OCGs',[]):
            if group.get_object().get('/Usage'):
                raise ValueError('Export without conditional PDF layer print/view rules.')
    writer = PdfWriter()
    if '/OCProperties' in reader.root_object:
        writer.root_object[NameObject('/OCProperties')]=reader.root_object['/OCProperties'].clone(writer)
    pieces = []
    for i, original in enumerate(reader.pages):
        if original.get('/Annots'):
            raise ValueError('Flatten annotations/forms in a print-only PDF before nesting.')
        if float(original.get('/UserUnit',1)) != 1:
            raise ValueError('PDF UserUnit scaling is not supported. Export at actual size with standard PDF units.')
        page = writer.add_page(original)
        if page.rotation: page.transfer_rotation_to_content()
        page_pieces = extract_page(page, writer, cut_spot, i)
        crop = box(*map(float,page.cropbox))
        occupied = []
        for piece_number,piece in enumerate(page_pieces,1):
            poly = Polygon(piece['pdfPoints'])
            envelope = poly.buffer(bleed_mm/MM, join_style=2) if bleed_mm else poly
            if not crop.buffer(.001).covers(envelope):
                raise ValueError('A cut contour plus the entered bleed extends outside its PDF page. Correct the source or bleed setting.')
            if any(envelope.intersection(other).area > .001 for other in occupied):
                raise ValueError('Cut contours or their bleed areas overlap/nest inside each other. Separate printable pieces in the source.')
            occupied.append(envelope)
            x0,y0,x1,y1 = envelope.bounds
            piece.update(id='pdf-'+str(len(pieces)+1), name=f'Page {i+1} · piece {piece_number}',
                         anchor=[x0,y1], bounds=[x0,y0,x1,y1],
                         points=[[(x-x0)*MM,(y1-y)*MM] for x,y in envelope.exterior.coords[:-1]],
                         clipCommands=[('m',list(envelope.exterior.coords[0]))]+[('l',list(p)) for p in envelope.exterior.coords[1:]]+[('h',[])])
            pieces.append(piece)
            if not bleed_mm: piece['clipCommands']=piece['commands']
        if not page_pieces:
            raise ValueError(f'Page {i+1}: no closed {cut_spot} spot-color strokes found. Add actual cut contours in the design file; ordinary colored lines are not cut spots.')
    if len(pieces)>100:
        raise ValueError('Use no more than 100 cut contours per file.')
    if '/OutputIntents' in reader.root_object:
        writer.root_object[NameObject('/OutputIntents')] = reader.root_object['/OutputIntents'].clone(writer)
    buf=io.BytesIO(); writer.write(buf)
    return buf.getvalue(), {'pieces':pieces,'bleedMm':bleed_mm,'cutSpot':cut_spot,
                           'warnings':['Bleed coverage is not automatically verified. Review each detected piece and confirm the source includes the entered bleed.'],
                           'pages':len(reader.pages)}


def form_from_page(page, writer):
    form = DecodedStreamObject(); form.set_data(page.get_contents().get_data())
    form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                 NameObject('/BBox'):page.cropbox.clone(writer),NameObject('/Resources'):page['/Resources'].clone(writer)})
    if '/Group' in page: form[NameObject('/Group')]=page['/Group'].clone(writer)
    return writer._add_object(form)


def export_pdf(job, result, documents, cut_spot='CutContour', cut_layer='CutContour', sheet_filter=None):
    """Copy original PDF drawing streams, clipping each piece including its bleed."""
    writer=PdfWriter(); writer.pdf_header='%PDF-1.7'
    forms={}; readers={}; output_intents=[]; source_layers=[]
    for ident, (raw, meta) in documents.items():
        reader=PdfReader(io.BytesIO(raw)); readers[ident]=reader
        if reader.pdf_header > writer.pdf_header: writer.pdf_header=reader.pdf_header
        if '/OCProperties' in reader.root_object:
            source_layers.extend(g.clone(writer) for g in reader.root_object['/OCProperties'].get('/OCGs',[]))
        if '/OutputIntents' in reader.root_object:
            intents=reader.root_object['/OutputIntents']
            # Preserve the first intent; refuse incompatible document profiles.
            profiles=[hashlib.sha256(o.get_object()['/DestOutputProfile'].get_data()).hexdigest() for o in intents if '/DestOutputProfile' in o.get_object()]
            if output_intents and output_intents[0]!=profiles:
                raise ValueError('Source PDFs have different output profiles. Export compatible source PDFs before mixing these jobs.')
            if not output_intents:
                output_intents.append(profiles)
                writer.root_object[NameObject('/OutputIntents')]=intents.clone(writer)
        for page_index, page in enumerate(reader.pages):
            forms[(ident,page_index)]=form_from_page(page,writer)
    group=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject(cut_layer or cut_spot)}))
    layers=ArrayObject(source_layers+[group])
    writer.root_object[NameObject('/OCProperties')]=DictionaryObject({NameObject('/OCGs'):layers,NameObject('/D'):DictionaryObject({NameObject('/Order'):layers,NameObject('/ON'):layers})})
    tint=DictionaryObject({NameObject('/FunctionType'):NumberObject(2),NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)]),NameObject('/C0'):ArrayObject([NumberObject(0)]*4),NameObject('/C1'):ArrayObject([NumberObject(0),NumberObject(1),NumberObject(0),NumberObject(0)]),NameObject('/N'):NumberObject(1)})
    space=ArrayObject([NameObject('/Separation'),NameObject('/'+cut_spot),NameObject('/DeviceCMYK'),writer._add_object(tint)])
    parts={p['id']:p for p in job['parts']}
    sheets=result.get('sheets') or [{'index':0,'offset':0,'usedLength':result['usedLength']}]
    for sheet in sheets:
        if sheet_filter is not None and sheet['index']!=sheet_filter: continue
        if not 0 < sheet['usedLength'] <= 5000 or not 0 < result['width'] <= 5000:
            raise ValueError('PDF sheets are limited to 5000 mm per side. Set a maximum sheet length in Settings for a longer batch.')
        page=writer.add_blank_page(width=result['width']/MM,height=sheet['usedLength']/MM)
        resources=DictionaryObject({NameObject('/XObject'):DictionaryObject(),NameObject('/ColorSpace'):DictionaryObject({NameObject('/EZCut'):space}),NameObject('/Properties'):DictionaryObject({NameObject('/EZCutLayer'):group}),NameObject('/ExtGState'):DictionaryObject({NameObject('/EZOverprint'):DictionaryObject({NameObject('/Type'):NameObject('/ExtGState'),NameObject('/OP'):__import__('pypdf').generic.BooleanObject(True)})})})
        page[NameObject('/Resources')]=resources
        chunks=[]
        for placement in result['placements']:
            if placement.get('sheet',0)!=sheet['index']: continue
            part=parts[placement['id']]
            ident=part['documentId']; meta=documents[ident][1]
            piece=next(p for p in meta['pieces'] if p['id']==part['pdfPieceId'])
            x0,y1=piece['anchor']; theta=math.radians(placement['rotation']); c,s=math.cos(theta),math.sin(theta)
            # PDF y-up -> internal mm y-down -> rotated placement -> PDF y-up.
            a,b,cc,d=c,-s,s,c
            tx=placement['x']/MM-c*x0-s*y1
            ty=(sheet['usedLength']-(placement['y']-sheet['offset']))/MM+s*x0-c*y1
            key=NameObject('/Art'+str(len(resources['/XObject'])+1))
            resources['/XObject'][key]=forms[(ident,piece['page'])]
            chunks.append('q\n'+' '.join(f'{v:.9f}' for v in (a,b,cc,d,tx,ty))+' cm\nq\n'+path_text(piece['clipCommands'])+'\nW n\n'+str(key)+' Do\nQ\n/OC /EZCutLayer BDC\n/EZOverprint gs\n/EZCut CS 1 SCN\n0.25 w\n'+path_text(piece['commands'])+'\nS\nEMC\nQ')
        stream=DecodedStreamObject(); stream.set_data('\n'.join(chunks).encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_metadata({'/Creator':'eznest','/Title':'Nested artwork — review in RIP before production'})
    out=io.BytesIO(); writer.write(out); return out.getvalue()


def import_to_store(raw, folder, bleed_mm=0, cut_spot='CutContour'):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    ident=hashlib.sha256(raw+json.dumps([bleed_mm,cut_spot]).encode()).hexdigest()
    clean,meta=read_document(raw,bleed_mm,cut_spot)
    meta.update(id=ident,sourceHash=hashlib.sha256(raw).hexdigest())
    # Preview in a separate process through the import worker. PDFium is not thread-safe.
    import pypdfium2 as pdfium
    preview_parts=[]
    for piece in meta['pieces']:
        w=(piece['bounds'][2]-piece['bounds'][0])*MM; h=(piece['bounds'][3]-piece['bounds'][1])*MM
        part={'id':piece['id'],'documentId':ident,'pdfPieceId':piece['id']}
        preview=export_pdf({'parts':[part]}, {'width':w,'usedLength':h,'placements':[{'id':piece['id'],'x':0,'y':0,'rotation':0}]}, {ident:(clean,meta)},cut_spot)
        with pdfium.PdfDocument(preview) as doc:
            page=doc[0]; bitmap=page.render(scale=min(2,600/max(page.get_size())),fill_color=(255,255,255,0))
            image=bitmap.to_pil(); buffer=io.BytesIO(); image.save(buffer,format='PNG'); bitmap.close(); page.close()
        preview_parts.append({'id':piece['id'],'name':piece['name'],'points':piece['points'],'quantity':1,
                              'documentId':ident,'pdfPieceId':piece['id'],'preview':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(), 'previewWidth':w,'previewHeight':h})
    (folder/(ident+'.pdf')).write_bytes(clean)
    (folder/(ident+'.json')).write_text(json.dumps(meta),encoding='utf-8')
    return {'format':'pdf','documentId':ident,'parts':preview_parts,'warnings':meta['warnings'],'bleedMm':bleed_mm,'reviewed':False}


def load_documents(job, folder, require_review=True):
    documents={}
    for source in job['productionJobs']:
        data=job.get('documentSources',{}).get(source['id'])
        if not data: raise ValueError('PDF export requires PDF/compatible AI jobs only. Export SVG jobs in a separate batch.')
        if require_review and data.get('reviewed') is not True:
            raise ValueError('Review the detected PDF pieces and confirm existing bleed in Job options before exporting.')
        ident=data.get('documentId','')
        if len(ident)!=64 or any(c not in '0123456789abcdef' for c in ident): raise ValueError('Invalid document identity.')
        try:
            raw=(Path(folder)/(ident+'.pdf')).read_bytes()
            meta=json.loads((Path(folder)/(ident+'.json')).read_text(encoding='utf-8'))
        except (OSError,ValueError):
            raise ValueError('A source PDF is unavailable. Re-add the original file.')
        documents[ident]=(raw,meta)
        actual={p['pdfPieceId']:p for p in job['parts'] if p.get('sourceJobId')==source['id']}
        if set(actual)!=set(p['id'] for p in meta['pieces']): raise ValueError('PDF source pieces no longer match this job. Re-import it.')
        for p in meta['pieces']:
            item=actual[p['id']]
            if item.get('documentId')!=ident or item['points']!=p['points']: raise ValueError('PDF geometry does not match the original import.')
    return documents


def output_check(job, folder):
    """Readiness for this exact batch, rather than promises made by a profile."""
    issues=[]
    try:
        documents=load_documents(job,folder)
    except ValueError as error:
        issues.append(str(error)); documents={}
    profile=job.get('outputProfile',{})
    if profile.get('format','pdf')!='pdf': issues.append('Choose a PDF output profile for PDF/AI artwork.')
    if profile.get('colorMode','preserve')!='preserve': issues.append('Choose Preserve source colors; color conversion belongs in your RIP.')
    if profile.get('iccProfile'): issues.append('A specific ICC output profile is not applied by eznest. Configure color management in your RIP.')
    if profile.get('registrationOwner')=='file': issues.append('Choose RIP or finishing software for registration marks; eznest does not add them.')
    required=profile.get('bleedMm')
    if required is None: issues.append('Confirm required bleed in the output profile (0 for none).')
    elif any(meta['bleedMm']+1e-6<required for raw,meta in documents.values()): issues.append('An imported file reserves less existing bleed than the output profile requires. Re-import with the correct bleed.')
    return {'ready':not issues,'actualFormat':'pdf','issues':issues,'bleedVerification':'operator-reviewed; no automatic ink-coverage verification','colorHandling':'source preserved; RIP manages conversion'}


def worker(request, output):
    request=Path(request); output=Path(output)
    try:
        data=json.loads(request.read_text(encoding='utf-8'))
        raw=base64.b64decode(data['content'],validate=True)
        if len(raw)>20_000_000: raise ValueError('PDF/AI files are limited to 20 MB in this build.')
        result={'ok':True,'document':import_to_store(raw,output.parent/'documents',data.get('bleedMm',0),data.get('cutSpot','CutContour'))}
    except Exception as error:
        result={'ok':False,'error':str(error)}
    output.write_text(json.dumps(result),encoding='utf-8')


if __name__=='__main__':
    import sys
    worker(*sys.argv[1:3])
