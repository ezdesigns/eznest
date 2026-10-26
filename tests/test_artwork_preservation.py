import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject, FloatObject
from shapely.geometry import Polygon

from pdf_io import read_document, import_to_store, export_pdf, MM
from test_pdf_production import pdf_fixture


def rendered(raw):
    with pdfium.PdfDocument(raw) as doc:
        page = doc[0]
        bitmap = page.render(scale=2, fill_color=(255,255,255,0))
        try:
            return np.asarray(bitmap.to_pil().convert('RGBA')).copy()
        finally:
            bitmap.close()
            page.close()


class ArtworkPreservationTests(unittest.TestCase):
    def test_nearby_decoration_without_its_own_cut_stays_with_the_piece(self):
        writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        stream = DecodedStreamObject()
        stream.set_data(b'1 0 0 rg 10 10 110 90 re f 124 30 5 20 re f '
                        b'/Contour CS 1 SCN .25 w 20 20 90 70 re S')
        writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
        raw = io.BytesIO(); writer.write(raw)
        with tempfile.TemporaryDirectory() as directory:
            data = import_to_store(raw.getvalue(), directory, preserve=True)
            self.assertEqual(len(data['parts']), 1)
            self.assertEqual(data['sourcePieceCount'], 1)
            self.assertGreater(data['parts'][0]['previewWidth'], 119*MM)

    def test_nearby_bleed_stays_independent_without_losing_or_copying_ink(self):
        # A 4-point ink gap exceeds the paint guards but not the former double
        # guard. Translucency exposes duplicate ink in source-position reassembly.
        for kind, gap in (('path', 4), ('image', 4), ('path', 3)):
            with self.subTest(kind=kind, gap=gap), tempfile.TemporaryDirectory() as directory:
                writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
                page = writer.pages[0]
                page['/Resources'][NameObject('/ExtGState')] = DictionaryObject({
                    NameObject('/Half'): DictionaryObject({NameObject('/ca'): FloatObject(.5)})})
                content = b'q /Half gs 1 0 0 rg 10 10 110 90 re f Q\n'
                if kind == 'path':
                    content += b'q /Half gs 0 0 1 rg 124 10 100 90 re f Q\n'
                else:
                    content += (b'q 100 0 0 90 124 10 cm '
                                b'BI /W 1 /H 1 /CS /RGB /BPC 8 /F /AHx ID 0000ff> EI Q\n')
                content += (b'/Contour CS 1 SCN .25 w 20 20 90 70 re S '
                            b'134 20 80 70 re S\n')
                content = content.replace(b'124', str(120+gap).encode()).replace(b'134', str(130+gap).encode())
                stream = DecodedStreamObject(); stream.set_data(content)
                page[NameObject('/Contents')] = writer._add_object(stream)
                raw = io.BytesIO(); writer.write(raw)
                data = import_to_store(raw.getvalue(), directory, preserve=True)
                if gap == 3:
                    # A guard reaches its neighbour's protected paint, so keep
                    # the two pieces together instead of risking copied ink.
                    self.assertEqual(len(data['parts']), 1)
                    self.assertEqual(data['parts'][0]['sourcePieceCount'], 2)
                    self.assertEqual(sum(data['parts'][0]['cutCounts'].values()), 2)
                    continue
                self.assertEqual(len(data['parts']), 2)
                self.assertEqual([p['sourcePieceCount'] for p in data['parts']], [1, 1])
                ident = data['documentId']
                clean = (Path(directory)/(ident+'.pdf')).read_bytes()
                meta = json.loads((Path(directory)/(ident+'.json')).read_text())
                clip_polygons = [Polygon([values for op, values in p['clipCommands'] if op in ('m', 'l')])
                                 for p in meta['pieces']]
                # Their extra guards overlap only in blank source space.
                from shapely.geometry import box
                self.assertFalse(clip_polygons[0].disjoint(clip_polygons[1]))
                self.assertTrue(clip_polygons[0].disjoint(box(124, 10, 224, 100)))
                self.assertTrue(clip_polygons[1].disjoint(box(10, 10, 120, 100)))
                for part, piece, clip in zip(data['parts'], meta['pieces'], clip_polygons):
                    x0, y1 = piece['anchor']
                    search = Polygon([(x0+x/MM, y1-y/MM) for x, y in part['points']])
                    self.assertTrue(search.buffer(1e-8).covers(clip))
                    self.assertGreaterEqual(search.area + 1e-8, clip.area)
                placements = [{'id':part['id'], 'rotation':0, 'x':piece['anchor'][0]*MM,
                               'y':300*MM-piece['anchor'][1]*MM}
                              for part, piece in zip(data['parts'], meta['pieces'])]
                output = export_pdf({'parts':data['parts']},
                                    {'width':400*MM, 'usedLength':300*MM, 'placements':placements},
                                    {ident:(clean, meta)})
                cleaned, exported_meta = read_document(output)
                self.assertTrue(np.array_equal(rendered(clean), rendered(cleaned)))
                self.assertEqual(sum(len(p['cutPaths']) for p in exported_meta['pieces']), 2)

    def test_complex_outline_reduction_contains_every_original_vertex(self):
        import math
        from artwork_bounds import compact_enclosure
        points=[((100 + .002 * math.sin(i*31))*math.cos(i*math.tau/6000),
                 (100 + .002 * math.sin(i*31))*math.sin(i*math.tau/6000)) for i in range(6000)]
        original=Polygon(points)
        compact=compact_enclosure(original)
        self.assertLessEqual(len(compact.exterior.coords),5001)
        self.assertTrue(compact.covers(original))
        self.assertLess(compact.area/original.area,1.005)

    def test_artwork_outside_cuts_survives_unchanged_including_transformed_forms(self):
        for forms, curved_border in ((False, False), (True, False), (False, True)):
            with self.subTest(forms=forms, curved_border=curved_border), tempfile.TemporaryDirectory() as directory:
                raw = pdf_fixture(forms=forms)
                if curved_border:
                    writer = PdfWriter(clone_from=io.BytesIO(raw))
                    stream = DecodedStreamObject()
                    stream.set_data(writer.pages[0].get_contents().get_data()+
                                    b'\nq 0 0 1 RG 10 w 15 95 m 20 150 100 150 115 95 c S Q\n')
                    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
                    buffer = io.BytesIO(); writer.write(buffer); raw = buffer.getvalue()
                data = import_to_store(raw, directory, preserve=True)
                ident = data['documentId']
                clean = (Path(directory)/(ident+'.pdf')).read_bytes()
                meta = json.loads((Path(directory)/(ident+'.json')).read_text())
                self.assertTrue(data['artworkPreserved'])
                self.assertEqual(len(data['parts']), 2)
                page = PdfReader(io.BytesIO(clean)).pages[0]
                height = float(page.mediabox.height)*MM
                placements = []
                for part, piece in zip(data['parts'], meta['pieces']):
                    self.assertGreater(Polygon(part['points']).area, Polygon(piece['pdfPoints']).area*MM*MM)
                    placements.append({'id':part['id'], 'rotation':0, 'x':piece['anchor'][0]*MM,
                                       'y':height-piece['anchor'][1]*MM})
                result = {'width':float(page.mediabox.width)*MM,'usedLength':height,'placements':placements}
                job = {'parts':data['parts']}
                exported = export_pdf(job,result,{ident:(clean,meta)})
                cleaned_export, exported_meta = read_document(exported)
                # Reassembly at source positions verifies every painted pixel,
                # including the area that used to be discarded outside cuts.
                self.assertTrue(np.array_equal(rendered(clean), rendered(cleaned_export)))
                self.assertEqual(sum(len(p['cutPaths']) for p in meta['pieces']),
                                 sum(len(p['cutPaths']) for p in exported_meta['pieces']))
                job['settings'] = {'autoBleedMm':1}
                with self.assertRaisesRegex(ValueError,'enlargement'):
                    export_pdf(job,result,{ident:(clean,meta)})

    def test_connected_artwork_keeps_both_cut_pieces_as_one_unit(self):
        writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        page = writer.pages[0]
        stream = DecodedStreamObject()
        stream.set_data(page.get_contents().get_data()+b'\n0 0 0 rg 110 40 85 10 re f\n')
        page[NameObject('/Contents')] = writer._add_object(stream)
        raw = io.BytesIO(); writer.write(raw)
        with tempfile.TemporaryDirectory() as directory:
            data = import_to_store(raw.getvalue(),directory,preserve=True)
            self.assertEqual(len(data['parts']),1)
            self.assertEqual(data['sourcePieceCount'],2)
            self.assertEqual(data['parts'][0]['sourcePieceCount'],2)
            self.assertEqual(sum(data['parts'][0]['cutCounts'].values()),2)

    def test_unowned_artwork_is_flagged_instead_of_silently_discarded(self):
        for page_number, count in ((1,1),(2,2)):
            with self.subTest(page=page_number, groups=count):
                writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
                if page_number == 2:
                    writer.add_page(PdfReader(io.BytesIO(pdf_fixture())).pages[0])
                page = writer.pages[page_number-1]; stream = DecodedStreamObject()
                extra = b'\n0 0 0 rg 330 200 20 20 re f\n'
                if count == 2:
                    extra += b'280 200 20 20 re f\n'
                stream.set_data(page.get_contents().get_data()+extra)
                page[NameObject('/Contents')] = writer._add_object(stream)
                raw = io.BytesIO(); writer.write(raw)
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(ValueError) as error:
                        import_to_store(raw.getvalue(),directory,preserve=True)
                    self.assertIn(f'Page {page_number}: {count} separate artwork group',str(error.exception))
                    self.assertIn('no cut boundary',str(error.exception))
                    self.assertIn('Add closed cut lines',str(error.exception))
                    self.assertEqual(list(Path(directory).glob('*')),[])
