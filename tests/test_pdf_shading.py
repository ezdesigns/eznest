import copy
import io
import unittest

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, ContentStream,
                           DecodedStreamObject, DictionaryObject, FloatObject,
                           NameObject, NumberObject)

from pdf_io import form_from_page
from pdf_shading import solid_shadings


def array(values):
    return ArrayObject([FloatObject(v) for v in values])


def fixture():
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    function = DictionaryObject({NameObject('/FunctionType'): NumberObject(2),
        NameObject('/Domain'): array([0, 1]), NameObject('/C0'): array([.7, .3, .1]),
        NameObject('/C1'): array([.7, .3, .1]), NameObject('/N'): NumberObject(1)})
    shade = DictionaryObject({NameObject('/ShadingType'): NumberObject(2),
        NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
        NameObject('/Coords'): array([0, 0, 1, 0]),
        NameObject('/Extend'): ArrayObject([BooleanObject(True), BooleanObject(True)]),
        NameObject('/Function'): writer._add_object(function)})
    gradient = DictionaryObject(shade)
    other = DictionaryObject(function)
    other[NameObject('/C1')] = array([.1, .2, .8])
    gradient[NameObject('/Function')] = writer._add_object(other)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Shading'):
        DictionaryObject({NameObject('/Constant'): writer._add_object(shade),
                          NameObject('/Gradient'): writer._add_object(gradient)})})
    content = DecodedStreamObject()
    content.set_data(b'q 70 30 -25 60 120 40 cm 0 0 1 1 re W n /Constant sh Q '
                     b'q 90 0 0 60 10 120 cm 0 0 1 1 re W n /Gradient sh Q')
    page[NameObject('/Contents')] = writer._add_object(content)
    return writer, page


def raw(writer):
    out = io.BytesIO(); writer.write(out); return out.getvalue()


def pixels(raw_pdf):
    with pdfium.PdfDocument(raw_pdf) as document:
        page = document[0]
        bitmap = page.render(scale=2)
        try:
            return np.array(bitmap.to_pil().convert('RGB'))
        finally:
            bitmap.close(); page.close()


class ShadingTests(unittest.TestCase):
    def test_export_form_preserves_pixels_and_real_gradient(self):
        original, page = fixture()
        before = raw(original)
        writer = PdfWriter()
        target = writer.add_blank_page(300, 200)
        form = form_from_page(page, writer)
        target[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'):
            DictionaryObject({NameObject('/Art'): form})})
        content = DecodedStreamObject(); content.set_data(b'/Art Do')
        target[NameObject('/Contents')] = writer._add_object(content)
        self.assertTrue(np.array_equal(pixels(before), pixels(raw(writer))))
        self.assertEqual(before, raw(original), 'source must not be mutated')
        result = form.get_object()
        self.assertEqual(list(result['/Resources']['/Shading']), ['/Gradient'])
        ops = ContentStream(result, writer).operations
        self.assertEqual([str(v[0]) for v, op in ops if op == b'sh'], ['/Gradient'])
        self.assertIn('/EZSolidShading0', result['/Resources']['/ColorSpace'])

    def test_profile_is_kept_byte_for_byte(self):
        from PIL import ImageCms
        writer, page = fixture()
        profile = DecodedStreamObject()
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        profile.set_data(icc); profile[NameObject('/N')] = NumberObject(3)
        page['/Resources']['/Shading']['/Constant'][NameObject('/ColorSpace')] = ArrayObject([
            NameObject('/ICCBased'), writer._add_object(profile)])
        before = raw(writer)
        output = PdfWriter(); form = form_from_page(page, output).get_object()
        color = form['/Resources']['/ColorSpace']['/EZSolidShading0']
        self.assertEqual(color[0], '/ICCBased')
        self.assertEqual(color[1].get_object().get_data(), icc)
        self.assertEqual(raw(writer), before)

    def test_uncertain_shadings_unchanged(self):
        changes = [('/Extend', ArrayObject([BooleanObject(False), BooleanObject(True)])),
                   ('/BBox', array([0, 0, 1, 1])), ('/ShadingType', NumberObject(3)),
                   ('/Coords', array([0, 0, 0, 0]))]
        for key, value in changes:
            with self.subTest(key=key):
                _, page = fixture()
                page['/Resources']['/Shading']['/Constant'][NameObject(key)] = value
                original = page.get_contents().get_data()
                content, _ = solid_shadings(original, page['/Resources'], page.mediabox)
                self.assertEqual(content, original)

    def test_pending_path_and_singular_matrix_are_not_rewritten(self):
        for content in (b'0 0 m 10 10 l /Constant sh S', b'0 0 0 0 0 0 cm /Constant sh'):
            with self.subTest(content=content):
                _, page = fixture()
                data, _ = solid_shadings(content, page['/Resources'], page.mediabox)
                self.assertEqual(data, content)

    def test_partially_replaced_definition_is_retained(self):
        _, page = fixture()
        content = b'/Constant sh 0 0 m /Constant sh S'
        data, res = solid_shadings(content, page['/Resources'], page.mediabox)
        self.assertIn('/Constant', res['/Shading'])
        self.assertEqual(data.count(b'/Constant sh'), 1)

    def test_inherited_resource_consumers_are_not_changed(self):
        for key, subtype in (('/XObject', '/Form'), ('/Font', '/Type3')):
            with self.subTest(subtype=subtype):
                _, page = fixture()
                page['/Resources'][NameObject(key)] = DictionaryObject({NameObject('/Child'):
                    DictionaryObject({NameObject('/Subtype'): NameObject(subtype)})})
                content = page.get_contents().get_data()
                data, _ = solid_shadings(content, page['/Resources'], page.mediabox)
                self.assertEqual(data, content)

    def test_nested_shared_forms_preserve_source_and_reuse_replacement(self):
        original, source = fixture()
        # Build an unchanged nested source, rather than calling the fix to make it.
        leaf = DecodedStreamObject(); leaf.set_data(source.get_contents().get_data())
        leaf.update({NameObject('/Subtype'): NameObject('/Form'),
                     NameObject('/BBox'): source.mediabox,
                     NameObject('/Resources'): source['/Resources']})
        ref = original._add_object(leaf)
        source[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'):
            DictionaryObject({NameObject('/One'): ref, NameObject('/Two'): ref})})
        stream = DecodedStreamObject(); stream.set_data(b'/One Do /Two Do')
        source[NameObject('/Contents')] = original._add_object(stream)
        before = raw(original)
        writer = PdfWriter()
        form = form_from_page(source, writer).get_object()
        children = form['/Resources']['/XObject']
        self.assertEqual(children.raw_get('/One'), children.raw_get('/Two'))
        self.assertEqual(list(children['/One']['/Resources']['/Shading']), ['/Gradient'])
        self.assertEqual(before, raw(original))


if __name__ == '__main__':
    unittest.main()
