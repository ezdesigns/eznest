"""Bad silhouettes must not rewrite the customer's cutter paths or bleed."""
import io
import tempfile
import unittest

import pypdfium2 as pdfium
from PIL import ImageChops
from pypdf import PdfReader
from shapely.geometry import box

from cut_mapping import defaults
from pdf_io import MM, export_pdf, import_to_store, load_documents, read_document
from test_automatic_prepare import fixture
from test_pdf_production import document_job
from test_mixed_cuts import mixed_fixture


class IrregularCutTests(unittest.TestCase):
    def roundtrip(self, raw):
        with tempfile.TemporaryDirectory() as folder:
            parsed = import_to_store(raw, folder, preserve=True, cut_mapping=defaults())
            job = document_job(parsed)
            docs = load_documents(job, folder)
            clean, meta = docs[parsed['documentId']]
            page = PdfReader(io.BytesIO(raw)).pages[0]
            width, height = map(float, (page.mediabox.width, page.mediabox.height))
            # Place each piece in its original position, so exported coordinates
            # and artwork pixels can be compared directly against the source.
            placements = [dict(id=part['id'], x=piece['anchor'][0]*MM,
                               y=(height-piece['anchor'][1])*MM, rotation=0)
                          for part, piece in zip(job['parts'], meta['pieces'])]
            output = export_pdf(job, dict(width=width*MM, usedLength=height*MM,
                                         placements=placements), docs, cut_mapping=defaults())
            exported_clean, exported_meta = read_document(output, cut_mapping=defaults(), prepare=True)
            original_cuts = [c for p in meta['pieces'] for c in p['cutPaths']]
            exported_cuts = [c for p in exported_meta['pieces'] for c in p['cutPaths']]
            from pdf_cut_colors import _signature
            original_reader = PdfReader(io.BytesIO(clean))
            exported_reader = PdfReader(io.BytesIO(exported_clean))
            self.assertEqual(len(original_cuts), len(exported_cuts))
            for original, exported in zip(original_cuts, exported_cuts):
                self.assertEqual(original['operation'], exported['operation'])
                self.assertEqual(original['sourceSpot'], exported['sourceSpot'])
                self.assertEqual(original['sourceColor']['values'], exported['sourceColor']['values'])
                def color(reader, cut):
                    return reader.pages[cut['page']]['/Resources']['/ColorSpace'][cut['sourceColor']['resource']]
                self.assertEqual(_signature(color(original_reader, original)),
                                 _signature(color(exported_reader, exported)))
                self.assertEqual([op for op,_ in original['commands']], [op for op,_ in exported['commands']])
                for (_, expected), (_, actual) in zip(original['commands'], exported['commands']):
                    for a,b in zip(expected, actual):
                        self.assertAlmostEqual(a, b, places=5)
            images = []
            for data in (clean, exported_clean):
                with pdfium.PdfDocument(data) as doc:
                    rendered_page = doc[0]
                    bitmap = rendered_page.render(scale=2)
                    images.append(bitmap.to_pil().convert('RGB'))
                    bitmap.close(); rendered_page.close()
            self.assertIsNone(ImageChops.difference(*images).getbbox(), 'Print artwork or bleed changed')
            self.assertTrue(parsed['preparationReview'])
            return parsed, meta

    def test_crossed_boundary_keeps_art_and_bleed_and_does_not_become_a_new_cut(self):
        raw = fixture('0 1 0 rg 8 8 100 100 re f /Contour CS 1 SCN .25 w '
                      '20 20 m 100 100 l 20 100 l 100 20 l h S', named=True)
        with self.assertRaisesRegex(ValueError, 'self-intersecting'):
            read_document(raw, cut_mapping=defaults())
        parsed, meta = self.roundtrip(raw)
        self.assertEqual(len(parsed['parts']), 1)
        self.assertTrue(meta['pieces'][0]['preservedPageGroup'])
        self.assertEqual(meta['pieces'][0]['cutCounts']['thru'], 1)
        self.assertTrue(any('more material' in w for w in parsed['warnings']))

    def test_proven_source_groups_still_nest_separately(self):
        raw = fixture('q 10 10 100 100 re W n 1 0 0 rg 0 0 150 150 re f Q '
                      'q 180 10 100 100 re W n 0 0 1 rg 170 0 120 150 re f Q '
                      '/Contour CS 1 SCN .25 w 20 20 m 100 100 l 20 100 l 100 20 l h S '
                      '190 20 80 80 re S', named=True)
        parsed, meta = self.roundtrip(raw)
        self.assertEqual(len(parsed['parts']), 2)
        self.assertEqual([p['sourceObjectIds'] for p in meta['pieces']], [[0], [1]])
        self.assertFalse(any(p.get('preservedPageGroup') for p in meta['pieces']))
        self.assertTrue(box(*meta['pieces'][0]['bounds']).covers(box(10,10,110,110)))
        self.assertTrue(box(*meta['pieces'][1]['bounds']).covers(box(180,10,280,110)))
        self.assertFalse(box(*meta['pieces'][0]['bounds']).intersects(box(*meta['pieces'][1]['bounds'])))

    def test_tiny_and_zero_length_internal_cuts_are_not_discarded(self):
        for tiny in ('40 40 .01 .01 re S', '40 40 m 40.001 40 l S', '40 40 m 40 40 l S'):
            with self.subTest(tiny=tiny):
                raw = fixture('q 10 10 100 100 re W n 1 0 0 rg 0 0 150 150 re f Q '
                              '/Contour CS 1 SCN .25 w 20 20 80 80 re S '+tiny, named=True)
                _, meta = self.roundtrip(raw)
                self.assertEqual(len(meta['pieces']), 1)
                self.assertEqual(meta['pieces'][0]['cutCounts']['thru'], 2)

    def test_large_path_count_uses_complete_page_fallback(self):
        cuts = ' '.join(f'{20+n} 20 .01 .01 re S' for n in range(201))
        raw = fixture('0 1 0 rg 10 10 240 40 re f /Contour CS 1 SCN .25 w '+cuts, named=True)
        _, meta = self.roundtrip(raw)
        self.assertTrue(meta['pieces'][0]['preservedPageGroup'])
        self.assertEqual(meta['pieces'][0]['cutCounts']['thru'], 201)

    def test_through_and_kiss_names_colors_and_counts_are_preserved(self):
        raw = mixed_fixture(extra='/OC /Inner BDC q /Kiss CS .6 SCN .25 w 40 40 .01 .01 re S Q EMC')
        _, meta = self.roundtrip(raw)
        cuts = [c for p in meta['pieces'] for c in p['cutPaths']]
        self.assertEqual(sum(c['operation'] == 'thru' for c in cuts), 2)
        self.assertEqual(sum(c['operation'] == 'kiss' for c in cuts), 6)

    def test_outside_page_is_not_hidden_by_fallback(self):
        raw = fixture('/Contour CS 1 SCN -20 20 m 100 100 l -20 100 l 100 20 l h S', named=True)
        with self.assertRaisesRegex(ValueError, 'outside its PDF page'):
            read_document(raw, cut_mapping=defaults(), prepare=True)


if __name__ == '__main__':
    unittest.main()
