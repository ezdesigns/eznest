import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
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
        writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        page = writer.pages[0]; stream = DecodedStreamObject()
        stream.set_data(page.get_contents().get_data()+b'\n0 0 0 rg 330 200 20 20 re f\n')
        page[NameObject('/Contents')] = writer._add_object(stream)
        raw = io.BytesIO(); writer.write(raw)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'separate from every cut piece'):
                import_to_store(raw.getvalue(),directory,preserve=True)
