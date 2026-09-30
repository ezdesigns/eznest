"""Synthetic production contracts; no claim of physical RIP/cutter validation."""
import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject, DecodedStreamObject
from cut_mapping import defaults, validate, classify
from pdf_io import read_document, import_to_store, load_documents, export_pdf, output_check, MM
from production import make_package
from test_pdf_production import document_job, pdf_fixture


def mixed_fixture(forms=False, layers=True, generic=True, extra='', registration=True):
    writer=PdfWriter();page=writer.add_blank_page(width=400,height=300)
    tint=DictionaryObject({NameObject('/FunctionType'):NumberObject(2),NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)]),NameObject('/C0'):ArrayObject([NumberObject(0)]*4),NameObject('/C1'):ArrayObject([NumberObject(0),NumberObject(1),NumberObject(0),NumberObject(0)]),NameObject('/N'):NumberObject(1)})
    spaces=DictionaryObject()
    for key,name in [('Thru','CutContour' if generic else 'CutContour_Thru-cut'),('Kiss','CutContour' if generic else 'CutContour_Kiss-cut'),('Brand','BrandInk')]:
        spaces[NameObject('/'+key)]=ArrayObject([NameObject('/Separation'),NameObject('/'+name),NameObject('/DeviceCMYK'),writer._add_object(tint)])
    props=DictionaryObject()
    for key,name in [('Outer','LNThru-cut'),('Inner','LNKiss-cut'),('Marks','LNRegmark')]:
        props[NameObject('/'+key)]=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject(name)}))
    resources=DictionaryObject({NameObject('/ColorSpace'):spaces,NameObject('/Properties'):props})
    def layer(key,body):return f'/OC /{key} BDC {body} EMC' if layers else body
    first='q 1 0 0 0 k 15 15 110 80 re f /Brand cs 1 scn 40 35 5 5 re f Q '
    first+=layer('Outer','q /Thru CS 1 SCN 0.25 w 20 20 100 70 re S Q')+' '
    first+=layer('Inner','q /Kiss CS 1 SCN 0.25 w 40 40 20 15 re S 75 40 m 80 45 90 45 100 40 c S Q')+' '
    if registration:first+='/OC /Marks BDC q 0 g 25 25 4 4 re f Q EMC '
    first+=extra
    stream=DecodedStreamObject()
    if forms:
        form=DecodedStreamObject();form.set_data(first.encode());form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(n) for n in [0,0,150,120]]),NameObject('/Resources'):resources})
        inner=writer._add_object(form)
        wrapper=DecodedStreamObject();wrapper.set_data(b'/InnerForm Do');wrapper.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):form['/BBox'],NameObject('/Resources'):DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/InnerForm'):inner})})})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Panel'):writer._add_object(wrapper)})})
        stream.set_data(('q 1 0 0 1 10 10 cm /Panel Do Q q 0 1 -1 0 320 100 cm /Panel Do Q').encode())
    else:
        page[NameObject('/Resources')]=resources
        stream.set_data((first+' q 1 0 0 1 170 10 cm '+first+' Q').encode())
    page[NameObject('/Contents')]=writer._add_object(stream)
    groups=ArrayObject(list(props.values()))
    writer.root_object[NameObject('/OCProperties')]=DictionaryObject({NameObject('/OCGs'):groups,NameObject('/D'):DictionaryObject({NameObject('/ON'):groups})})
    buffer=io.BytesIO();writer.write(buffer);return buffer.getvalue()


class MixedCutsTests(unittest.TestCase):
    def test_outer_boundary_owns_open_and_closed_interior_cuts(self):
        clean,meta=read_document(mixed_fixture(),cut_mapping=defaults())
        self.assertEqual(len(meta['pieces']),2)
        self.assertEqual(meta['registrationPaintRemoved'],2)
        for piece in meta['pieces']:
            self.assertEqual(piece['cutCounts'],{'thru':1,'kiss':2,'contour':0})
            self.assertEqual(len(piece['cutPaths']),3)
            self.assertEqual([p['closed'] for p in piece['cutPaths']],[True,True,False])
            self.assertEqual(piece['cutPaths'][1]['sourceLayers'],['LNKiss-cut'])
            self.assertEqual(piece['cutPaths'][1]['sourceSpot'],'CutContour')
            self.assertEqual(piece['cutPaths'][2]['commands'][-1][0],'c')
        reader=PdfReader(io.BytesIO(clean))
        self.assertNotIn('/OCProperties',reader.root_object)
        operations=reader.pages[0].get_contents().operations
        self.assertFalse(any(op==b'S' for _,op in operations))
        self.assertTrue(any(op==b'scn' for _,op in operations)) # Brand spot preserved.

    def test_layer_only_and_spot_only_recognition_and_nested_forms(self):
        for forms in (False,True):
            for layers,generic in [(True,True),(False,False)]:
                with self.subTest(forms=forms,layers=layers):
                    _,meta=read_document(mixed_fixture(forms,layers,generic,registration=False),cut_mapping=defaults())
                    self.assertEqual(len(meta['pieces']),2)
                    self.assertTrue(all(p['cutCounts']['kiss']==2 for p in meta['pieces']))
        raw=mixed_fixture()
        writer=PdfWriter(clone_from=io.BytesIO(raw));content=writer.pages[0].get_contents()
        content.set_data(re.sub(rb'/(Thru|Kiss) CS\s+1 SCN',b'1 0 1 RG',content.get_data()))
        writer.pages[0][NameObject('/Contents')]=writer._add_object(content)
        out=io.BytesIO();writer.write(out)
        _,meta=read_document(out.getvalue(),cut_mapping=defaults())
        self.assertEqual(meta['pieces'][0]['cutCounts']['thru'],1)
        self.assertIsNone(meta['pieces'][0]['cutPaths'][0]['sourceSpot'])

    def test_registration_forms_images_and_text_do_not_move_print_text(self):
        writer=PdfWriter(clone_from=io.BytesIO(mixed_fixture(registration=False)));page=writer.pages[0];resources=page['/Resources']
        mark_layer=resources['/Properties']['/Marks']
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        resources[NameObject('/Font')]=DictionaryObject({NameObject('/F1'):writer._add_object(font)})
        image=DecodedStreamObject();image.set_data(bytes([0,0,0]));image.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),NameObject('/Width'):NumberObject(1),NameObject('/Height'):NumberObject(1),NameObject('/BitsPerComponent'):NumberObject(8),NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/OC'):mark_layer.indirect_reference})
        form=DecodedStreamObject();form.set_data(b'0 g 0 0 5 5 re f');form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(n) for n in [0,0,5,5]]),NameObject('/OC'):mark_layer.indirect_reference})
        resources[NameObject('/XObject')]=DictionaryObject({NameObject('/OldMark'):writer._add_object(image),NameObject('/MarkForm'):writer._add_object(form)})
        stream=DecodedStreamObject();stream.set_data(page.get_contents().get_data()+b'\nq 10 0 0 10 30 30 cm /OldMark Do Q q 1 0 0 1 35 35 cm /MarkForm Do Q BT /F1 10 Tf 25 70 Td /OC /Marks BDC (XX) Tj EMC (OK) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream);out=io.BytesIO();writer.write(out)
        clean,meta=read_document(out.getvalue(),cut_mapping=defaults())
        self.assertEqual(meta['registrationPaintRemoved'],3)
        operations=PdfReader(io.BytesIO(clean)).pages[0].get_contents().operations
        self.assertFalse(any(op==b'Do' for _,op in operations))
        text_index=next(i for i,(args,op) in enumerate(operations) if op==b'Tj' and str(args[0])=='XX')
        self.assertEqual(operations[text_index-1],([3],b'Tr'))
        self.assertEqual(operations[text_index+1],([0],b'Tr'))
        self.assertEqual(operations[text_index+3][1],b'Tj')

    def test_device_n_dashed_and_clipped_cuts_reject(self):
        for extra in ['[2 2] 0 d','0 0 60 60 re W n']:
            with self.subTest(extra=extra),self.assertRaisesRegex(ValueError,'Dashed|clipped'):
                read_document(mixed_fixture(extra='q '+extra+' /OC /Inner BDC /Kiss CS 1 SCN 75 45 m 90 50 l S EMC Q'),cut_mapping=defaults())
        writer=PdfWriter(clone_from=io.BytesIO(mixed_fixture(generic=False)));space=writer.pages[0]['/Resources']['/ColorSpace']['/Thru']
        space[0]=NameObject('/DeviceN');space[1]=ArrayObject([NameObject('/CutContour_Thru-cut')]);out=io.BytesIO();writer.write(out)
        with self.assertRaisesRegex(ValueError,'DeviceN'):read_document(out.getvalue(),cut_mapping=defaults())

    def test_ambiguous_generic_and_conflicting_rules_reject(self):
        with self.assertRaisesRegex(ValueError,'Unspecified'):read_document(pdf_fixture(),cut_mapping=defaults())
        mapping=defaults();mapping['genericOperation']='kiss'
        self.assertEqual(read_document(pdf_fixture(),cut_mapping=mapping)[1]['pieces'][0]['cutCounts']['kiss'],1)
        with self.assertRaisesRegex(ValueError,'Conflicting'):classify(defaults(),'CutContour_Thru-cut',['LNKiss-cut'])
        with self.assertRaisesRegex(ValueError,'Unmapped'):classify(defaults(),'CutContour_Unknown',[])
        mapping['rules']+=[{'source':'spot','match':'prefix','name':'CutContour','operation':'thru'}]
        self.assertEqual(classify(validate(mapping),'CutContour_Kiss-cut',[]),'kiss')
        with self.assertRaisesRegex(ValueError,'Conflicting'):classify(validate(mapping),'CutContour_Unknown',['LNKiss-cut'])

    def test_orphans_duplicates_overlap_and_filled_cuts_reject(self):
        cases=[('150 140 m 160 140 l S','unique piece owner'),('40 40 20 15 re S','Duplicate'),('75 40 m 80 45 90 45 100 40 c S','Duplicate'),('100 80 50 40 re S','overlap'),('45 45 3 3 re f','filled')]
        for body,message in cases:
            with self.subTest(body=body):
                extra='/OC /Inner BDC q /Kiss CS 1 SCN '+body+' Q EMC'
                with self.assertRaisesRegex(ValueError,message):read_document(mixed_fixture(extra=extra),cut_mapping=defaults())

    def test_rotated_copies_multisheet_preserve_every_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed=import_to_store(mixed_fixture(),directory,1,cut_mapping=defaults());job=document_job(parsed)
            job['outputProfile']['cutMapping']=defaults();job['productionJobs'][0]['sets']=2
            for p in job['parts']:p['quantity']=2
            docs=load_documents(job,directory)
            result={'width':100,'usedLength':90,'sheets':[{'index':0,'offset':0,'usedLength':45},{'index':1,'offset':45,'usedLength':45}],
                    'placements':[{'id':job['parts'][i]['id'],'x':35 if i==0 else 55,'y':3+45*sheet,'rotation':90 if i==0 else 0,'sheet':sheet} for sheet in range(2) for i in range(2)]}
            raw=export_pdf(job,result,docs,cut_mapping=defaults())
            (Path(directory)/'out.pdf').write_bytes(raw)
            reader=PdfReader(io.BytesIO(raw));self.assertEqual(len(reader.pages),2)
            self.assertEqual({g.get_object()['/Name'] for g in reader.root_object['/OCProperties']['/OCGs']},{'Thru-cut','Kiss-cut'})
            _,meta=read_document(raw,cut_mapping=defaults())
            self.assertEqual(len(meta['pieces']),4)
            self.assertEqual(meta['registrationPaintRemoved'],0)
            self.assertTrue(all(p['cutCounts']=={'thru':1,'kiss':2,'contour':0} for p in meta['pieces']))
            # Rotation preserves distances between an outer corner and interior cut.
            import math
            source=docs[parsed['documentId']][1]['pieces'][0]['cutPaths']
            for piece in meta['pieces']:
                cuts=piece['cutPaths']
                self.assertAlmostEqual(math.dist(cuts[0]['pdfPoints'][0],cuts[1]['pdfPoints'][0]),math.dist(source[0]['pdfPoints'][0],source[1]['pdfPoints'][0]),places=5)
            package,manifest=make_package(job,result,'c'*32,None,'<svg xmlns="http://www.w3.org/2000/svg"/>',docs,output_check(job,directory))
            self.assertEqual(manifest['cutSummary'],{'thru':4,'kiss':8,'contour':0})
            with ZipFile(io.BytesIO(package)) as z:
                self.assertIn('thruPaths,kissPaths,genericPaths',z.read('piece-checklist.csv').decode('utf-8-sig'))
                self.assertIn('Kiss-cut',z.read('sorting-guide.html').decode())
                self.assertIn('kiss: 8 paths; spot CutContour_Kiss-cut; layer Kiss-cut',z.read('READ ME.txt').decode())

    def test_custom_output_names_and_old_store_require_reimport(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed=import_to_store(mixed_fixture(),directory,cut_mapping=defaults());job=document_job(parsed);docs=load_documents(job,directory)
            custom=defaults();custom['outputs']['thru'].update(spot='Shop Through',layer='Through',toolHint='SP9 (confirm locally)')
            custom['outputs']['kiss'].update(spot='Shop Kiss',layer='Kiss')
            result={'width':100,'usedLength':50,'placements':[{'id':job['parts'][0]['id'],'x':5,'y':5,'rotation':0}]}
            raw=export_pdf(job,result,docs,cut_mapping=custom);page=PdfReader(io.BytesIO(raw)).pages[0]
            self.assertEqual({str(c[1]) for c in page['/Resources']['/ColorSpace'].values()},{'/Shop Through','/Shop Kiss'})
            self.assertNotIn(b'SP9',raw)
            job['outputProfile']['registrationOwner']='none';self.assertFalse(output_check(job,directory)['ready'])
            path=Path(directory)/(parsed['documentId']+'.json');meta=json.loads(path.read_text());meta.pop('modelVersion');path.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError,'Re-add'):load_documents(job,directory)

    def test_cut_mapping_validation_and_shared_defaults(self):
        fixture=json.loads((Path(__file__).parent/'cut-mapping-defaults.json').read_text())
        self.assertEqual(validate(defaults()),validate(fixture))
        for changed in ('spot','layer'):
            mapping=defaults();mapping['outputs']['kiss'][changed]=mapping['outputs']['thru'][changed]
            with self.assertRaisesRegex(ValueError,'different'):validate(mapping)
        mapping=defaults();mapping['rules'].append({**mapping['rules'][0],'operation':'kiss'})
        with self.assertRaisesRegex(ValueError,'different'):validate(mapping)


if __name__=='__main__':unittest.main()
