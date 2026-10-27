"""PDF-native artwork isolation. Preview pixels are never used for PDF export.

Pieces own a closed boundary plus all contained mapped cut paths. Exact spots
and PDF layers classify separate operations. Ambiguous content fails closed.
"""
import base64
import copy
import hashlib
import io
import json
import math
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, ContentStream, DecodedStreamObject,
                           DictionaryObject, NameObject, NumberObject,
                           TextStringObject)
from shapely.geometry import Polygon, box, MultiPoint
from shapely.affinity import rotate, translate
from shapely.strtree import STRtree

MM = 25.4 / 72
IDENTITY = (1, 0, 0, 1, 0, 0)
from import_limits import MAX_PDF_BYTES, MAX_JSON_PDF_BYTES, MAX_PDF_BASE64_CHARS
MAX_PAGE_OPERATIONS = 2_000_000
MAX_CLIP_SEGMENTS = 20_000
MAX_CLIP_FACES = 2_000


def validate_layer_usage(group):
    """Illustrator CreatorInfo describes authorship, not layer visibility."""
    usage = group.get('/Usage')
    if usage is not None:
        usage = usage.get_object()
        if not isinstance(usage, DictionaryObject) or set(usage) - {'/CreatorInfo'}:
            raise ValueError('Export without conditional PDF layer print/view rules.')


def flattened_path(commands):
    """Flatten only geometry used for cutting or clipping, never ordinary ink."""
    points = []
    for op, values in commands:
        if op in ('m', 'l'):
            points.append(values)
        elif op == 'c':
            points.extend(curve_points(points[-1], values[:2], values[2:4], values[4:6]))
    return points


def clipping_region(paths, rule):
    """Interpret PDF fill rules for cut validation; never rewrite the mask.

    Polygonizing the noded edges yields faces on which winding is constant.
    Testing those faces handles holes, overlapping rings and self-crossings
    without treating every subpath as either a union or a hole. PDF closes
    open clipping subpaths implicitly (ISO 32000-1, 8.5.3.3 and 8.5.4).
    """
    import numpy as np
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    rings = []
    segment_count = 0
    for commands, _, _ in paths:
        points = flattened_path(commands)
        if any(not math.isfinite(v) for p in points for v in p):
            raise ValueError('Invalid clipping mask coordinates.')
        if len(points) < 3:
            continue
        if points[-1] != points[0]:
            points = points + [points[0]]
        segment_count += len(points) - 1
        if segment_count > MAX_CLIP_SEGMENTS:
            raise ValueError('Clipping mask is too complex to verify safely.')
        rings.append(points)
    if not rings:
        return Polygon()
    if len(rings) == 1:
        simple = Polygon(rings[0])
        if simple.is_valid:
            return simple
    faces = []
    for face in polygonize(unary_union([LineString(ring) for ring in rings])):
        faces.append(face)
        if len(faces) > MAX_CLIP_FACES:
            raise ValueError('Clipping mask is too complex to verify safely.')
    coordinates = np.asarray([(a, b) for ring in rings for a, b in zip(ring, ring[1:])])
    a, b = coordinates[:, 0], coordinates[:, 1]
    selected = []
    for face in faces:
        point = face.representative_point()
        x, y = point.x, point.y
        cross = (b[:, 0]-a[:, 0])*(y-a[:, 1]) - (x-a[:, 0])*(b[:, 1]-a[:, 1])
        winding = (int(np.count_nonzero((a[:, 1] <= y) & (b[:, 1] > y) & (cross > 0)))
                   - int(np.count_nonzero((b[:, 1] <= y) & (a[:, 1] > y) & (cross < 0))))
        if (winding % 2 != 0) if rule == b'W*' else winding != 0:
            selected.append(face)
    return unary_union(selected) if selected else Polygon()


def matrix(a, b):
    """a after b; PDF matrices map column vectors."""
    A, B, C, D, E, F = a
    g, h, i, j, k, l = b
    return (A*g+C*h, B*g+D*h, A*i+C*j, B*i+D*j, A*k+C*l+E, B*k+D*l+F)


def point(m, p):
    a, b, c, d, e, f = m
    x, y = map(float, p)
    return [a*x+c*y+e, b*x+d*y+f]


def curve_points(p0, p1, p2, p3, depth=0, tolerance=.02/MM):
    # Millions of subdivisions can occur in detailed prepared artwork. Scalar
    # distances avoid constructing a GEOS line and two points at each step.
    # Clamp to the segment: distance to its infinite line misses curves that
    # double back past either endpoint, including collinear control points.
    dx, dy = p3[0]-p0[0], p3[1]-p0[1]
    length = math.hypot(dx, dy)
    def distance(p):
        x, y = p[0]-p0[0], p[1]-p0[1]
        if not length:
            return math.hypot(x, y)
        ux, uy = dx/length, dy/length
        projection = max(0, min(length, x*ux+y*uy))
        return math.hypot(x-projection*ux, y-projection*uy)
    if depth >= 14 or max(distance(p1), distance(p2)) <= tolerance:
        return [p3]
    mid = lambda a, b: [(a[0]+b[0])/2, (a[1]+b[1])/2]
    a, b, c = mid(p0, p1), mid(p1, p2), mid(p2, p3)
    d, e = mid(a, b), mid(b, c)
    f = mid(d, e)
    return curve_points(p0, a, d, f, depth+1, tolerance) + curve_points(f, e, c, p3, depth+1, tolerance)


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


class GuideReviewRequired(ValueError):
    """An import cannot continue until the operator reviews these exact lines."""
    def __init__(self, review):
        super().__init__('Review possible guides before adding this file.')
        self.review = review


class CutReviewRequired(ValueError):
    def __init__(self, review):
        super().__init__('These outlines are not named cut paths. Review them before nesting.')
        self.review = review


def unnamed_cut_review(raw, mapping, candidates, previews=True):
    source_hash = hashlib.sha256(raw).hexdigest()
    identity = [source_hash, mapping, [p['id'] for p in candidates]]
    review = {'id':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
              'sourceHash':source_hash, 'count':len(candidates), 'pages':[]}
    if not previews:
        return review
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(raw) as doc:
        for index in sorted({p['page'] for p in candidates}):
            page = doc[index]
            try:
                if page.get_rotation():
                    raise ValueError('Name the cut paths in this rotated PDF before importing it.')
                left,bottom,right,top = page.get_bbox()
                bitmap = page.render(scale=min(2,900/max(page.get_size())))
                try:
                    buffer=io.BytesIO();bitmap.to_pil().save(buffer,format='PNG')
                finally:
                    bitmap.close()
                paths=[]
                for p in candidates:
                    if p['page'] != index: continue
                    pts=p['pdfPoints']; stride=max(1,math.ceil(len(pts)/160))
                    sample=pts[::stride]
                    if sample[-1]!=pts[-1]: sample.append(pts[-1])
                    paths.append({'id':p['id'],'d':'M'+' L'.join(f'{x:.3f} {-y:.3f}' for x,y in sample)+' Z'})
                review['pages'].append({'page':index+1,'viewBox':[left,-top,right-left,top-bottom],
                    'image':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii'),'paths':paths})
            finally:
                page.close()
    return review


def guide_review(raw, mapping, cut_spot, pages):
    candidates = [p for paths in pages for p in paths if p.get('possibleGuide')]
    if not candidates:
        return None
    if len(candidates) > 50:
        raise ValueError('More than 50 dashed cut lines need review. Separate guides from cuts in the source file.')
    source_hash = hashlib.sha256(raw).hexdigest()
    identity = [source_hash, mapping, cut_spot, [p['id'] for p in candidates]]
    review_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    previews = []
    for page_index, paths in enumerate(pages):
        if not any(p.get('possibleGuide') for p in paths):
            continue
        all_points = [pt for p in paths for pt in p['pdfPoints']]
        x0 = min(pt[0] for pt in all_points); x1 = max(pt[0] for pt in all_points)
        y0 = min(-pt[1] for pt in all_points); y1 = max(-pt[1] for pt in all_points)
        pad = max(x1-x0, y1-y0, 1) * .03
        outlines = []
        for p in paths:
            # Preview only: bound the display detail without changing source cuts.
            pts = p['pdfPoints']; stride = max(1, math.ceil(len(pts)/160))
            sample = pts[::stride]
            if sample[-1] != pts[-1]: sample.append(pts[-1])
            d = 'M' + ' L'.join(f'{x:.3f} {-y:.3f}' for x,y in sample)
            if p['closed']: d += ' Z'
            outlines.append({'id':p['id'], 'd':d, 'guide':bool(p.get('possibleGuide'))})
        previews.append({'page':page_index+1, 'viewBox':[x0-pad,y0-pad,x1-x0+2*pad,y1-y0+2*pad], 'paths':outlines})
    from shapely.geometry import LineString
    return {'id':review_id, 'sourceHash':source_hash, 'pages':previews,
            'lines':[{'id':p['id'],'page':p['page']+1,'lengthMm':LineString(p['pdfPoints']).length*MM} for p in candidates]}


def extract_page(page, writer, cut_spot, page_index, mapping, candidates=None, unnamed_operation=None, image_bounds=None):
    """Extract all mapped operations; flatten static layer visibility in print art."""
    from shapely.geometry import LineString
    from cut_mapping import classify
    paths_found=[]; budget=[0]; removed=[0]; mask_bounds={}

    def image_extent(obj):
        # Only proven zero-alpha borders may be excluded from nesting space.
        # Inspect the original 8-bit soft mask, never a thresholded preview.
        full=(0,0,1,1); mask=obj.get('/SMask')
        if mask is None or '/Mask' in obj or obj.get('/ImageMask'): return full
        mask=mask.get_object(); w=int(obj.get('/Width',0));h=int(obj.get('/Height',0))
        if (not 0<w*h<=16_000_000 or mask.get('/Width')!=w or mask.get('/Height')!=h or
            mask.get('/BitsPerComponent')!=8 or mask.get('/ColorSpace')!='/DeviceGray' or
            list(mask.get('/Decode',[0,1]))!=[0,1]): return full
        key=(id(mask),w,h)
        if key not in mask_bounds:
            from PIL import Image
            data=mask.get_data()
            if len(data)!=w*h: return full
            bbox=Image.frombytes('L',(w,h),data).getbbox()
            if bbox:
                x0,y0,x1,y1=bbox
                # One native pixel on each side also encloses interpolation.
                mask_bounds[key]=(max(0,x0-1)/w, max(0,h-y1-1)/h, min(w,x1+1)/w, min(h,h-y0+1)/h)
            else: mask_bounds[key]=full  # Keep a conservative empty-image box.
        return mask_bounds[key]

    def layer_names(value, resources):
        if value is None:return []
        if isinstance(value,NameObject):
            value=resources.get('/Properties',DictionaryObject()).get_object().get(value)
            if value is None:raise ValueError('A PDF layer reference is missing.')
        value=value.get_object()
        if not isinstance(value,DictionaryObject) or value.get('/Type')!='/OCG':
            raise ValueError('Conditional PDF layer visibility is not supported. Export all layers visible.')
        validate_layer_usage(value)
        return [str(value.get('/Name',''))]

    def visit(stream, resources, initial=IDENTITY, depth=0, inherited=None, clips=None, inherited_layers=None):
        if depth>16:raise ValueError('PDF forms are nested too deeply.')
        content=ContentStream(stream,writer)
        resources=DictionaryObject(resources.get_object())
        xobjects=DictionaryObject(resources['/XObject'] if '/XObject' in resources else {})
        resources[NameObject('/XObject')]=xobjects
        state=copy.deepcopy(inherited or {'stroke':None,'fill':None,'dashed':False,'textMode':0})
        state.update(matrix=initial,clips=list(clips or []))
        layers=list(inherited_layers or []); marks=[]; stack=[]
        paths=[]; commands=[]; points=[]; pending_clip=None; output=[]; path_output_start=0

        for value in resources.get('/Properties',DictionaryObject()).get_object().values():
            value=value.get_object()
            if isinstance(value,DictionaryObject) and value.get('/Type') in ('/OCG','/OCMD'):layer_names(value,resources)

        def finish_path(close=False):
            nonlocal commands,points
            if points:
                closed=close or (len(points)>2 and math.dist(points[0],points[-1])<1e-5)
                if close and (not commands or commands[-1][0]!='h'):commands.append(('h',[]))
                paths.append((commands,points,closed))
            commands=[];points=[]

        for operands,op in content.operations:
            budget[0]+=1
            if budget[0]>MAX_PAGE_OPERATIONS:raise ValueError('PDF page is too complex. Export a smaller print-only file.')
            if op==b'q':stack.append(copy.deepcopy(state))
            elif op==b'Q':
                if not stack:raise ValueError('PDF graphics state is unbalanced.')
                state=stack.pop()
            elif op==b'cm':state['matrix']=matrix(state['matrix'],tuple(map(float,operands)))
            elif op in (b'CS',b'cs'):
                space=resources.get('/ColorSpace',DictionaryObject()).get_object().get(operands[0])
                if space is not None:
                    space=space.get_object()
                    if isinstance(space,ArrayObject) and space[0]=='/DeviceN':
                        for name in space[1]:
                            if classify(mapping,str(name).removeprefix('/'),[],cut_spot):
                                raise ValueError('DeviceN cut colors are not supported. Export cut colors as Separation spots or use a supported layer-mapped source.')
                state['stroke' if op==b'CS' else 'fill']=spot_name(resources,operands[0])
            elif op in (b'G',b'RG',b'K'):state['stroke']=None
            elif op in (b'g',b'rg',b'k'):state['fill']=None
            elif op==b'd':state['dashed']=bool(operands[0])
            elif op==b'Tr':state['textMode']=int(operands[0])
            elif op==b'gs':
                settings=resources.get('/ExtGState',DictionaryObject()).get_object().get(operands[0])
                if settings is not None and '/D' in settings.get_object():state['dashed']=bool(settings.get_object()['/D'][0])
            elif op in (b'BDC',b'BMC'):
                marks.append(list(layers))
                if op==b'BDC' and operands[0]=='/OC':
                    layers+=layer_names(operands[1],resources)
                    # All permitted source layers are visible; retain their visual
                    # content without copying cut-layer wrappers into print art.
                    operands=[NameObject('/Artifact')];op=b'BMC'
            elif op==b'EMC':
                if not marks:raise ValueError('PDF marked content is unbalanced.')
                layers=marks.pop()
            elif op==b'm':
                finish_path();point_value=point(state['matrix'],operands)
                points=[point_value];commands=[('m',point_value)]
            elif op==b'l':
                if not points:raise ValueError('PDF line has no starting point.')
                point_value=point(state['matrix'],operands);points.append(point_value);commands.append(('l',point_value))
            elif op in (b'c',b'v',b'y'):
                if not points:raise ValueError('PDF curve has no starting point.')
                coords=[point(state['matrix'],operands[i:i+2]) for i in range(0,len(operands),2)]
                if op==b'v':coords.insert(0,points[-1])
                if op==b'y':coords.append(coords[-1])
                points.append(coords[-1]);commands.append(('c',[v for p in coords for v in p]))
            elif op==b're':
                finish_path();x,y,w,h=map(float,operands)
                points=[point(state['matrix'],p) for p in [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]]
                commands=[('m',points[0])]+[('l',p) for p in points[1:]];finish_path(True)
            elif op==b'h':finish_path(True)
            elif op in (b'W',b'W*'):pending_clip=op
            elif op in (b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'n'):
                finish_path(op in (b's',b'b',b'b*'))
                strokes=op in (b'S',b's',b'B',b'B*',b'b',b'b*')
                fills=op in (b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*')
                stroke_type=classify(mapping,state['stroke'],layers,cut_spot) if strokes else None
                fill_type=classify(mapping,state['fill'],layers,cut_spot) if fills else None
                from_unlabeled=False
                if (candidates is not None and strokes and not fills and not stroke_type and
                        not state['dashed'] and not pending_clip and paths and all(p[2] for p in paths)):
                    proposed=[]
                    for cmd,pts,closed in paths:
                        pts=flattened_path(cmd)
                        if not 3<=len(pts)<=5000 or any(not math.isfinite(v) for p in pts for v in p): break
                        geom=Polygon(pts);line=LineString(pts+[pts[0]])
                        if not geom.is_valid or geom.area*MM*MM<.01: break
                        if any(not c.buffer(.001).covers(line) for c in state['clips']): break
                        proposed.append({'id':f'p{page_index+1}-outline{len(candidates)+len(proposed)+1}',
                                         'page':page_index,'pdfPoints':pts})
                    if len(proposed)==len(paths):
                        candidates.extend(proposed)
                        if len(candidates)>5000: raise ValueError('Review no more than 5000 unnamed cut outlines per file.')
                        if unnamed_operation in ('kiss','thru'):
                            stroke_type=unnamed_operation;from_unlabeled=True
                if 'regmark' in (stroke_type,fill_type):
                    if (stroke_type not in (None,'regmark') or fill_type not in (None,'regmark')) or pending_clip:
                        raise ValueError('Registration paint conflicts with cutting or clipping. Separate it in the source.')
                    removed[0]+=1;op=b'n'
                else:
                    if fill_type:raise ValueError('Cut layers/colors must contain vector strokes, not filled shapes.')
                    if stroke_type:
                        if state['dashed'] and fills:raise ValueError('Dashed cuts combined with filled artwork need review in the source. Separate guides from artwork first.')
                        if pending_clip:raise ValueError('A cut stroke also changes the clipping path. Separate the cut from artwork clipping.')
                        for cmd,pts,closed in paths:
                            if state['dashed'] and closed:raise ValueError('Dashed closed cuts may be perforations. Review their cutting setup in the source; they cannot be excluded as open guides.')
                            pts=flattened_path(cmd)
                            if len(pts)<2 or len(pts)>5000 or any(not math.isfinite(v) for p in pts for v in p):raise ValueError('Invalid or oversized cut path.')
                            line=LineString(pts+[pts[0]] if closed else pts)
                            # A closed, exactly collinear slit has no interior.
                            # Preserve its source commands as an internal cut;
                            # group_paths still requires a unique outer owner.
                            boundary=closed and line.convex_hull.geom_type=='Polygon'
                            geom=Polygon(pts) if boundary else line
                            if not geom.is_valid or geom.is_empty or (boundary and geom.area*MM*MM<.01) or (not boundary and geom.length*MM<.01):raise ValueError('A cut path is self-intersecting or too small.')
                            # Only the stroke must be visible, not the enclosed
                            # interior (which can legitimately surround a hole).
                            if any(not c.buffer(.001).covers(line) for c in state['clips']):raise ValueError('A cut path is clipped. Correct its source clipping structure.')
                            paths_found.append({'id':f'p{page_index+1}-cut{len(paths_found)+1}','page':page_index,'commands':cmd,'pdfPoints':pts,'closed':closed,'boundary':boundary,'operation':stroke_type,'sourceSpot':state['stroke'],'sourceLayers':list(layers)})
                            if from_unlabeled: paths_found[-1]['fromUnlabeled']=True
                            if state['dashed']:paths_found[-1]['possibleGuide']=True
                            if len(paths_found)>2000:raise ValueError('Use no more than 2000 cut paths per page.')
                        if op in (b'b',b'b*'):output.append(([],b'h'))
                        op=(b'f*' if op.endswith(b'*') else b'f') if fills else b'n'
                if pending_clip:
                    state['clips'].append(clipping_region(paths,pending_clip));pending_clip=None
                paths=[]
                if op==b'n' and (stroke_type or fill_type):
                    # Removed cut strokes no longer need a million inert path
                    # commands in the print Form. Keep graphics-state operators
                    # and every filled/printed path; only nonpainting paths go.
                    output[path_output_start:]=[item for item in output[path_output_start:]
                        if item[1] not in (b'm',b'l',b'c',b'v',b'y',b're',b'h')]
                path_output_start=len(output)+1
            elif op==b'Do':
                ref=xobjects.get(operands[0])
                if ref is not None:
                    obj=ref.get_object();object_layers=layers+layer_names(obj.get('/OC'),resources)
                    layer_type=classify(mapping,None,object_layers,cut_spot)
                    if layer_type=='regmark':removed[0]+=1;continue
                    if obj.get('/Subtype')=='/Form':
                        transform=matrix(state['matrix'],tuple(map(float,obj.get('/Matrix',IDENTITY))))
                        form_clips=list(state['clips'])
                        if '/BBox' in obj:
                            x0,y0,x1,y1=map(float,obj['/BBox']);form_clips.append(Polygon([point(transform,p) for p in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]]))
                        body,nested=visit(obj,obj['/Resources'] if '/Resources' in obj else resources,transform,depth+1,state,form_clips,object_layers)
                        clone=DecodedStreamObject()
                        for k,v in obj.items():
                            if k not in ('/Length','/Filter','/DecodeParms','/Resources','/OC'):clone[k]=v
                        clone.set_data(body);clone[NameObject('/Resources')]=nested
                        key=NameObject('/EZNForm'+str(budget[0]));xobjects[key]=writer._add_object(clone);operands=[key]
                    else:
                        if layer_type:raise ValueError('A cut layer contains an image instead of vector paths.')
                        if image_bounds is not None and obj.get('/Subtype')=='/Image':
                            def rect(values):
                                x0,y0,x1,y1=values
                                return list(Polygon([point(state['matrix'],p) for p in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]).bounds)
                            image_bounds.append({'page':page_index,'box':rect((0,0,1,1)),'paint':rect(image_extent(obj))})
                        if '/OC' in obj:
                            clone=copy.copy(obj);clone.pop('/OC',None)
                            if hasattr(clone,'indirect_reference'):del clone.indirect_reference
                            key=NameObject('/EZNImage'+str(budget[0]));xobjects[key]=writer._add_object(clone);operands=[key]
            elif op in (b'Tj',b'TJ',b"'",b'"',b'sh',b'INLINE IMAGE'):
                layer_type=classify(mapping,state['fill'],layers,cut_spot)
                if op in (b'Tj',b'TJ',b"'",b'"') and state['textMode'] in (1,2,5,6):
                    stroke_type=classify(mapping,state['stroke'],layers,cut_spot)
                    if layer_type and stroke_type and layer_type!=stroke_type:raise ValueError('Text has conflicting cut or registration colors.')
                    layer_type=stroke_type or layer_type
                if layer_type=='regmark':
                    removed[0]+=1
                    if op in (b'Tj',b'TJ',b"'",b'"'):
                        if state['textMode']>=4:raise ValueError('Registration text also clips artwork. Separate it in the source.')
                        # Invisible text preserves text positioning for subsequent art.
                        output.extend([([NumberObject(3)],b'Tr'),(operands,op),([NumberObject(state['textMode'])],b'Tr')])
                    continue
                if layer_type:raise ValueError('Cut layers/colors contain text or non-vector paint. Outline the cut geometry first.')
            output.append((operands,op))
        if stack or marks:raise ValueError('PDF graphics or marked-content state is unbalanced.')
        content.operations=output
        return content.get_data(),resources

    body,resources=visit(page.get_contents(),page['/Resources'])
    stream=DecodedStreamObject();stream.set_data(body)
    page[NameObject('/Contents')]=writer._add_object(stream);page[NameObject('/Resources')]=resources
    return paths_found,removed[0]


def group_paths(paths):
    """Outermost closed contours own contained cuts; ambiguous geometry rejects."""
    from shapely.geometry import LineString
    if not paths:raise ValueError('No cut lines found. Check the cut spot names or cut layer mapping, then import a file with vector cut strokes.')
    closed={i:Polygon(p['pdfPoints']) for i,p in enumerate(paths) if p.get('boundary',p['closed'])}
    open_paths=[LineString(p['pdfPoints']) for p in paths if not p.get('boundary',p['closed'])]
    for i,path in enumerate(open_paths):
        if any(path.equals(other) for other in open_paths[i+1:]):raise ValueError('Duplicate/coincident open cuts need review in the source.')
    keys=list(closed); geometries=list(closed.values()); tree=STRtree(geometries)
    for i,a in closed.items():
        for position in tree.query(a):
            j=keys[position]; b=closed[j]
            if j<=i:continue
            if a.equals(b):raise ValueError('Duplicate/coincident cut boundaries need review in the source.')
            if a.intersection(b).area>.001 and not a.covers(b) and not b.covers(a):raise ValueError('Cut boundaries overlap without a unique piece owner.')
    outer={i:p for i,p in closed.items() if not any(keys[k]!=i and geometries[k].covers(p) for k in tree.query(p))}
    if not outer:raise ValueError('No closed piece boundary found. Open cut paths need a containing closed boundary.')
    owned={i:[] for i in outer}
    outer_keys=list(outer); boundaries=[p.buffer(.001) for p in outer.values()]; owner_tree=STRtree(boundaries)
    for index,path in enumerate(paths):
        geometry=closed[index] if index in closed else LineString(path['pdfPoints'])
        owners=[outer_keys[k] for k in owner_tree.query(geometry) if boundaries[k].covers(geometry)]
        if len(owners)!=1:raise ValueError('A cut path has no unique piece owner. Keep every cut inside one closed piece boundary.')
        owned[owners[0]].append(path)
    return [{**paths[i],'cutPaths':owned[i]} for i in outer]


def read_document(raw, bleed_mm=0, cut_spot='CutContour', cut_mapping=None, guide_approval=None, cut_approval=None):
    from cut_mapping import import_mapping,counts
    if not raw[:1024].lstrip().startswith(b'%PDF-'):raise ValueError('Use PDF, or save AI with Create PDF Compatible File enabled.')
    if not isinstance(cut_spot,str) or not cut_spot or len(cut_spot)>80 or any(ord(c)<32 for c in cut_spot):raise ValueError('Enter a valid generic cut spot name.')
    if type(bleed_mm) not in (int,float) or not math.isfinite(bleed_mm) or not 0<=bleed_mm<=25:raise ValueError('Existing artwork bleed must be between 0 and 25 mm.')
    mapping=import_mapping(cut_mapping,cut_spot)
    reader=PdfReader(io.BytesIO(raw),strict=False)
    if reader.is_encrypted:raise ValueError('Export an unencrypted PDF for nesting.')
    if not 1<=len(reader.pages)<=25:raise ValueError('Import between 1 and 25 PDF pages at a time.')
    if '/OCProperties' in reader.root_object:
        properties=reader.root_object['/OCProperties'];default=properties.get('/D',DictionaryObject()).get_object()
        if str(default.get('/BaseState','/ON'))!='/ON' or default.get('/OFF') or default.get('/AS'):raise ValueError('Export a print-only PDF with all layers visible. Hidden or conditional visibility is unsupported.')
        for group in properties.get('/OCGs',[]):
            validate_layer_usage(group.get_object())
    writer=PdfWriter();pieces=[];registration_removed=0;path_count=0;page_paths=[];candidates=[];image_bounds=[]
    unnamed_operation=cut_approval.get('operation') if isinstance(cut_approval,dict) else None
    for i,original in enumerate(reader.pages):
        if original.get('/Annots'):raise ValueError('Flatten annotations/forms in a print-only PDF before nesting.')
        if float(original.get('/UserUnit',1))!=1:raise ValueError('PDF UserUnit scaling is unsupported. Export at actual size with standard PDF units.')
        # Native Illustrator editing data is not PDF paint and is not needed in
        # the local print source. Preserve the original uploaded AI separately.
        page=writer.add_page(original, excluded_keys=['/PieceInfo', '/Thumb'])
        if page.rotation:page.transfer_rotation_to_content()
        paths,removed=extract_page(page,writer,cut_spot,i,mapping,candidates,unnamed_operation,image_bounds);registration_removed+=removed;path_count+=len(paths)
        if path_count>5000:raise ValueError('Use no more than 5000 cut paths per file.')
        page_paths.append(paths)
    known_cuts=any(not p.get('fromUnlabeled') for paths in page_paths for p in paths)
    if candidates and not known_cuts:
        review=unnamed_cut_review(raw,mapping,candidates,previews=cut_approval is None)
        if cut_approval is None: raise CutReviewRequired(review)
        if (not isinstance(cut_approval,dict) or set(cut_approval)!={'id','sourceHash','operation'} or
                cut_approval['id']!=review['id'] or cut_approval['sourceHash']!=review['sourceHash'] or
                unnamed_operation not in ('kiss','thru')):
            raise ValueError('The cut review does not match this file. Add it again and review its outlines.')
    elif cut_approval is not None:
        raise ValueError('This file has no matching unnamed cut review. Add the original file again.')
    review=guide_review(raw,mapping,cut_spot,page_paths)
    excluded=[]
    if review:
        expected=[p['id'] for p in review['lines']]
        if guide_approval is None:raise GuideReviewRequired(review)
        if (not isinstance(guide_approval,dict) or guide_approval.get('id')!=review['id']
                or guide_approval.get('sourceHash')!=review['sourceHash'] or guide_approval.get('excludedIds')!=expected):
            raise ValueError('The guide review does not match this file and cut mapping. Add the file again and review its lines.')
        excluded=expected
    elif guide_approval is not None:
        raise ValueError('This file has no matching guide review. Add the original file again.')
    for i,(page,paths) in enumerate(zip(writer.pages,page_paths)):
        paths=[p for p in paths if p['id'] not in excluded]
        page_pieces=group_paths(paths);crop=box(*map(float,page.cropbox))
        envelopes=[Polygon(p['pdfPoints']).buffer(bleed_mm/MM,join_style=2) if bleed_mm else Polygon(p['pdfPoints']) for p in page_pieces]
        envelope_tree=STRtree(envelopes)
        for piece_number,piece in enumerate(page_pieces,1):
            envelope=envelopes[piece_number-1]
            if not crop.buffer(.001).covers(envelope):raise ValueError('A piece plus bleed extends outside its PDF page. Correct the source or bleed setting.')
            if any(k<piece_number-1 and envelope.intersection(envelopes[k]).area>.001 for k in envelope_tree.query(envelope)):raise ValueError('Pieces or their bleed areas overlap. Separate printable pieces in the source.')
            x0,y0,x1,y1=envelope.bounds
            piece.update(id='pdf-'+str(len(pieces)+1),name=f'Page {i+1} · piece {piece_number}',anchor=[x0,y1],bounds=[x0,y0,x1,y1],
                         points=[[(x-x0)*MM,(y1-y)*MM] for x,y in envelope.exterior.coords[:-1]],
                         clipCommands=[('m',list(envelope.exterior.coords[0]))]+[('l',list(p)) for p in envelope.exterior.coords[1:]]+[('h',[])])
            if not bleed_mm:piece['clipCommands']=piece['commands']
            piece['cutCounts']=counts(piece);pieces.append(piece)
        if len(pieces)>5000:raise ValueError('Use no more than 5000 pieces per file.')
    if '/OutputIntents' in reader.root_object:writer.root_object[NameObject('/OutputIntents')]=reader.root_object['/OutputIntents'].clone(writer)
    # Source optional-content wrappers were flattened only after visibility checks.
    writer.root_object.pop('/OCProperties',None)
    buf=io.BytesIO();writer.write(buf)
    warnings=['Review piece ownership, cut types, size and existing bleed. Ink coverage and nested separate pieces are not automatically identified.']
    if registration_removed:warnings.append(f'{registration_removed} registration paint object(s) removed. Let the RIP generate new sheet registration marks.')
    if excluded:warnings.append(f'{len(excluded)} dashed guide line(s) excluded after operator review. Original artwork and remaining cuts are unchanged.')
    return buf.getvalue(),{'modelVersion':2,'pieces':pieces,'bleedMm':bleed_mm,'cutSpot':cut_spot,'cutMapping':mapping,
                          'registrationPaintRemoved':registration_removed,'excludedGuideIds':excluded,'reviewedCutOutlines':cut_approval,'imagePaintBounds':image_bounds,'warnings':warnings,'pages':len(reader.pages)}


def cut_bounds(piece):
    points = [point for path in piece.get('cutPaths') or [] for point in path.get('pdfPoints') or []]
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def bleed_artwork_matrix(bounds, bleed_mm):
    """Scale artwork about the cut-bounds center so each side grows by bleed_mm.

    The returned PDF matrix is applied only to the clip and art. Cut strokes stay
    on the original contour.
    """
    if not bounds or isinstance(bleed_mm, bool) or not isinstance(bleed_mm, (int, float)):
        return None
    if not math.isfinite(bleed_mm) or bleed_mm <= 0:
        return None
    x0, y0, x1, y1 = bounds
    width, height = x1 - x0, y1 - y0
    if width <= 1e-6 or height <= 1e-6:
        return None
    bleed = bleed_mm / MM
    sx = (width + 2 * bleed) / width
    sy = (height + 2 * bleed) / height
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (sx, 0, 0, sy, cx * (1 - sx), cy * (1 - sy))



def prepare_nesting_geometry(job, documents=None):
    """Reserve exported paint while preserving source coordinates and cut paths.

    PDF Bezier controls enclose the exact clipped path, so the convex hull is
    conservative even when the cut polygon was flattened for the search. Apply
    the same nonuniform matrix as export, including any existing import bleed.
    Never accept a client-supplied print envelope.
    """
    bleed = job.get('settings', {}).get('autoBleedMm') or 0
    if type(bleed) not in (int, float) or not math.isfinite(bleed) or not 0 <= bleed <= 25:
        raise ValueError('Auto bleed must be from 0 to 25 mm.')
    parts = job.get('parts', []) + [p for fill in job.get('fillJobs', []) for p in fill['parts']]
    for part in parts:
        part.pop('nestingPoints', None)
        if not bleed:
            continue
        original = Polygon(part['points'])
        if part.get('documentId'):
            if not documents or part['documentId'] not in documents:
                raise ValueError('Load the original PDF before adding auto bleed.')
            meta = documents[part['documentId']][1]
            if meta.get('artworkPreserved'):
                raise ValueError('Prepared artwork already retains its bleed; automatic enlargement is unavailable.')
            piece = next(p for p in meta['pieces'] if p['id'] == part['pdfPieceId'])
            transform = bleed_artwork_matrix(cut_bounds(piece), bleed)
            if transform is None:
                continue
            controls = [point(transform, values[i:i+2]) for op, values in piece['clipCommands']
                        for i in range(0, len(values), 2)]
            x0, y1 = piece['anchor']
            envelope = MultiPoint([((x-x0)*MM, (y1-y)*MM) for x, y in controls]).convex_hull
            envelope = original.union(envelope).convex_hull
        else:
            # SVG auto bleed uses round strokes; miter space contains that paint.
            envelope = original.buffer(bleed, join_style=2)
        part['nestingPoints'] = [list(p) for p in envelope.exterior.coords[:-1]]


def validate_auto_bleed_export(job, result, documents):
    """Independently reject a stale/tampered layout at the final PDF boundary."""
    if not job.get('settings', {}).get('autoBleedMm'):
        return
    checked = copy.deepcopy(job)
    prepare_nesting_geometry(checked, documents)
    parts = {p['id']: p for p in checked['parts']}
    settings = checked.get('settings', {})
    margin, gap = settings.get('margin', 0), settings.get('gap', 0)
    sheets = result.get('sheets') or [{'index': 0, 'offset': 0, 'usedLength': result['usedLength']}]
    for sheet in sheets:
        boundary = box(margin, margin, result['width']-margin, sheet['usedLength']-margin)
        occupied = []
        for placement in result['placements']:
            if placement.get('sheet', 0) != sheet['index']:
                continue
            part = parts[placement['id']]
            shape = translate(rotate(Polygon(part.get('nestingPoints', part['points'])),
                                     placement['rotation'], origin=(0, 0)),
                              placement['x'], placement['y']-sheet['offset'])
            if not boundary.buffer(.001).covers(shape) or any(
                    shape.intersection(other).area > .0001 or shape.distance(other)+.001 < gap
                    for other in occupied):
                raise ValueError('Auto bleed needs more space. Nest again with this bleed setting before exporting.')
            occupied.append(shape)


def regmark_operators(width_mm, height_mm, margin_mm):
    """Corner LNRegmark strokes in PDF points. No barcode."""
    band = margin_mm if isinstance(margin_mm, (int, float)) and not isinstance(margin_mm, bool) and margin_mm > 1 else 6
    inset = min(band * 0.4, width_mm * 0.2, height_mm * 0.2) / MM
    arm = min(max(band * 0.5, 4), 14) / MM
    width, height = width_mm / MM, height_mm / MM
    corners = ((inset, inset, 1, 1), (width - inset, inset, -1, 1), (inset, height - inset, 1, -1), (width - inset, height - inset, -1, -1))
    parts = []
    for x, y, sx, sy in corners:
        parts.append(f'{x:.3f} {y:.3f} m {x + sx * arm:.3f} {y:.3f} l {x:.3f} {y:.3f} m {x:.3f} {y + sy * arm:.3f} l')
    return ' '.join(parts) + ' S'


def form_from_page(page, writer):
    form = DecodedStreamObject(); form.set_data(page.get_contents().get_data())
    form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                 NameObject('/BBox'):page.cropbox.clone(writer),NameObject('/Resources'):page['/Resources'].clone(writer)})
    if '/Group' in page: form[NameObject('/Group')]=page['/Group'].clone(writer)
    return writer._add_object(form)


def sheet_id_operators(width_mm, height_mm, margin_mm, sheet_id):
    """Small layout id in the bottom margin, outside the corner mark area. No barcode."""
    if not isinstance(sheet_id, str) or not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z-]{0,79}', sheet_id):
        return ''
    band = margin_mm if isinstance(margin_mm, (int, float)) and not isinstance(margin_mm, bool) and margin_mm > 0 else 4
    x = (width_mm / 2) / MM
    y = max(band * 0.28, 1.6) / MM
    return f'q 0 g BT /EZSheetFont 6 Tf {x:.2f} {y:.2f} Td ({sheet_id}) Tj ET Q'


def export_pdf(job, result, documents, cut_spot='CutContour', cut_layer='CutContour', sheet_filter=None, cut_mapping=None, sheet_id=None, preview=False):
    """Transform a piece's print art and every owned cut using one rigid matrix."""
    validate_auto_bleed_export(job, result, documents)
    from cut_mapping import output_mapping,OPERATIONS
    mapping=output_mapping({'cutMapping':cut_mapping} if cut_mapping else {'cutSpot':cut_spot,'cutLayer':cut_layer})
    writer=PdfWriter();writer.pdf_header='%PDF-1.7'
    forms={};readers={};output_intents=[]
    for ident,(raw,meta) in documents.items():
        reader=PdfReader(io.BytesIO(raw));readers[ident]=reader
        if reader.pdf_header>writer.pdf_header:writer.pdf_header=reader.pdf_header
        if '/OutputIntents' in reader.root_object:
            intents=reader.root_object['/OutputIntents']
            profiles=[hashlib.sha256(o.get_object()['/DestOutputProfile'].get_data()).hexdigest() for o in intents if '/DestOutputProfile' in o.get_object()]
            if output_intents and output_intents[0]!=profiles:raise ValueError('Source PDFs have different output profiles. Use compatible source PDFs before mixing jobs.')
            if not output_intents:
                output_intents.append(profiles);writer.root_object[NameObject('/OutputIntents')]=intents.clone(writer)
        for page_index,page in enumerate(reader.pages):forms[(ident,page_index)]=form_from_page(page,writer)
    active=[op for op in OPERATIONS if any(c['operation']==op for raw,meta in documents.values() for p in meta['pieces'] for c in p['cutPaths'])]
    settings=job.get('settings') or {}
    draw_marks=settings.get('drawRegmarks') is True
    bleed_mm=settings.get('autoBleedMm') or 0
    if bleed_mm and any(meta.get('artworkPreserved') for _,meta in documents.values()):
        raise ValueError('Original artwork preservation does not allow automatic enlargement.')
    groups={};spaces={};keys={}
    for index,operation in enumerate(active):
        config=mapping['outputs'][operation];keys[operation]=('/EZCut'+(str(index) if index else ''),'/EZCutLayer'+(str(index) if index else ''))
        groups[operation]=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject(config['layer'])}))
        tint=DictionaryObject({NameObject('/FunctionType'):NumberObject(2),NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)]),NameObject('/C0'):ArrayObject([NumberObject(0)]*4),NameObject('/C1'):ArrayObject([NumberObject(v) for v in ([1,0,0,0] if operation=='thru' else [0,1,0,0])]),NameObject('/N'):NumberObject(1)})
        spaces[operation]=ArrayObject([NameObject('/Separation'),NameObject('/'+config['spot']),NameObject('/DeviceCMYK'),writer._add_object(tint)])
    reg_group=reg_space=None
    if draw_marks:
        reg_group=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject('LNRegmark')}))
        reg_tint=DictionaryObject({NameObject('/FunctionType'):NumberObject(2),NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)]),NameObject('/C0'):ArrayObject([NumberObject(0)]*4),NameObject('/C1'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(0),NumberObject(1)]),NameObject('/N'):NumberObject(1)})
        reg_space=ArrayObject([NameObject('/Separation'),NameObject('/LNRegmark'),NameObject('/DeviceCMYK'),writer._add_object(reg_tint)])
    print_group = writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject('print')})) if job.get('illustrator') else None
    layers=ArrayObject(([print_group] if print_group else [])+list(groups.values())+([reg_group] if reg_group else []))
    writer.root_object[NameObject('/OCProperties')]=DictionaryObject({NameObject('/OCGs'):layers,NameObject('/D'):DictionaryObject({NameObject('/Order'):layers,NameObject('/ON'):layers})})
    parts={p['id']:p for p in job['parts']}
    sheets=result.get('sheets') or [{'index':0,'offset':0,'usedLength':result['usedLength']}]
    for sheet in sheets:
        if sheet_filter is not None and sheet['index']!=sheet_filter:continue
        if not 0<sheet['usedLength']<=5000 or not 0<result['width']<=5000:raise ValueError('PDF sheets are limited to 5000 mm per side. Set a maximum sheet length for a longer batch.')
        page_width=sheet.get('previewWidth',result['width']) if preview else result['width']
        page=writer.add_blank_page(width=page_width/MM,height=sheet['usedLength']/MM)
        color_spaces={NameObject(keys[op][0]):spaces[op] for op in active}
        properties={NameObject(keys[op][1]):groups[op] for op in active}
        if print_group:
            properties[NameObject('/EZPrint')] = print_group
        if draw_marks:
            color_spaces[NameObject('/EZReg')]=reg_space
            properties[NameObject('/EZRegLayer')]=reg_group
        resources=DictionaryObject({NameObject('/XObject'):DictionaryObject(),NameObject('/ColorSpace'):DictionaryObject(color_spaces),
            NameObject('/Properties'):DictionaryObject(properties),
            NameObject('/ExtGState'):DictionaryObject({NameObject('/EZOverprint'):DictionaryObject({NameObject('/Type'):NameObject('/ExtGState'),NameObject('/OP'):__import__('pypdf').generic.BooleanObject(True)})})})
        page[NameObject('/Resources')]=resources;chunks=[]
        for placement in result['placements']:
            if placement.get('sheet',0)!=sheet['index']:continue
            part=parts[placement['id']];ident=part['documentId'];meta=documents[ident][1]
            piece=next(p for p in meta['pieces'] if p['id']==part['pdfPieceId'])
            x0,y1=piece['anchor'];theta=math.radians(placement['rotation']);c,s=math.cos(theta),math.sin(theta)
            tx=placement['x']/MM-c*x0-s*y1
            ty=(sheet['usedLength']-(placement['y']-sheet['offset']))/MM+s*x0-c*y1
            key=NameObject('/Art'+str(len(resources['/XObject'])+1));resources['/XObject'][key]=forms[(ident,piece['page'])]
            placement_cm=' '.join(f'{v:.9f}' for v in (c,-s,s,c,tx,ty))
            bleed=bleed_artwork_matrix(cut_bounds(piece), bleed_mm) if piece.get('cutPaths') else None
            if bleed:
                bleed_cm=' '.join(f'{v:.9f}' for v in bleed)
                chunk='q\n'+placement_cm+' cm\nq\n'+bleed_cm+' cm\nq\n'+path_text(piece['clipCommands'])+'\nW n\n'+str(key)+' Do\nQ\nQ\n'
            else:
                chunk='q\n'+placement_cm+' cm\nq\n'+path_text(piece['clipCommands'])+'\nW n\n'+str(key)+' Do\nQ\n'
            if print_group:
                chunk = chunk.replace(str(key)+' Do', '/OC /EZPrint BDC\n'+str(key)+' Do\nEMC')
            for path in piece['cutPaths']:
                color,layer=keys[path['operation']]
                chunk+='/OC '+layer+' BDC\n/EZOverprint gs\n'+color+' CS 1 SCN\n0.25 w\n'+path_text(path['commands'])+'\nS\nEMC\n'
            chunks.append(chunk+'Q')
        if draw_marks:
            band=settings.get('markMargin') or settings.get('margin') or 0
            chunks.append('q\n/OC /EZRegLayer BDC\n/EZOverprint gs\n/EZReg CS 1 SCN\n0.4 w\n'+regmark_operators(result['width'], sheet['usedLength'], band)+'\nEMC\nQ')
        label=sheet_id_operators(result['width'], sheet['usedLength'], settings.get('markMargin') or settings.get('margin') or 0, sheet_id)
        if label:
            resources[NameObject('/Font')]=DictionaryObject({NameObject('/EZSheetFont'):DictionaryObject({
                NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})})
            chunks.append(label)
        stream=DecodedStreamObject();stream.set_data('\n'.join(chunks).encode('ascii'));page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_metadata({'/Creator':'eznest','/Title':'Nested artwork and separate cut operations — review in RIP'})
    out=io.BytesIO();writer.write(out);return out.getvalue()


def import_to_store(raw, folder, bleed_mm=0, cut_spot='CutContour', cut_mapping=None, preserve=False, guide_approval=None, cut_approval=None):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    clean,meta=read_document(raw,0 if preserve else bleed_mm,cut_spot,cut_mapping,guide_approval,cut_approval)
    if preserve:
        from artwork_bounds import preserve_artwork
        meta=preserve_artwork(clean,meta)
    identity=[2,bleed_mm,cut_spot,meta['cutMapping']]
    if preserve:identity=['preserve-artwork-v2',cut_spot,meta['cutMapping']]
    if meta['excludedGuideIds']:identity.append({'excludedGuideIds':meta['excludedGuideIds']})
    if cut_approval:identity.append({'reviewedCutOutlines':cut_approval})
    ident=hashlib.sha256(raw+json.dumps(identity,sort_keys=True).encode()).hexdigest()
    meta.update(id=ident,sourceHash=hashlib.sha256(raw).hexdigest())
    # Preview in a separate process through the import worker. PDFium is not thread-safe.
    import pypdfium2 as pdfium
    preview_parts=[];preview_sheets=[];placements=[];preview_items=[];offset=0
    for index,piece in enumerate(meta['pieces']):
        w=(piece['bounds'][2]-piece['bounds'][0])*MM; h=(piece['bounds'][3]-piece['bounds'][1])*MM
        preview_items.append({'id':piece['id'],'documentId':ident,'pdfPieceId':piece['id']})
        preview_sheets.append({'index':index,'offset':offset,'usedLength':h,'previewWidth':w})
        placements.append({'id':piece['id'],'x':0,'y':offset,'rotation':0,'sheet':index});offset+=h
    # One PDF document shares the source Form across all preview pages. Parsing
    # and copying a detailed AI once per piece can take minutes for a full kit.
    preview=export_pdf({'parts':preview_items}, {'width':max(s['previewWidth'] for s in preview_sheets),'usedLength':offset,'placements':placements,'sheets':preview_sheets}, {ident:(clean,meta)},cut_spot,cut_mapping=meta['cutMapping'],preview=True)
    # Keep a large order's screen thumbnails bounded. The print export below
    # still uses the original PDF objects at their original resolution.
    preview_edge=min(600, max(32, int(math.sqrt(6_000_000 / len(meta['pieces'])))))
    with pdfium.PdfDocument(preview) as doc:
      for index,piece in enumerate(meta['pieces']):
        w=preview_sheets[index]['previewWidth']; h=preview_sheets[index]['usedLength']
        page=doc[index]; bitmap=None
        try:
            bitmap=page.render(scale=min(2,preview_edge/max(page.get_size())),fill_color=(255,255,255,0))
            image=bitmap.to_pil(); buffer=io.BytesIO(); image.save(buffer,format='PNG')
        finally:
            if bitmap is not None:bitmap.close()
            page.close()
        unknown=[]
        for path in piece.get('cutPaths') or []:
            if path.get('operation') in ('thru','kiss','regmark'): continue
            layers=path.get('sourceLayers') or []
            if layers: unknown.append({'source':'layer','name':str(layers[0])})
            elif path.get('sourceSpot'): unknown.append({'source':'spot','name':str(path['sourceSpot'])})
        if not unknown and piece.get('cutCounts',{}).get('contour'):
            unknown.append({'source':'spot','name':cut_spot or 'CutContour'})
        preview_cuts=[]
        x0,y1=piece['anchor']
        for cut in piece['cutPaths']:
            commands=[]
            display_commands=cut['commands']
            if len(meta['pieces'])>200:
                from shapely.geometry import LineString
                pts=list(LineString(cut['pdfPoints']).simplify(.04/MM,preserve_topology=True).coords)
                display_commands=[('m',pts[0])]+[('l',p) for p in pts[1:]]+([('h',[])] if cut['closed'] else [])
            for command,values in display_commands:
                coords=[((value-x0) if index%2==0 else (y1-value))*MM for index,value in enumerate(values)]
                commands.append(('Z' if command=='h' else command.upper())+' '+' '.join(f'{v:.6f}' for v in coords))
            preview_cuts.append({'operation':cut['operation'],'d':' '.join(commands)})
        preview_parts.append({'id':piece['id'],'name':piece['name'],'points':piece['points'],'quantity':1,
                              'documentId':ident,'pdfPieceId':piece['id'],'sourcePieceCount':piece.get('sourcePieceCount',1),'cutCounts':piece['cutCounts'],'cutRefs':unknown,'previewCuts':preview_cuts,'preview':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(), 'previewWidth':w,'previewHeight':h})
    (folder/(ident+'.pdf')).write_bytes(clean)
    (folder/(ident+'.json')).write_text(json.dumps(meta),encoding='utf-8')
    return {'format':'pdf','documentId':ident,'parts':preview_parts,'warnings':meta['warnings'],'excludedGuideCount':len(meta['excludedGuideIds']),'bleedMm':meta['bleedMm'],'artworkPreserved':bool(meta.get('artworkPreserved')),'sourcePieceCount':meta.get('sourcePieceCount',len(meta['pieces'])),'reviewed':False,'modelVersion':2,'registrationPaintRemoved':meta['registrationPaintRemoved'],'cutMapping':meta['cutMapping']}


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
        if meta.get('modelVersion')!=2: raise ValueError('Re-add this PDF/AI file to review its cut types with the updated importer.')
        data['excludedGuideCount']=len(meta.get('excludedGuideIds',[]))
        documents[ident]=(raw,meta)
        actual={p['pdfPieceId']:p for p in job['parts'] if p.get('sourceJobId')==source['id']}
        if set(actual)!=set(p['id'] for p in meta['pieces']): raise ValueError('PDF source pieces no longer match this job. Re-import it.')
        for p in meta['pieces']:
            item=actual[p['id']]
            item['cutCounts']=p['cutCounts']
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
    if any(meta.get('registrationPaintRemoved') for raw,meta in documents.values()) and profile.get('registrationOwner') not in ('rip','finishing'):
        issues.append('Source registration marks were removed. Choose RIP or finishing software to generate new sheet marks.')
    required=profile.get('bleedMm')
    if required is None: issues.append('Confirm required bleed in the output profile (0 for none).')
    elif any(meta['bleedMm']+1e-6<required for raw,meta in documents.values()): issues.append('An imported file reserves less existing bleed than the output profile requires. Re-import with the correct bleed.')
    return {'ready':not issues,'actualFormat':'pdf','issues':issues,'bleedVerification':'operator-reviewed; no automatic ink-coverage verification','colorHandling':'source preserved; RIP manages conversion'}


def worker(request, output, source_file=None):
    request=Path(request); output=Path(output)
    print_copy = None
    try:
        data=json.loads(request.read_text(encoding='utf-8'))
        if source_file is not None:
            source = Path(source_file)
            if source.stat().st_size > MAX_PDF_BYTES:
                raise ValueError('PDF/AI files are limited to 2 GB.')
            if source.stat().st_size > 32_000_000:
                from pdf_compact import compact_pdf
                print_copy = source.with_name(source.stem + '-print.pdf')
                compact_pdf(source, print_copy)
                source = print_copy
            raw = source.read_bytes()
            if len(raw) > MAX_PDF_BYTES:
                raise ValueError('PDF/AI files are limited to 2 GB.')
        else:
            content=data['content']
            if not isinstance(content,str) or len(content)>MAX_PDF_BASE64_CHARS:
                raise ValueError('JSON PDF imports are limited to 256 MB. Use the browser file upload for larger files.')
            raw=base64.b64decode(content,validate=True)
            if len(raw)>MAX_JSON_PDF_BYTES:
                raise ValueError('JSON PDF imports are limited to 256 MB. Use the browser file upload for larger files.')
        result={'ok':True,'document':import_to_store(raw,output.parent/'documents',data.get('bleedMm',0),data.get('cutSpot','CutContour'),data.get('cutMapping'),preserve=data.get('preserveArtwork') is True,guide_approval=data.get('guideApproval'),cut_approval=data.get('cutApproval'))}
    except CutReviewRequired as error:
        result={'ok':False,'error':str(error),'cutReview':error.review}
    except GuideReviewRequired as error:
        result={'ok':False,'error':str(error),'guideReview':error.review}
    except Exception as error:
        result={'ok':False,'error':str(error)}
    finally:
        if print_copy is not None:
            try:
                print_copy.unlink(missing_ok=True)
            except OSError:
                pass  # The server retries cleanup after this worker exits.
    output.write_text(json.dumps(result),encoding='utf-8')


if __name__=='__main__':
    import sys
    worker(*sys.argv[1:])
