import io
import unittest
from unittest.mock import patch

import numpy as np
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject, DictionaryObject, NameObject
from shapely.geometry import box

from artwork_bounds import preserve_artwork
from pdf_io import export_pdf, read_document
from pdf_piece_objects import analyze_objects, select_objects
from test_pdf_production import pdf_fixture
from test_pdf_export_forms import rendered


def page_with_content(content):
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    page[NameObject('/Resources')] = DictionaryObject()
    stream = DecodedStreamObject(); stream.set_data(content)
    page[NameObject('/Contents')] = writer._add_object(stream)
    raw = io.BytesIO(); writer.write(raw)
    reader = PdfReader(io.BytesIO(raw.getvalue()))
    return reader, reader.pages[0]


class PieceObjectsTests(unittest.TestCase):
    def test_only_whole_objects_are_selected(self):
        reader, page = page_with_content(b'1 0 0 rg 10 10 20 20 re f 0 0 1 rg 100 10 20 20 re f')
        before = page.get_contents().get_data()
        analyzed = analyze_objects(page, reader)
        content, counts = select_objects(analyzed, box(0, 0, 50, 50))
        self.assertEqual(counts, {'sourceObjects': 2, 'pieceObjects': 1})
        stream = ContentStream(None, None); stream.set_data(content)
        self.assertEqual(sum(op == b'f' for _, op in stream.operations), 1)
        self.assertEqual(page.get_contents().get_data(), before)
        self.assertIsNone(select_objects(analyzed, box(0, 0, 15, 50)), 'Do not slice crossing artwork')

    def test_existing_design_clip_is_retained(self):
        reader, page = page_with_content(b'q 10 10 20 20 re W n 1 0 0 rg 0 0 200 200 re f Q 100 10 20 20 re f')
        analyzed = analyze_objects(page, reader)
        content, counts = select_objects(analyzed, box(0, 0, 50, 50))
        self.assertEqual(counts['pieceObjects'], 1)
        stream = ContentStream(None, None); stream.set_data(content)
        self.assertEqual(sum(op == b'W' for _, op in stream.operations), 1)

    def test_clipping_text_and_oversized_stream_use_existing_export(self):
        reader, page = page_with_content(b'BT 7 Tr ET')
        self.assertIsNone(analyze_objects(page, reader))
        with patch('pdf_piece_objects.MAX_SOURCE_BYTES', 1):
            self.assertIsNone(analyze_objects(page, reader))

    def test_transformed_objects_keep_their_coordinates(self):
        reader, page = page_with_content(b'q 0 1 -1 0 80 20 cm 0 0 20 30 re f Q 100 100 10 10 re f')
        analyzed = analyze_objects(page, reader)
        content, counts = select_objects(analyzed, box(40, 10, 90, 50))
        self.assertEqual(counts['pieceObjects'], 1)
        self.assertIn(b'0 1 -1 0 80 20 cm', content)

    def test_removed_text_keeps_font_state_needed_by_next_run(self):
        reader, page = page_with_content(b'BT /F 12 Tf 20 20 Td (Outside) Tj ET BT 150 20 Td (Inside) Tj ET')
        page['/Resources'][NameObject('/Font')] = DictionaryObject({NameObject('/F'):
            DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'),
                              NameObject('/BaseFont'):NameObject('/Helvetica')})})
        analyzed = analyze_objects(page, reader)
        selected, counts = select_objects(analyzed, box(140, 0, 250, 80))
        self.assertEqual(counts['pieceObjects'], 1)
        outputs = []
        for content in (b'q 140 0 110 80 re W n '+page.get_contents().get_data()+b' Q', selected):
            writer=PdfWriter(); target=writer.add_page(page)
            stream=DecodedStreamObject();stream.set_data(content)
            target[NameObject('/Contents')]=writer._add_object(stream)
            data=io.BytesIO();writer.write(data);outputs.append(rendered(data.getvalue()))
        self.assertTrue(np.array_equal(*outputs))
        self.assertIn(b'/F 12 Tf', selected)
        self.assertNotIn(b'Outside', selected)

    def test_full_export_retains_bleed_cuts_pixels_and_original(self):
        original = pdf_fixture()
        clean, meta = read_document(original)
        meta = preserve_artwork(clean, meta)
        job = {'parts': [{'id': p['id'], 'pdfPieceId': p['id'], 'documentId': 'doc'} for p in meta['pieces']]}
        result = {'width': 150, 'usedLength': 100, 'placements': [
            {'id': p['id'], 'x': 15+i*70, 'y': 15, 'rotation': 0} for i,p in enumerate(meta['pieces'])]}
        documents = {'doc': (clean, meta)}
        with patch('pdf_piece_objects.analyze_objects', return_value=None):
            reference = export_pdf(job, result, documents)
        actual = export_pdf(job, result, documents)
        self.assertTrue(np.array_equal(rendered(reference), rendered(actual)))
        _, before = read_document(reference); _, after = read_document(actual)
        self.assertEqual([p['cutPaths'] for p in before['pieces']], [p['cutPaths'] for p in after['pieces']])
        page = PdfReader(io.BytesIO(actual)).pages[0]
        self.assertNotIn(b'W', [op for _,op in ContentStream(page.get_contents(), page.pdf).operations])
        for ref in page['/Resources']['/XObject'].values():
            ops = ContentStream(ref.get_object(), page.pdf).operations
            self.assertEqual(sum(op in (b'f', b'f*') for _,op in ops), 1)
        self.assertEqual(clean, documents['doc'][0])


if __name__ == '__main__':
    unittest.main()
