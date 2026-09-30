import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, DecodedStreamObject
from pdf_io import read_document, import_to_store, export_pdf, load_documents, output_check, MM
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


def document_job(parsed):
    return {'materialId':'test','materialName':'Test stock','settings':{'width':100,'maxLength':None,'gap':2,'margin':2,'seconds':1,'rotations':[0,90,180,270]},
            'parts':[{**p,'id':'job:'+p['id'],'sourceJobId':'job','perSet':1} for p in parsed['parts']],
            'productionJobs':[{'id':'job','code':'A','name':'Kit.pdf','revision':'test','sets':1,'materialId':'test','partIds':['job:'+p['id'] for p in parsed['parts']],'customer':'Customer One','order':'ORDER-12','kit':'MX'}],
            'documentSources':{'job':{'documentId':parsed['documentId'],'reviewed':True,'bleedMm':parsed['bleedMm']}},
            'outputProfile':{'name':'PDF','rip':'Test','format':'pdf','acceptedFormats':['pdf','ai'],'colorMode':'preserve','iccProfile':'','bleedMm':0,'cutSpot':'CutContour','cutLayer':'CutContour','registrationOwner':'rip','finishingSoftware':'','mediaOwner':'rip','jobLogOwner':'rip'}}


class PDFProductionTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
