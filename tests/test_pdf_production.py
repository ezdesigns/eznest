import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, DecodedStreamObject
from pdf_io import read_document, import_to_store, export_pdf, load_documents, output_check, bleed_artwork_matrix, cut_bounds, prepare_nesting_geometry, MM
from production import make_package


def pdf_fixture(forms=False, spot=True, opened=False, overlap=False):
    writer=PdfWriter(); page=writer.add_blank_page(width=400,height=300)
    tint=DictionaryObject({NameObject('/FunctionType'):NumberObject(2),NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)]),NameObject('/C0'):ArrayObject([NumberObject(0)]*4),NameObject('/C1'):ArrayObject([NumberObject(0),NumberObject(1),NumberObject(0),NumberObject(0)]),NameObject('/N'):NumberObject(1)})
    resources=DictionaryObject({NameObject('/ColorSpace'):DictionaryObject({NameObject('/Contour'):ArrayObject([NameObject('/Separation'),NameObject('/CutContour'),NameObject('/DeviceCMYK'),writer._add_object(tint)])})})
    close='' if opened else 'h'
    contour='/Contour CS 1 SCN' if spot else '1 0 1 RG'
    first=f'q 1 0 0 0 k 10 10 110 90 re f {contour} 0.25 w 20 20 m 100 20 l 120 40 100 80 100 80 c 20 80 l {close} S Q'
    second='q 0 0 1 0 k 180 20 100 90 re f '+contour+' 190 30 80 60 re S Q'
    stream=DecodedStreamObject()
    if forms:
        form=DecodedStreamObject(); form.set_data(first.encode()); form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(n) for n in [0,0,150,120]]),NameObject('/Resources'):resources})
        ref=writer._add_object(form)
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Panel'):ref})})
        stream.set_data(b'q 1 0 0 1 10 10 cm /Panel Do Q q 0 1 -1 0 300 100 cm /Panel Do Q')
    else:
        page[NameObject('/Resources')]=resources
        stream.set_data((first+'\n'+(first if overlap else second)).encode())
    page[NameObject('/Contents')]=writer._add_object(stream)
    buffer=io.BytesIO(); writer.write(buffer); return buffer.getvalue()


def square_pdf_fixture():
    writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
    stream = DecodedStreamObject()
    width = 20 / MM
    stream.set_data(('q 1 0 0 0 k 20 20 {0} {0} re f /Contour CS 1 SCN 20 20 {0} {0} re S Q\n'
                     'q 0 0 1 0 k 200 20 {0} {0} re f /Contour CS 1 SCN 200 20 {0} {0} re S Q').format(width).encode())
    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()


def document_job(parsed):
    return {'materialId':'test','materialName':'Test stock','settings':{'width':100,'maxLength':None,'gap':2,'margin':2,'seconds':1,'rotations':[0,90,180,270]},
            'parts':[{**p,'id':'job:'+p['id'],'sourceJobId':'job','perSet':1} for p in parsed['parts']],
            'productionJobs':[{'id':'job','code':'A','name':'Kit.pdf','revision':'test','sets':1,'materialId':'test','partIds':['job:'+p['id'] for p in parsed['parts']],'customer':'Customer One','order':'ORDER-12','kit':'MX'}],
            'documentSources':{'job':{'documentId':parsed['documentId'],'reviewed':True,'bleedMm':parsed['bleedMm']}},
            'outputProfile':{'name':'PDF','rip':'Test','format':'pdf','acceptedFormats':['pdf','ai'],'colorMode':'preserve','iccProfile':'','bleedMm':0,'cutSpot':'CutContour','cutLayer':'CutContour','registrationOwner':'rip','finishingSoftware':'','mediaOwner':'rip','jobLogOwner':'rip'}}


class PDFProductionTests(unittest.TestCase):
    def test_creator_metadata_is_not_a_visibility_rule(self):
        from pypdf.generic import TextStringObject
        from cut_mapping import defaults
        writer=PdfWriter(clone_from=io.BytesIO(pdf_fixture(spot=False)))
        creator=DictionaryObject({NameObject('/Creator'):TextStringObject('Adobe Illustrator'),NameObject('/Subtype'):NameObject('/Artwork')})
        group=DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject('thru-cut'),NameObject('/Usage'):DictionaryObject({NameObject('/CreatorInfo'):creator})})
        ref=writer._add_object(group)
        writer.root_object[NameObject('/OCProperties')]=DictionaryObject({NameObject('/OCGs'):ArrayObject([ref])})
        page=writer.pages[0]
        page['/Resources'][NameObject('/Properties')]=DictionaryObject({NameObject('/Cuts'):ref})
        stream=DecodedStreamObject();stream.set_data(b'/OC /Cuts BDC 20 20 80 60 re S EMC')
        page[NameObject('/Contents')]=writer._add_object(stream)
        def raw():
            out=io.BytesIO();writer.write(out);return out.getvalue()
        clean,meta=read_document(raw(),cut_mapping=defaults())
        self.assertEqual(meta['pieces'][0]['cutCounts']['thru'],1)
        self.assertAlmostEqual(meta['pieces'][0]['points'][1][0],80*MM)
        for key in ('/View','/Print','/Zoom','/Language','/User'):
            group['/Usage'][NameObject(key)]=DictionaryObject()
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'conditional'):
                read_document(raw(),cut_mapping=defaults())
            del group['/Usage'][key]

    def test_detailed_ink_is_preserved_without_flattening_its_curves(self):
        writer=PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        stream=DecodedStreamObject()
        ink=b'q 0 0 1 rg 15 15 m 20 40 40 40 60 15 c h f Q\n'
        # More than the previous page-operation cap; cut geometry stays simple.
        stream.set_data(ink*40000+b'/Contour CS 1 SCN 20 20 80 60 re S')
        writer.pages[0][NameObject('/Contents')]=writer._add_object(stream)
        raw=io.BytesIO();writer.write(raw)
        with patch('pdf_io.curve_points',side_effect=AssertionError('Ordinary ink was flattened')):
            clean,meta=read_document(raw.getvalue())
        self.assertEqual(len(meta['pieces']),1)
        self.assertEqual(PdfReader(io.BytesIO(clean)).pages[0].get_contents().get_data().count(b' c\n'),40000)
        with patch('pdf_io.MAX_PAGE_OPERATIONS',100),self.assertRaisesRegex(ValueError,'too complex'):
            read_document(raw.getvalue())

    def test_curved_clipping_still_rejects_a_clipped_cut(self):
        writer=PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        stream=DecodedStreamObject()
        stream.set_data(b'q 20 20 m 20 80 l 100 80 l 100 20 l 80 70 40 70 20 20 c h W n /Contour CS 1 SCN 30 25 50 30 re S Q')
        writer.pages[0][NameObject('/Contents')]=writer._add_object(stream)
        raw=io.BytesIO();writer.write(raw)
        with self.assertRaisesRegex(ValueError,'clipped'):
            read_document(raw.getvalue())

    def test_shared_preview_pages_match_individual_vector_exports(self):
        import pypdfium2 as pdfium
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            parsed=import_to_store(pdf_fixture(forms=True),directory)
            ident=parsed['documentId']
            meta=json.loads((Path(directory)/(ident+'.json')).read_text())
            clean=(Path(directory)/(ident+'.pdf')).read_bytes()
            for part,piece in zip(parsed['parts'],meta['pieces']):
                w,h=part['previewWidth'],part['previewHeight']
                single=export_pdf({'parts':[part]},{'width':w,'usedLength':h,'placements':[{'id':part['id'],'x':0,'y':0,'rotation':0}]},{ident:(clean,meta)},cut_mapping=meta['cutMapping'])
                with pdfium.PdfDocument(single) as doc:
                    page=doc[0];bitmap=page.render(scale=min(2,600/max(page.get_size())),fill_color=(255,255,255,0))
                    expected=bitmap.to_pil().copy();bitmap.close();page.close()
                actual=Image.open(io.BytesIO(base64.b64decode(part['preview'].split(',',1)[1])))
                self.assertEqual(actual.size,expected.size)
                self.assertEqual(actual.tobytes(),expected.tobytes())

    def test_cut_detection_retains_curves_and_source_colors(self):
        clean,meta=read_document(pdf_fixture(),2)
        self.assertEqual(len(meta['pieces']),2)
        self.assertTrue(any(op=='c' for op,values in meta['pieces'][0]['commands']))
        ops=PdfReader(io.BytesIO(clean)).pages[0].get_contents().operations
        self.assertTrue(any(op==b'k' for args,op in ops))
        self.assertFalse(any(op==b'S' for args,op in ops))
        self.assertGreater(max(p[0] for p in meta['pieces'][0]['points']),80*MM)

    def test_transformed_reused_form_contours(self):
        clean,meta=read_document(pdf_fixture(forms=True),0)
        self.assertEqual(len(meta['pieces']),2)
        self.assertAlmostEqual(meta['pieces'][0]['pdfPoints'][0][0],30)
        self.assertAlmostEqual(meta['pieces'][1]['pdfPoints'][0][0],280)
        self.assertAlmostEqual(meta['pieces'][1]['pdfPoints'][0][1],120)

    def test_non_pdf_open_ordinary_and_overlapping_contours_rejected(self):
        for raw in [b'%!PS Illustrator file',pdf_fixture(spot=False),pdf_fixture(opened=True),pdf_fixture(overlap=True)]:
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(ValueError):read_document(raw)

    def test_conditional_layers_rejected_and_rotated_pages_preserve_size(self):
        writer=PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        properties=DictionaryObject({NameObject('/HiddenCut'):DictionaryObject({NameObject('/Type'):NameObject('/OCMD')})})
        writer.pages[0]['/Resources'][NameObject('/Properties')]=properties
        buffer=io.BytesIO();writer.write(buffer)
        with self.assertRaisesRegex(ValueError,'Conditional'):read_document(buffer.getvalue())
        writer=PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        writer.pages[0].rotate(90)
        buffer=io.BytesIO();writer.write(buffer)
        clean,meta=read_document(buffer.getvalue())
        bounds=meta['pieces'][1]['bounds']
        self.assertAlmostEqual((bounds[2]-bounds[0])*MM,60*MM)
        self.assertAlmostEqual((bounds[3]-bounds[1])*MM,80*MM)

    def test_excessive_pdf_length_requires_sheet_limit(self):
        with self.assertRaisesRegex(ValueError,'maximum sheet length'):
            export_pdf({'parts':[]},{'width':100,'usedLength':5100,'placements':[]},{})

    def test_review_tamper_and_source_availability_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed=import_to_store(pdf_fixture(),directory,1)
            job=document_job(parsed)
            self.assertTrue(output_check(job,directory)['ready'])
            job['documentSources']['job']['reviewed']=False
            self.assertFalse(output_check(job,directory)['ready'])
            job['documentSources']['job']['reviewed']=True
            job['parts'][0]['points'][0][0]+=1
            with self.assertRaisesRegex(ValueError,'geometry'):load_documents(job,directory)

    def test_pdf_export_is_vector_spot_layered_scaled_and_sheeted(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed=import_to_store(pdf_fixture(),directory,1)
            job=document_job(parsed); job['settings']['sheetLength']=50
            docs=load_documents(job,directory)
            result={'width':100,'usedLength':90,'sheets':[{'index':0,'offset':0,'usedLength':45},{'index':1,'offset':45,'usedLength':45}],
                    'placements':[{'id':job['parts'][0]['id'],'x':35,'y':3,'rotation':90,'sheet':0},{'id':job['parts'][1]['id'],'x':3,'y':48,'rotation':0,'sheet':1}]}
            raw=export_pdf(job,result,docs)
            reader=PdfReader(io.BytesIO(raw))
            self.assertEqual(reader.pdf_header,'%PDF-1.7')
            self.assertEqual(len(reader.pages),2)
            clean_again,meta_again=read_document(raw)
            self.assertEqual(len(meta_again['pieces']),2)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.width)*MM,100,places=4)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.height)*MM,45,places=4)
            self.assertEqual(str(reader.pages[0]['/Resources']['/ColorSpace']['/EZCut'][1]),'/CutContour')
            self.assertEqual(reader.root_object['/OCProperties']['/OCGs'][0].get_object()['/Name'],'CutContour')
            form=next(iter(reader.pages[0]['/Resources']['/XObject'].values())).get_object()
            self.assertEqual(form['/Subtype'],'/Form')
            self.assertIn(b'1 0 0 0 k',form.get_data())
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(raw) as rendered:
                page=rendered[0]; bitmap=page.render(scale=2); image=bitmap.to_pil().convert('RGB')
                # At x=25mm, y=15mm the rotated cyan panel must still be visible.
                pixel=image.getpixel((round(25/MM*2),round(15/MM*2)))
                self.assertLess(pixel[0],100); self.assertGreater(pixel[1],120)
                bitmap.close(); page.close()
            svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 90"/>'
            package,manifest=make_package(job,result,'b'*32,None,svg,docs,output_check(job,directory))
            with ZipFile(io.BytesIO(package)) as archive:
                self.assertIn('sheet-001.pdf',archive.namelist());self.assertIn('sheet-002.pdf',archive.namelist())
                self.assertNotIn('artwork.svg',archive.namelist())
                self.assertIn('ORDER-12',archive.read('piece-checklist.csv').decode('utf-8-sig'))
            self.assertEqual([p['sheet'] for p in manifest['pieces']],[1,2])

    def test_bleed_matrix_offsets_a_square_by_one_sixteenth(self):
        matrix = bleed_artwork_matrix((0, 0, 72, 72), 25.4 / 16)
        self.assertAlmostEqual(matrix[0], 1.125, places=6)
        self.assertAlmostEqual(matrix[3], 1.125, places=6)
        self.assertAlmostEqual(matrix[4], -4.5, places=6)
        self.assertAlmostEqual(matrix[5], -4.5, places=6)
        self.assertIsNone(bleed_artwork_matrix((0, 0, 72, 72), 0))
        eighth = bleed_artwork_matrix((0, 0, 72, 72), 25.4 / 8)
        self.assertAlmostEqual(eighth[0], (72 + 2 * (25.4 / 8) / MM) / 72, places=6)

    def test_auto_bleed_rejects_old_layout_and_nests_expanded_artwork(self):
        from engine import solve, validate_result
        with tempfile.TemporaryDirectory() as directory:
            parsed = import_to_store(square_pdf_fixture(), directory, 0)
            job = document_job(parsed)
            job['settings'].update(width=100, gap=1, margin=2, rotations=[0])
            docs = load_documents(job, directory)
            original = copy.deepcopy(job['parts'])
            old = {'width':100, 'usedLength':40, 'placements':[
                {'id':job['parts'][0]['id'], 'x':10, 'y':10, 'rotation':0},
                {'id':job['parts'][1]['id'], 'x':31.02, 'y':10, 'rotation':0}]}
            validate_result(job, old)
            export_pdf(job, old, docs)
            # This is the release-time setting change that previously corrupted
            # neighboring print areas while all original cut checks still passed.
            job['settings']['autoBleedMm'] = 3.175
            with self.assertRaisesRegex(ValueError, 'Auto bleed needs more space'):
                export_pdf(job, old, docs)
            prepare_nesting_geometry(job, docs)
            for before, after in zip(original, job['parts']):
                self.assertEqual(before, {k:v for k,v in after.items() if k != 'nestingPoints'})
            with self.assertRaisesRegex(ValueError, 'overlap/spacing'):
                validate_result(job, old)
            nested = solve(job)
            shapes = validate_result(job, nested)
            self.assertGreaterEqual(shapes[0].distance(shapes[1]), .999)
            raw = export_pdf(job, nested, docs)
            _, exported = read_document(raw)
            # The original two 20 mm cuts survive unchanged despite larger paint.
            self.assertEqual(len(exported['pieces']), 2)
            for piece in exported['pieces']:
                bounds = cut_bounds(piece)
                self.assertAlmostEqual((bounds[2]-bounds[0])*MM, 20, places=5)
                self.assertAlmostEqual((bounds[3]-bounds[1])*MM, 20, places=5)

    def test_auto_bleed_respects_sheet_edges_rotations_and_existing_bleed(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed = import_to_store(square_pdf_fixture(), directory, 1)
            job = document_job(parsed)
            job['settings'].update(autoBleedMm=3.175, margin=0, gap=1)
            docs = load_documents(job, directory)
            prepare_nesting_geometry(job, docs)
            # Existing 1 mm bleed is enlarged by the same nonuniform matrix;
            # reserving only 3.175 mm around the old 22 mm outline is insufficient.
            xs = [p[0] for p in job['parts'][0]['nestingPoints']]
            self.assertAlmostEqual(max(xs)-min(xs), 22*(1+2*3.175/20), places=5)
            ident = job['parts'][0]['id']
            edge = {'width':100, 'usedLength':40, 'placements':[
                {'id':ident, 'x':0, 'y':10, 'rotation':0}]}
            with self.assertRaisesRegex(ValueError, 'Auto bleed needs more space'):
                export_pdf(job, edge, docs)
            valid = {'width':100, 'usedLength':100,
                     'sheets':[{'index':0,'offset':0,'usedLength':50}, {'index':1,'offset':50,'usedLength':50}],
                     'placements':[{'id':ident,'x':40,'y':10,'rotation':90,'sheet':0},
                                   {'id':ident,'x':40,'y':60,'rotation':90,'sheet':1}]}
            self.assertEqual(len(PdfReader(io.BytesIO(export_pdf(job, valid, docs))).pages), 2)
            valid['placements'][1]['y'] = 51
            with self.assertRaisesRegex(ValueError, 'Auto bleed needs more space'):
                export_pdf(job, valid, docs)

    def test_envelopes_are_recomputed_and_cleared_when_auto_bleed_is_off(self):
        job = {'settings':{'autoBleedMm':1}, 'parts':[{'points':[[0,0],[20,0],[20,20],[0,20]],
                'nestingPoints':[[0,0],[1,0],[0,1]]}]}
        prepare_nesting_geometry(job)
        self.assertLess(min(p[0] for p in job['parts'][0]['nestingPoints']), 0)
        job['settings']['autoBleedMm'] = 0
        prepare_nesting_geometry(job)
        self.assertNotIn('nestingPoints', job['parts'][0])

    def test_auto_bleed_scales_art_and_leaves_cut_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed = import_to_store(pdf_fixture(), directory, 0)
            job = document_job(parsed)
            docs = load_documents(job, directory)
            part = job['parts'][0]
            result = {'width': 200, 'usedLength': 160, 'placements': [{'id': part['id'], 'x': 20, 'y': 20, 'rotation': 0}]}
            plain = export_pdf(job, result, docs)
            job['settings']['autoBleedMm'] = 25.4 / 16
            bled = export_pdf(job, result, docs)
            plain_stream = PdfReader(io.BytesIO(plain)).pages[0].get_contents().get_data()
            bled_stream = PdfReader(io.BytesIO(bled)).pages[0].get_contents().get_data()
            piece = docs[part['documentId']][1]['pieces'][0]
            matrix = bleed_artwork_matrix(cut_bounds(piece), 25.4 / 16)
            scale = f'{matrix[0]:.9f}'.encode()
            self.assertIn(b'20 20 m', plain_stream)
            self.assertIn(b'20 20 m', bled_stream)
            self.assertIn(scale, bled_stream)
            self.assertNotIn(scale, plain_stream)
            self.assertEqual(plain_stream.split(b'0.25 w\n', 1)[1], bled_stream.split(b'0.25 w\n', 1)[1])
            self.assertNotIn(b'LNRegmark', plain_stream)
            self.assertNotIn(b'LNRegmark', bled_stream)
            self.assertNotIn(b'barcode', bled.lower())
            job['settings']['drawRegmarks'] = True
            job['settings']['markMargin'] = 8
            marked = export_pdf(job, result, docs)
            marked_stream = PdfReader(io.BytesIO(marked)).pages[0].get_contents().get_data()
            self.assertIn(b'LNRegmark', marked)
            self.assertIn(b'/EZReg', marked_stream)
            self.assertIn(b'20 20 m', marked_stream)
            self.assertNotIn(b'barcode', marked.lower())


if __name__=='__main__':unittest.main()
