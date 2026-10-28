import io
import unittest

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject)

from pdf_export_forms import clip_bounds, invocation_bounds, piece_form, remove_empty_groups
from pdf_io import form_from_page


def rendered(raw):
    with pdfium.PdfDocument(raw) as doc:
        page = doc[0]
        bitmap = page.render(scale=2)
        try:
            return np.array(bitmap.to_pil())
        finally:
            bitmap.close()
            page.close()


class ExportFormsTests(unittest.TestCase):
    def test_pruning_images_and_transformed_forms_preserves_pixels_and_resources(self):
        source = PdfWriter()
        page = source.add_blank_page(120, 40)
        objects = DictionaryObject()
        for name, rgb in [('/Red', b'\xff\x00\x00'), ('/Blue', b'\x00\x00\xff')]:
            image = DecodedStreamObject()
            image.set_data(rgb)
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            objects[NameObject(name)] = source._add_object(image)
        form = DecodedStreamObject()
        form.set_data(b'0 1 0 rg 0 0 10 10 re f')
        form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                     NameObject('/BBox'): ArrayObject([FloatObject(v) for v in (0,0,10,10)]),
                     NameObject('/Matrix'): ArrayObject([FloatObject(v) for v in (1,0,0,1,80,0)]),
                     NameObject('/Resources'): DictionaryObject()})
        objects[NameObject('/FarForm')] = source._add_object(form)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): objects})
        stream = DecodedStreamObject()
        stream.set_data(b'q 20 0 0 20 0 0 cm /Red Do Q q 20 0 0 20 60 0 cm /Blue Do Q /FarForm Do')
        page[NameObject('/Contents')] = source._add_object(stream)
        raw = io.BytesIO(); source.write(raw)
        reader = PdfReader(io.BytesIO(raw.getvalue())); original = reader.pages[0]
        analyzed = invocation_bounds(original, reader)
        outputs = []
        for optimized in (False, True):
            writer = PdfWriter(); target = writer.add_blank_page(120, 40)
            ref = piece_form(original, writer, analyzed, (0,0,25,25)) if optimized else form_from_page(original, writer)
            if optimized:
                self.assertEqual(set(ref.get_object()['/Resources']['/XObject']), {'/Red'})
                self.assertEqual(ref.get_object().get_data().count(b'Do'), 1)
            target[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Art'):ref})})
            draw = DecodedStreamObject(); draw.set_data(b'q 0 0 25 25 re W n /Art Do Q')
            target[NameObject('/Contents')] = writer._add_object(draw)
            result = io.BytesIO(); writer.write(result); outputs.append(result.getvalue())
        self.assertTrue(np.array_equal(rendered(outputs[0]), rendered(outputs[1])))

    def test_empty_groups_do_not_remove_paths_that_escape_graphics_state(self):
        # The path is not saved/restored by q/Q and is painted afterward.
        path = [([],b'q'),([0,0,10,10],b're'),([],b'Q'),([],b'f')]
        self.assertEqual(remove_empty_groups(path), path)
        inherited = [([0,0],b'm'),([],b'q'),([],b'n'),([],b'Q')]
        self.assertEqual(remove_empty_groups(inherited), inherited)
        unknown = [([],b'q'),([],b'BT'),([],b'ET'),([],b'Q')]
        self.assertEqual(remove_empty_groups(unknown), unknown)
        empty = [([],b'q'),([0,0,10,10],b're'),([],b'W'),([],b'n'),([],b'Q')]
        self.assertEqual(remove_empty_groups(empty), [])

    def test_curve_control_bounds_are_conservative_and_unknown_clip_falls_back(self):
        self.assertEqual(clip_bounds([('m',[1,2]),('c',[-10,50,40,-20,5,6]),('h',[])]), (-10,-20,40,50))
        self.assertIsNone(clip_bounds([('unsupported',[])]))


if __name__ == '__main__':
    unittest.main()
