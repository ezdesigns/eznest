import io
import unittest

from PIL import ImageCms
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, NameObject, NumberObject

from cut_mapping import defaults
from pdf_io import export_pdf, read_document
from test_pdf_production import pdf_fixture


def fixture(color=(0, 0, 1), forms=False):
    reader = PdfReader(io.BytesIO(pdf_fixture(forms=forms)))
    writer = PdfWriter(); page = writer.add_page(reader.pages[0])
    resources = page['/Resources']
    if forms:
        resources = resources['/XObject']['/Panel']['/Resources']
    spot = resources['/ColorSpace']['/Contour']
    profile = DecodedStreamObject()
    profile.set_data(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    profile[NameObject('/N')] = NumberObject(3)
    spot[2] = ArrayObject([NameObject('/ICCBased'), writer._add_object(profile)])
    spot[3].get_object()[NameObject('/C0')] = ArrayObject([NumberObject(1)] * 3)
    spot[3].get_object()[NameObject('/C1')] = ArrayObject([NumberObject(v) for v in color])
    raw = io.BytesIO(); writer.write(raw)
    mapping = defaults(); mapping['genericOperation'] = 'thru'
    return read_document(raw.getvalue(), cut_mapping=mapping)


def exported(documents, preview=False):
    parts = [{'id': ident + p['id'], 'documentId': ident, 'pdfPieceId': p['id']}
             for ident, (_, meta) in documents.items() for p in meta['pieces']]
    result = {'width': 400, 'usedLength': 150, 'placements': [
        {'id': p['id'], 'x': 10+i*80, 'y': 10, 'rotation': 0} for i, p in enumerate(parts)]}
    return PdfReader(io.BytesIO(export_pdf({'parts': parts}, result, documents, preview=preview)))


class CutAppearanceTests(unittest.TestCase):
    def test_source_blue_profile_and_tint_survive_renaming_and_preview(self):
        for forms in (False, True):
            clean, meta = fixture(forms=forms)
            original = bytes(clean)
            source = PdfReader(io.BytesIO(clean)).pages[0]['/Resources']
            if forms:
                source = source['/XObject']['/Panel']['/Resources']
            original_space = source['/ColorSpace']['/Contour']
            for preview in (False, True):
                result = exported({'doc': (clean, meta)}, preview)
                space = result.pages[0]['/Resources']['/ColorSpace']['/EZCut']
                self.assertEqual(space[1], '/CutContour_Thru-cut')
                self.assertEqual(list(space[3].get_object()['/C1']), [0, 0, 1])
                self.assertEqual(space[2].get_object()[1].get_object().get_data(), original_space[2].get_object()[1].get_object().get_data())
            self.assertEqual(clean, original)

    def test_disagreeing_source_definitions_use_blue_not_cyan(self):
        result = exported({'a': fixture(), 'b': fixture((0, 1, 1))})
        space = result.pages[0]['/Resources']['/ColorSpace']['/EZCut']
        self.assertEqual(space[1], '/CutContour_Thru-cut')
        self.assertEqual(space[2], '/DeviceCMYK')
        self.assertEqual(list(space[3].get_object()['/C1']), [1, 1, 0, 0])

    def test_normal_pdf_upload_has_separate_print_and_cut_layers(self):
        result = exported({'doc': fixture()})
        self.assertEqual({g.get_object()['/Name'] for g in result.root_object['/OCProperties']['/OCGs']},
                         {'Print', 'Thru-cut'})
        page = result.pages[0]; stack = []; art = cuts = 0
        for values, op in ContentStream(page.get_contents(), result).operations:
            if op == b'BDC':
                stack.append(page['/Resources']['/Properties'][values[1]]['/Name'])
            elif op == b'EMC':
                stack.pop()
            elif op == b'Do':
                self.assertEqual(stack[-1], 'Print'); art += 1
            elif op == b'S':
                self.assertEqual(stack[-1], 'Thru-cut'); cuts += 1
        self.assertEqual((art, cuts), (2, 2))

