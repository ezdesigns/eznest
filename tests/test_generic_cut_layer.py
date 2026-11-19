"""Generic process-color cut layers use the existing cut-choice flow."""
import io
import unittest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, TextStringObject
from cut_mapping import classify, defaults
from pdf_io import read_document
from test_pdf_production import pdf_fixture


def layer_fixture(forms=False, layer='CutContour'):
    writer=PdfWriter(clone_from=io.BytesIO(pdf_fixture(forms=forms, spot=False)))
    page=writer.pages[0]
    group=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject(layer)}))
    page['/Resources'][NameObject('/Properties')]=DictionaryObject({NameObject('/GenericCut'):group})
    stream=DecodedStreamObject()
    stream.set_data(b'/OC /GenericCut BDC '+page.get_contents().get_data()+b' EMC')
    page[NameObject('/Contents')]=writer._add_object(stream)
    groups=ArrayObject([group])
    writer.root_object[NameObject('/OCProperties')]=DictionaryObject({NameObject('/OCGs'):groups})
    output=io.BytesIO();writer.write(output);return output.getvalue()


class GenericCutLayerTests(unittest.TestCase):
    def test_layer_import_keeps_art_and_requests_operation(self):
        for forms in (False,True):
            raw=layer_fixture(forms)
            with self.subTest(forms=forms),self.assertRaisesRegex(ValueError,'Unspecified cut type'):
                read_document(raw,cut_mapping=defaults(),prepare=True)
            results=[]
            for operation in ('contour','thru','kiss'):
                mapping=defaults();mapping['genericOperation']=operation
                clean,meta=read_document(raw,cut_mapping=mapping,prepare=True)
                self.assertEqual(len(meta['pieces']),2)
                self.assertEqual(sum(len(p['cutPaths']) for p in meta['pieces']),2)
                self.assertEqual(meta['bleedMm'],0)
                for piece in meta['pieces']:
                    self.assertEqual(piece['cutCounts'][operation],1)
                    cut=piece['cutPaths'][0]
                    self.assertEqual(cut['sourceLayers'],['CutContour'])
                    self.assertIsNone(cut['sourceSpot'])
                results.append((clean,[(p['bounds'],p['cutPaths'][0]['commands'],p['cutPaths'][0]['strokeStyle']) for p in meta['pieces']]))
            # Choosing a tool must not change printed artwork, bleed, source
            # geometry, or the process color of the original stroke.
            self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2])

    def test_explicit_names_win_and_unknown_names_still_need_review(self):
        mapping=defaults();mapping['genericOperation']='kiss'
        self.assertEqual(classify(mapping,None,['CutContour','Thru-cut']),'thru')
        self.assertEqual(classify(mapping,'CutContour_Thru-cut',['CutContour']),'thru')
        mapping['rules'].append({'source':'layer','match':'exact','name':'CutContour','operation':'thru'})
        self.assertEqual(classify(mapping,None,['CutContour']),'thru')
        mapping=defaults();mapping['genericOperation']='thru'
        for spot,layers in [(None,['CutContour_Unknown']),('CutContour_Unknown',['CutContour']),('BrandInk',['CutContour'])]:
            with self.subTest(spot=spot,layers=layers),self.assertRaisesRegex(ValueError,'Unmapped'):
                classify(mapping,spot,layers)
        self.assertIsNone(classify(mapping,None,['Print']))

    def test_browser_upload_offers_existing_choice_without_nesting(self):
        import test_web_mvp
        from playwright.sync_api import sync_playwright,expect
        helper=test_web_mvp.WebMvpTests();helper.setUp()
        try:
            with sync_playwright() as pw:
                browser,page=helper.open_page(pw)
                try:
                    page.set_input_files('#file',{'name':'Layer-only.ai','mimeType':'application/pdf','buffer':layer_fixture(True)})
                    page.wait_for_function('() => !importing && kits.length === 1')
                    self.assertTrue(page.evaluate('kits[0].unresolved'))
                    self.assertIsNone(page.evaluate('current'))
                    helper.start_nesting(page)
                    expect(page.locator('#checks')).to_contain_text('Plain CutContour found',timeout=90000)
                    page.click('#choose-thru');page.click('#choose-confirm')
                    page.wait_for_function('() => !importing && !kits[0].unresolved')
                    self.assertEqual(page.evaluate('kits[0].data.parts.reduce((n,p) => n+p.cutCounts.thru,0)'),2)
                    self.assertIsNone(page.evaluate('current'))
                finally:browser.close()
        finally:helper.tearDown()
