"""Mixed Illustrator layers retain ink and review only separate matching outlines."""
import io
import unittest
from pypdf import PdfWriter, PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject, DecodedStreamObject
from pdf_io import read_document, CutReviewRequired


def fixture():
    writer=PdfWriter();page=writer.add_blank_page(width=300,height=150)
    layer=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject('Thru-cut')}))
    image=DecodedStreamObject();image.set_data(bytes([0,120,200]));image.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),NameObject('/Width'):NumberObject(1),NameObject('/Height'):NumberObject(1),NameObject('/BitsPerComponent'):NumberObject(8),NameObject('/ColorSpace'):NameObject('/DeviceRGB')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Properties'):DictionaryObject({NameObject('/Cuts'):layer}),NameObject('/XObject'):DictionaryObject({NameObject('/Photo'):writer._add_object(image)})})
    stream=DecodedStreamObject();stream.set_data(b'''
      /OC /Cuts BDC
      q 0 1 0 rg 15 15 90 90 re f Q
      q 10 0 0 10 40 40 cm /Photo Do Q
      q 1 0 0 RG 1 w 20 20 80 80 re S Q EMC
      q 0 0 1 rg 155 15 90 90 re f Q
      q 1 0 0 RG .2 w 160 20 80 80 re S Q
      q 1 0 0 RG 30 30 10 10 re S Q
      q 0 0 0 RG 170 30 5 5 re S Q
    ''');page[NameObject('/Contents')]=writer._add_object(stream)
    out=io.BytesIO();writer.write(out);return out.getvalue()


class MixedCutArtworkTests(unittest.TestCase):
    def test_mixed_layer_ink_is_preserved_and_only_separate_matching_outline_is_reviewed(self):
        raw=fixture()
        with self.assertRaises(CutReviewRequired) as raised:read_document(raw,prepare=True)
        review=raised.exception.review
        self.assertEqual(review['count'],1)
        approval={k:review[k] for k in ('id','sourceHash')}
        approval.update(operation='thru',pages=[1])
        clean,meta=read_document(raw,prepare=True,cut_approval=approval)
        self.assertEqual(len(meta['pieces']),2)
        self.assertEqual(sum(p['cutCounts']['thru'] for p in meta['pieces']),2)
        ops=PdfReader(io.BytesIO(clean)).pages[0].get_contents().operations
        self.assertEqual(sum(op==b'S' for _,op in ops),2) # Printed interior borders survive.
        self.assertEqual(sum(op==b'f' for _,op in ops),2)
        self.assertEqual(sum(op==b'Do' for _,op in ops),1)
        self.assertTrue(any('preserved as artwork' in w for w in meta['warnings']))
        with self.assertRaisesRegex(ValueError,'does not match'):
            read_document(raw+b'\n',prepare=True,cut_approval=approval)

    def test_legacy_strict_import_still_rejects_mixed_cut_layer(self):
        with self.assertRaisesRegex(ValueError,'filled shapes'):read_document(fixture())

    def test_explicit_cut_spot_fill_is_never_treated_as_print_ink(self):
        from test_mixed_cuts import mixed_fixture
        raw=mixed_fixture(generic=False,registration=False,extra='/Thru cs 1 scn 30 30 4 4 re f')
        with self.assertRaisesRegex(ValueError,'filled shapes'):read_document(raw,prepare=True)


if __name__=='__main__':unittest.main()
