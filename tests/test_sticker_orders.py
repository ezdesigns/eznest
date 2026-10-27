"""Synthetic large-order, lossless print-copy and explicit cut-review checks."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, DecodedStreamObject
from cut_mapping import defaults
from engine import validate_job, validate_result
from nesting import run
from pdf_compact import compact_pdf
from pdf_io import read_document, import_to_store, export_pdf, CutReviewRequired, MM


def outline_fixture(extra=''):
    writer = PdfWriter(); page = writer.add_blank_page(160, 80)
    page[NameObject('/Resources')] = DictionaryObject()
    stream = DecodedStreamObject()
    stream.set_data(('0 0.5 0.7 rg 8 8 54 54 re f 88 8 54 54 re f '
                     '0 G 10 10 50 50 re S 90 10 50 50 re S ' + extra).encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO(); writer.write(out); return out.getvalue()


def pixels(raw):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(raw) as doc:
        page = doc[0]; bitmap = page.render(scale=2)
        try: return bitmap.to_pil().tobytes()
        finally: bitmap.close(); page.close()


class StickerOrderTests(unittest.TestCase):
    def test_continuous_thousand_uses_one_page_and_best_row_orientation(self):
        job={'settings':{'width':1308.1,'sheetLength':5000,'continuous':True,'maxLength':None,
                         'margin':16.51,'gap':3.048,'seconds':1,'rotations':[0,90,180,270]},
             'parts':[{'id':'sticker','points':[[0,0],[51.447,0],[51.447,47.766],[0,47.766]],'quantity':1000}]}
        result=run(job)['result']
        self.assertEqual(len(result['sheets']),1)
        self.assertEqual(result['sheets'][0]['pieces'],1000)
        self.assertLess(result['usedLength'],2220)
        self.assertLess(result['usedLength'],result['layoutComparison']['baselineLengthMm'])
        self.assertEqual(len(validate_result(job,result)),1000)
        bad=copy.deepcopy(result);bad['placements'][1].update(bad['placements'][0])
        with self.assertRaisesRegex(ValueError,'overlap'):validate_result(job,bad)
        job['settings']['rotations']=[0]
        fixed=run(job)['result']
        self.assertTrue(all(p['rotation']==0 for p in fixed['placements']))
        self.assertGreater(fixed['usedLength'],result['usedLength'])
        job['settings']['maxLength']=100
        with self.assertRaises(ValueError):run(job)

    def test_continuous_mixed_shapes_join_without_breaks_or_overlap(self):
        from unittest.mock import patch
        job={'settings':{'width':100,'sheetLength':5000,'continuous':True,'maxLength':None,
                         'margin':3,'gap':2,'seconds':1,'rotations':[0]},
             'parts':[{'id':'triangle','points':[[0,0],[10,0],[0,10]],'quantity':801},
                      {'id':'square','points':[[0,0],[8,0],[8,8],[0,8]],'quantity':20}]}
        with patch('sheets.solve',side_effect=ValueError('Use checked fallback')):
            result=run(job)['result']
        self.assertEqual(len(result['sheets']),1)
        self.assertEqual(Counter(p['id'] for p in result['placements']),{'triangle':801,'square':20})
        self.assertEqual(len(validate_result(job,result)),821)

    def test_continuous_export_has_one_page_and_every_cut(self):
        from test_mixed_cuts import mixed_fixture
        from pdf_io import load_documents
        with tempfile.TemporaryDirectory() as directory:
            parsed=import_to_store(mixed_fixture(),directory,preserve=True)
            job={'settings':{'width':500,'sheetLength':5000,'continuous':True,'maxLength':None,
                             'margin':3,'gap':2,'seconds':1,'rotations':[0,90,180,270]},
                 'parts':[{**p,'quantity':500} for p in parsed['parts']],
                 'documentSources':{parsed['documentId']:parsed}}
            result=run(job)['result']
            ident=parsed['documentId']
            documents={ident:((Path(directory)/(ident+'.pdf')).read_bytes(),
                              json.loads((Path(directory)/(ident+'.json')).read_text()))}
            raw=export_pdf(job,result,documents,cut_mapping=defaults())
            reader=PdfReader(io.BytesIO(raw))
            self.assertEqual(len(reader.pages),1)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.height)*MM,result['usedLength'],places=4)
            self.assertEqual(reader.pages[0].get_contents().get_data().count(b'\nS\n'),3000)

    def test_compaction_preserves_layer_visibility_checks(self):
        from pypdf.generic import ArrayObject
        from test_mixed_cuts import mixed_fixture
        writer=PdfWriter(clone_from=PdfReader(io.BytesIO(mixed_fixture())))
        groups=writer.root_object['/OCProperties']['/OCGs']
        writer.root_object['/OCProperties']['/D'][NameObject('/OFF')]=ArrayObject([groups[0]])
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'hidden.pdf';target=Path(directory)/'print.pdf'
            with source.open('wb') as out:writer.write(out)
            compact_pdf(source,target)
            with self.assertRaisesRegex(ValueError,'Hidden or conditional'):
                read_document(target.read_bytes())

    def test_five_thousand_order_keeps_solver_sections_bounded(self):
        from unittest.mock import patch
        from sheets import split_nest
        job={'settings':{'width':220,'sheetLength':220,'maxLength':None,'margin':3,'gap':1,'seconds':1,'rotations':[0]},
             'parts':[{'id':'sticker','points':[[0,0],[2,0],[2,2],[0,2]],'quantity':5000}]}
        with patch('sheets.solve',side_effect=ValueError('Use the independently validated fallback')):
            result=split_nest(job)
        self.assertEqual(sum(s['pieces'] for s in result['sheets']),5000)
        self.assertEqual(len(result['sheets']),7)
        self.assertEqual(max(s['pieces'] for s in result['sheets']),800)
        self.assertEqual(len(validate_result(job,result)),5000)

    def test_unnamed_cuts_require_bound_review_and_preserve_art_and_bleed(self):
        raw = outline_fixture()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CutReviewRequired) as raised:
                import_to_store(raw, directory, preserve=True)
            self.assertEqual(list(Path(directory).iterdir()), [])
            review = raised.exception.review
            self.assertEqual(review['count'], 2)
            self.assertTrue(review['pages'][0]['image'].startswith('data:image/png;base64,'))
            approval = {key:review[key] for key in ('id', 'sourceHash')}
            approval['operation'] = 'kiss'
            for change in ({'id':'bad'}, {'sourceHash':'bad'}, {'operation':'contour'}, {'extra':True}):
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    read_document(raw, cut_approval={**approval, **change})
            with self.assertRaisesRegex(ValueError, 'does not match'):
                read_document(raw+b'\n', cut_approval=approval)
            mapping=defaults();mapping['genericOperation']='thru'
            with self.assertRaisesRegex(ValueError, 'does not match'):
                read_document(raw, cut_mapping=mapping, cut_approval=approval)
            parsed=import_to_store(raw, directory, preserve=True, cut_approval=approval)
            self.assertEqual(len(parsed['parts']), 2)
            self.assertEqual([p['cutCounts']['kiss'] for p in parsed['parts']], [1, 1])
            meta=json.loads((Path(directory)/(parsed['documentId']+'.json')).read_text())
            self.assertEqual(meta['reviewedCutOutlines'], approval)
            # Artwork is wider than its cut; the existing outside ink remains.
            self.assertGreater(meta['pieces'][0]['bounds'][2]-meta['pieces'][0]['bounds'][0],54)
            clean,_=read_document(raw, cut_approval=approval)
            baseline=outline_fixture()
            writer=PdfWriter(clone_from=PdfReader(io.BytesIO(baseline)))
            stream=DecodedStreamObject();stream.set_data(b'0 0.5 0.7 rg 8 8 54 54 re f 88 8 54 54 re f')
            writer.pages[0][NameObject('/Contents')]=writer._add_object(stream)
            out=io.BytesIO();writer.write(out)
            self.assertEqual(pixels(clean),pixels(out.getvalue()))

    def test_no_guess_for_open_dashed_or_filled_decoration(self):
        for content in ('0 0 10 10 re f','0 0 m 10 10 l S','[2] 0 d 0 0 10 10 re S'):
            writer=PdfWriter();page=writer.add_blank_page(30,30)
            page[NameObject('/Resources')]=DictionaryObject()
            stream=DecodedStreamObject();stream.set_data(content.encode())
            page[NameObject('/Contents')]=writer._add_object(stream)
            out=io.BytesIO();writer.write(out)
            with self.assertRaisesRegex(ValueError,'No cut lines'):
                read_document(out.getvalue())

    def test_transparent_image_boxes_can_overlap_without_merging_stickers(self):
        from artwork_bounds import preserve_artwork
        writer=PdfWriter();page=writer.add_blank_page(160,80)
        mask=DecodedStreamObject()
        # The faint edge has alpha 1, and must survive just like opaque pixels.
        mask.set_data(bytes(255 if 4<=x<16 and 4<=y<16 else 1 if 3<=x<17 and 3<=y<17 else 0 for y in range(20) for x in range(20)))
        mask.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
                     NameObject('/Width'):NumberObject(20),NameObject('/Height'):NumberObject(20),
                     NameObject('/BitsPerComponent'):NumberObject(8),NameObject('/ColorSpace'):NameObject('/DeviceGray')})
        img=DecodedStreamObject();img.set_data(b'\x00\x80\xff'*400)
        img.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
                    NameObject('/Width'):NumberObject(20),NameObject('/Height'):NumberObject(20),
                    NameObject('/BitsPerComponent'):NumberObject(8),NameObject('/ColorSpace'):NameObject('/DeviceRGB'),
                    NameObject('/SMask'):writer._add_object(mask)})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/I'):writer._add_object(img)})})
        stream=DecodedStreamObject();stream.set_data(b'q 60 0 0 60 0 10 cm /I Do Q q 60 0 0 60 55 10 cm /I Do Q 0 G 15 25 30 30 re S 70 25 30 30 re S')
        page[NameObject('/Contents')]=writer._add_object(stream)
        out=io.BytesIO();writer.write(out);raw=out.getvalue()
        with self.assertRaises(CutReviewRequired) as raised:read_document(raw)
        approval={k:raised.exception.review[k] for k in ('id','sourceHash')};approval['operation']='kiss'
        clean,meta=read_document(raw,cut_approval=approval)
        self.assertLess(meta['imagePaintBounds'][0]['paint'][2],60)
        meta=preserve_artwork(clean,meta)
        self.assertEqual(len(meta['pieces']),2)
        ident='a'*64
        job={'parts':[{'id':p['id'],'pdfPieceId':p['id'],'documentId':ident} for p in meta['pieces']]}
        result={'width':160*MM,'usedLength':80*MM,'placements':[
            {'id':p['id'],'x':p['anchor'][0]*MM,'y':(80-p['anchor'][1])*MM,'rotation':0} for p in meta['pieces']]}
        meta=copy.deepcopy(meta)
        for piece in meta['pieces']:piece['cutPaths']=[]  # Compare print paint, without the separate cut overlay.
        exported=export_pdf(job,result,{ident:(clean,meta)},preview=True)
        self.assertEqual(pixels(clean),pixels(exported))

    def test_compaction_retains_pixels_content_and_shares_only_identical_images(self):
        writer=PdfWriter();page=writer.add_blank_page(100,100)
        refs=[]
        for width in (1,1,3):
            img=DecodedStreamObject();img.set_data(b'\xff\x00\x00' if width==1 else b'\xff\x00\x00'*3)
            img.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
                        NameObject('/Width'):NumberObject(width),NameObject('/Height'):NumberObject(1),
                        NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
            refs.append(writer._add_object(img))
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/I'+str(i)):r for i,r in enumerate(refs)})})
        stream=DecodedStreamObject();stream.set_data(b'q 20 0 0 20 10 10 cm /I0 Do Q q 20 0 0 20 40 10 cm /I1 Do Q q 20 0 0 20 70 10 cm /I2 Do Q')
        page[NameObject('/Contents')]=writer._add_object(stream)
        editing=DecodedStreamObject();editing.set_data(b'x'*1_000_000)
        page[NameObject('/PieceInfo')]=DictionaryObject({NameObject('/Private'):writer._add_object(editing)})
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.pdf';out=Path(directory)/'print.pdf';again=Path(directory)/'again.pdf'
            with source.open('wb') as f:writer.write(f)
            raw=source.read_bytes();stats=compact_pdf(source,out);compact_pdf(source,again)
            self.assertEqual(source.read_bytes(),raw)
            self.assertEqual(out.read_bytes(),again.read_bytes()) # Review approval survives a second upload.
            self.assertLess(out.stat().st_size,10_000)
            self.assertEqual(stats['sharedImages'],1)
            actual=PdfReader(out).pages[0]
            self.assertEqual(actual.get_contents().get_data(),page.get_contents().get_data())
            self.assertNotIn('/PieceInfo',actual)
            objects=actual['/Resources']['/XObject']
            self.assertEqual(objects.raw_get('/I0'),objects.raw_get('/I1'))
            self.assertNotEqual(objects.raw_get('/I0'),objects.raw_get('/I2'))
            self.assertEqual(pixels(raw),pixels(out.read_bytes()))
            with self.assertRaises(ValueError):compact_pdf(source,source)
            with self.assertRaises(FileExistsError):compact_pdf(source,out)

    def test_thousand_copies_are_split_and_exactly_accounted_for(self):
        job={'settings':{'width':220,'sheetLength':220,'maxLength':None,'margin':3,'gap':2,'seconds':1,'rotations':[0]},
             'parts':[{'id':'sticker','points':[[0,0],[20,0],[20,20],[0,20]],'quantity':1000}]}
        result=run(job)['result']
        self.assertEqual(Counter(p['id'] for p in result['placements']),{'sticker':1000})
        self.assertGreater(len(result['sheets']),1)
        self.assertTrue(all(s['pieces']<=800 and s['usedLength']<=220 for s in result['sheets']))
        self.assertEqual(len(validate_result(job,result)),1000)
        bad=copy.deepcopy(result);bad['placements'].pop()
        with self.assertRaisesRegex(ValueError,'wrong number'):validate_result(job,bad)
        bad=copy.deepcopy(result);bad['placements'][1].update(bad['placements'][0])
        with self.assertRaisesRegex(ValueError,'overlap'):validate_result(job,bad)
        job['parts'][0]['quantity']=5001
        with self.assertRaises(ValueError):validate_job(job)
        job['parts'][0]['quantity']=1000;job['settings'].pop('sheetLength')
        with self.assertRaises(ValueError):validate_job(job)


if __name__=='__main__':unittest.main()
