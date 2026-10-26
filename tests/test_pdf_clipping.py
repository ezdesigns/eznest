"""Synthetic PDF regressions: compound masks and closed internal slits."""
import io
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from pdf_io import read_document, import_to_store, export_pdf
from test_pdf_production import pdf_fixture


def source(body):
    writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
    stream = DecodedStreamObject()
    stream.set_data(body.encode('ascii'))
    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class PDFClippingTests(unittest.TestCase):
    def test_disjoint_masks_and_implicitly_closed_mask(self):
        for mask in ('10 10 100 100 re 150 10 100 100 re',
                     '10 10 m 110 10 l 110 110 l 10 110 l 150 10 100 100 re'):
            with self.subTest(mask=mask):
                _, meta = read_document(source(mask +
                    ' W n /Contour CS 1 SCN 20 20 80 80 re S 160 20 80 80 re S'))
                self.assertEqual(len(meta['pieces']), 2)
                with self.assertRaisesRegex(ValueError, 'clipped'):
                    read_document(source(mask + ' W n /Contour CS 1 SCN 100 20 60 60 re S'))

    def test_winding_rules_preserve_holes_and_stroked_boundaries(self):
        for inner, rule, hole in (
                ('40 40 20 20 re', 'W', False),
                ('40 40 20 20 re', 'W*', True),
                ('40 40 m 40 60 l 60 60 l 60 40 l h', 'W', True),
                ('40 40 m 40 60 l 60 60 l 60 40 l h', 'W*', True)):
            prefix = '10 10 100 100 re ' + inner + ' ' + rule + ' n /Contour CS 1 SCN '
            with self.subTest(inner=inner, rule=rule):
                # A cut surrounds the hole, but none of its stroke is clipped.
                clean, meta = read_document(source(prefix + '20 20 80 80 re S'))
                self.assertEqual(len(meta['pieces']), 1)
                ops = PdfReader(io.BytesIO(clean)).pages[0].get_contents().operations
                self.assertIn(rule.encode(), [op for _, op in ops])
                for cut in ('45 45 10 10 re S', '30 45 40 10 re S'):
                    if hole:
                        with self.assertRaisesRegex(ValueError, 'clipped'):
                            read_document(source(prefix + cut))
                    else:
                        self.assertEqual(len(read_document(source(prefix + cut))[1]['pieces']), 1)

    def test_intersecting_compound_mask_uses_fill_rule(self):
        for rule in ('W', 'W*'):
            prefix = '10 10 80 80 re 50 10 80 80 re ' + rule + ' n /Contour CS 1 SCN '
            if rule == 'W*':
                with self.assertRaisesRegex(ValueError, 'clipped'):
                    read_document(source(prefix + '60 20 20 60 re S'))
            else:
                self.assertEqual(len(read_document(source(prefix + '60 20 20 60 re S'))[1]['pieces']), 1)

    def test_compound_mask_paint_is_unchanged_and_clip_state_restores(self):
        import pypdfium2 as pdfium

        def pixels(raw):
            with pdfium.PdfDocument(raw) as doc:
                page = doc[0]
                bitmap = page.render(scale=1)
                try:
                    return bitmap.to_pil().tobytes()
                finally:
                    bitmap.close()
                    page.close()

        art = 'q 1 0 0 1 10 20 cm 10 10 100 100 re 40 40 20 20 re W* n 0 0 1 rg 0 0 300 250 re f Q '
        clean, meta = read_document(source(art + '/Contour CS 1 SCN 20 20 150 150 re S'))
        self.assertEqual(pixels(clean), pixels(source(art)))
        self.assertEqual(len(meta['pieces']), 1)
        # The same transformed mask must still reject a cut through its hole.
        with self.assertRaisesRegex(ValueError, 'clipped'):
            read_document(source(art.removesuffix('Q ') + '/Contour CS 1 SCN 30 45 40 10 re S Q'))

    def test_closed_collinear_slit_preserves_commands_and_export(self):
        body = '/Contour CS 1 SCN 20 20 80 80 re S 40 40 m 60 60 l 50 50 l h S'
        _, meta = read_document(source(body))
        self.assertEqual(len(meta['pieces']), 1)
        self.assertEqual(len(meta['pieces'][0]['cutPaths']), 2)
        slit = meta['pieces'][0]['cutPaths'][1]
        self.assertTrue(slit['closed'])
        self.assertFalse(slit['boundary'])
        self.assertEqual(slit['commands'], [('m', [40, 40]), ('l', [60, 60]), ('l', [50, 50]), ('h', [])])
        with tempfile.TemporaryDirectory() as folder:
            parsed = import_to_store(source(body), folder)
            from pathlib import Path
            import json
            ident = parsed['documentId']
            stored = json.loads((Path(folder) / (ident + '.json')).read_text())
            clean = (Path(folder) / (ident + '.pdf')).read_bytes()
            part = parsed['parts'][0]
            out = export_pdf({'parts': [part]}, {'width': 100, 'usedLength': 100,
                'placements': [{'id': part['id'], 'x': 0, 'y': 0, 'rotation': 0}]}, {ident: (clean, stored)})
            commands = PdfReader(io.BytesIO(out)).pages[0].get_contents().get_data()
            self.assertIn(b'40 40 m\n60 60 l\n50 50 l\nh\nS', commands)
            self.assertEqual(sum(op == b'S' for _, op in PdfReader(io.BytesIO(out)).pages[0].get_contents().operations), 2)

    def test_slits_still_need_unique_owner_and_invalid_boundaries_reject(self):
        for body, error in (
                ('40 40 m 60 60 l h S', 'No closed piece'),
                ('20 20 80 80 re S 90 90 m 120 120 l h S', 'no unique piece owner'),
                ('20 20 80 80 re S 40 40 m 60 60 l h S 60 60 m 40 40 l h S', 'Duplicate'),
                ('20 20 m 100 100 l 20 100 l 100 20 l h S', 'self-intersecting'),
                ('40 40 m 40 40 l h S', 'too small')):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, error):
                read_document(source('/Contour CS 1 SCN ' + body))

    def test_no_mapped_cuts_has_distinct_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'No cut lines found.*spot.*layer'):
            read_document(source('20 20 80 80 re f'))

    def test_clip_complexity_guard(self):
        with patch('pdf_io.MAX_CLIP_SEGMENTS', 4), self.assertRaisesRegex(ValueError, 'Clipping mask is too complex'):
            read_document(source('10 10 100 100 re 150 10 100 100 re W n /Contour CS 1 SCN 20 20 80 80 re S'))


if __name__ == '__main__':
    unittest.main()
