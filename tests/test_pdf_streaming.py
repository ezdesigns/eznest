import opt_out
import io
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter, get_configuration
from pypdf.generic import ContentStream, DecodedStreamObject, NameObject
from pypdf.errors import LimitReachedError

from pdf_streaming import operations, OperationOutput, print_pdf_context
from pdf_io import read_document
from test_pdf_production import pdf_fixture


class PdfStreamingTests(unittest.TestCase):
    def test_tokenizer_matches_pdf_parser_including_strings_comments_and_inline_images(self):
        cases = [
            b'q\n1 0 0 1 0 0 cm\n10.5 -2 m\n.5 +2 l\nQ\n',
            b'% comment\r1 2 m% comment\n3 4 l S',
            b'BT /F1 12 Tf (a \\( nested\\) ) Tj [(abc) 10 <4142>] TJ ET',
            b'/Artifact << /Name (a) /Values [1 2] >> BDC 1 2 3 4 re f EMC',
            b'q BI /W 1 /H 1 /BPC 8 /CS /RGB ID \xff\x00\x00 EI Q',
            b'1 2 m\r3 4 l\rS',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                source=DecodedStreamObject();source.set_data(raw)
                expected=ContentStream(source,None).operations
                content=ContentStream(source,None)
                actual=[(args,op) for args,op,_ in operations(content)]
                self.assertEqual(actual,expected)
                self.assertEqual(content._operations,[])  # No whole-page operation cache.

    def test_unchanged_operators_keep_source_syntax_and_cut_removal_keeps_state(self):
        raw=b'q\n1.000 0 0 1 0 0 cm\n10 20 m\n30 40 l\nS\nQ\n'
        source=DecodedStreamObject();source.set_data(raw)
        result=OperationOutput(None)
        for args,op,syntax in operations(ContentStream(source,None)):
            result.original=(args,op,syntax)
            if op==b'S':
                result.finish_path(remove=True)
                result.append(([],b'n'))
            else:
                result.append((args,op))
        self.assertEqual(result.get_data(),b'q\n1.000 0 0 1 0 0 cm\nn\nQ\n')

    def test_real_decompression_over_75mb_imports_without_disabling_memory_guards(self):
        reader=PdfReader(io.BytesIO(pdf_fixture()))
        writer=PdfWriter();page=writer.add_page(reader.pages[0])
        # Large synthetic comment exercises the exact decoding boundary without
        # keeping customer artwork or millions of Python drawing objects in tests.
        stream=DecodedStreamObject()
        stream.set_data(b'%'+b'x'*75_000_001+b'\n'+page.get_contents().get_data())
        page[NameObject('/Contents')]=writer._add_object(stream.flate_encode())
        out=io.BytesIO();writer.write(out)
        before=get_configuration()
        with self.assertRaises(LimitReachedError):
            PdfReader(io.BytesIO(out.getvalue())).pages[0].get_contents()
        with patch('pdf_streaming.available_memory',return_value=4_000_000_000):
            _,meta=read_document(out.getvalue())
        self.assertEqual(len(meta['pieces']),2)
        self.assertEqual(get_configuration(),before)

    def test_memory_budget_is_finite_and_context_is_restored_after_error(self):
        before=get_configuration()
        @print_pdf_context
        def check():
            self.assertEqual(get_configuration().zlib_maximum_output_length,100_000_000)
            raise ValueError('test')
        with patch('pdf_streaming.available_memory',return_value=1_200_000_000):
            with self.assertRaisesRegex(ValueError,'test'):check()
        self.assertEqual(get_configuration(),before)

    def test_interior_fill_shortcut_requires_all_control_points_inside_cut(self):
        import pypdfium2 as pdfium
        import artwork_bounds
        from shapely.geometry import box
        for control, paint, skipped in ((20, b'f', True), (120, b'f', False), (20, b'S', False)):
            with self.subTest(control=control,paint=paint):
                writer=PdfWriter();page=writer.add_blank_page(200,200)
                stream=DecodedStreamObject()
                stream.set_data(b'q 1 0 0 1 5 5 cm 10 10 m '+str(control).encode()+b' 50 60 50 70 10 c h '+paint+b' Q')
                page[NameObject('/Contents')]=writer._add_object(stream)
                raw=io.BytesIO();writer.write(raw)
                with pdfium.PdfDocument(raw.getvalue()) as document:
                    page=document[0]
                    try:
                        with patch.object(artwork_bounds,'path_parts',wraps=artwork_bounds.path_parts) as flatten:
                            envelopes=artwork_bounds.paint_envelopes(page,cuts=[box(0,0,100,100)])
                        self.assertEqual(flatten.call_count==0,skipped)
                        self.assertEqual(len(envelopes)==0,skipped)
                    finally:page.close()

    def test_clips_with_the_same_bounds_keep_their_different_shapes(self):
        import pypdfium2 as pdfium
        from artwork_bounds import paint_envelopes
        from shapely.geometry import Point
        writer=PdfWriter();page=writer.add_blank_page(120,120)
        stream=DecodedStreamObject()
        stream.set_data(b'q 0 0 m 100 0 l 0 100 l h W n 0 0 100 100 re f Q '
                        b'q 100 0 m 100 100 l 0 100 l h W n 0 0 100 100 re f Q')
        page[NameObject('/Contents')]=writer._add_object(stream)
        raw=io.BytesIO();writer.write(raw)
        with pdfium.PdfDocument(raw.getvalue()) as document:
            page=document[0]
            try:envelopes=paint_envelopes(page)
            finally:page.close()
        self.assertEqual(len(envelopes),2)
        self.assertTrue(envelopes[0].covers(Point(10,10)))
        self.assertFalse(envelopes[0].covers(Point(90,90)))
        self.assertFalse(envelopes[1].covers(Point(10,10)))
        self.assertTrue(envelopes[1].covers(Point(90,90)))

    def test_large_page_is_shared_across_pieces_with_identical_rendered_output(self):
        from pdf_io import export_pdf, MM
        from test_pdf_export_forms import rendered
        import numpy as np
        clean,meta=read_document(pdf_fixture())
        job={'parts':[{'id':p['id'],'pdfPieceId':p['id'],'documentId':'test'} for p in meta['pieces']]}
        result={'width':400*MM,'usedLength':300*MM,'placements':[
            {'id':p['id'],'x':p['anchor'][0]*MM,'y':(300-p['anchor'][1])*MM,'rotation':0}
            for p in meta['pieces']]}
        documents={'test':(clean,meta)}
        baseline=export_pdf(job,result,documents)
        with patch('pdf_export_forms.MAX_PRUNED_PAGE_BYTES',0):
            shared=export_pdf(job,result,documents)
        self.assertTrue(np.array_equal(rendered(baseline),rendered(shared)))
        reader=PdfReader(io.BytesIO(shared))
        objects=reader.pages[0]['/Resources']['/XObject']
        self.assertEqual(len(objects),2)
        self.assertEqual(len({objects.raw_get(name).idnum for name in objects}),1)
