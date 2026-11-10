import io
import unittest

from PIL import ImageCms
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, NameObject, NumberObject

from cut_mapping import defaults
from pdf_io import export_pdf, read_document
from test_pdf_production import pdf_fixture


def fixture(color=(0, 0, 1), forms=False, name="CutContour", operation="thru", tint=1):
    reader = PdfReader(io.BytesIO(pdf_fixture(forms=forms)))
    writer = PdfWriter(); page = writer.add_page(reader.pages[0])
    resources = page['/Resources']
    if forms:
        resources = resources['/XObject']['/Panel']['/Resources']
    spot = resources['/ColorSpace']['/Contour']
    spot[1] = NameObject('/'+name)
    profile = DecodedStreamObject()
    profile.set_data(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    profile[NameObject('/N')] = NumberObject(3)
    spot[2] = ArrayObject([NameObject('/ICCBased'), writer._add_object(profile)])
    spot[3].get_object()[NameObject('/C0')] = ArrayObject([NumberObject(1)] * 3)
    spot[3].get_object()[NameObject('/C1')] = ArrayObject([NumberObject(v) for v in color])
    target = (page['/Resources']['/XObject']['/Panel'].get_object() if forms else page)
    content = target.get_data() if forms else page.get_contents().get_data()
    body = content.replace(b'1 SCN', (str(tint)+' SCN').encode())
    if forms: target.set_data(body)
    else:
        stream=DecodedStreamObject(); stream.set_data(body); page[NameObject('/Contents')]=writer._add_object(stream)
    raw = io.BytesIO(); writer.write(raw)
    mapping = defaults(); mapping['genericOperation'] = operation
    mapping['rules'].append({'source':'spot','match':'exact','name':name,'operation':operation})
    return read_document(raw.getvalue(), cut_mapping=mapping)


def exported(documents, preview=False):
    parts = [{'id': ident + p['id'], 'documentId': ident, 'pdfPieceId': p['id']}
             for ident, (_, meta) in documents.items() for p in meta['pieces']]
    result = {'width': 400, 'usedLength': 150, 'placements': [
        {'id': p['id'], 'x': 10+i*80, 'y': 10, 'rotation': 0} for i, p in enumerate(parts)]}
    return PdfReader(io.BytesIO(export_pdf({'parts': parts}, result, documents, preview=preview)))


class CutAppearanceTests(unittest.TestCase):
    def test_source_blue_profile_name_and_tint_survive_export_and_preview(self):
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
                self.assertEqual(space[1], '/CutContour')
                self.assertEqual(list(space[3].get_object()['/C1']), [0, 0, 1])
                self.assertEqual(space[2].get_object()[1].get_object().get_data(), original_space[2].get_object()[1].get_object().get_data())
            self.assertEqual(clean, original)

    def test_conflicting_same_name_colors_are_explained_not_recolored(self):
        with self.assertRaisesRegex(ValueError, 'different colors'):
            exported({'a': fixture(), 'b': fixture((0, 1, 1))})

    def test_distinct_names_in_the_same_operation_keep_both_colors(self):
        result = exported({'a': fixture(name='CutContour Blue'),
                           'b': fixture((0, 1, 1), name='CutContour Cyan')})
        colors = {str(s[1]): list(s[3].get_object()['/C1'])
                  for s in result.pages[0]['/Resources']['/ColorSpace'].values()}
        self.assertEqual(colors, {'/CutContour Blue':[0,0,1], '/CutContour Cyan':[0,1,1]})

    def test_both_types_preserve_custom_name_color_and_non_full_tint(self):
        for forms in (False, True):
            result = exported({'a':fixture((0,1,1), forms, 'CutContour Custom Thru', 'thru', .4),
                               'b':fixture((1,0,0), forms, 'CutContour Custom Kiss', 'kiss', .7)})
            colors={str(s[1]):list(s[3].get_object()['/C1']) for s in result.pages[0]['/Resources']['/ColorSpace'].values()}
            self.assertEqual(colors, {'/CutContour Custom Thru':[0,1,1], '/CutContour Custom Kiss':[1,0,0]})
            values=[float(args[0]) for args,op in ContentStream(result.pages[0].get_contents(),result).operations if op==b'SCN']
            self.assertEqual(values,[.4,.4,.7,.7])

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

    def test_kiss_cut_keeps_its_source_color_even_when_it_is_not_pink(self):
        result = exported({'doc':fixture((0,1,0), name='Shop Kiss', operation='kiss')})
        color = result.pages[0]['/Resources']['/ColorSpace']['/EZCut']
        self.assertEqual(color[1], '/Shop Kiss')
        self.assertEqual(list(color[3].get_object()['/C1']), [0,1,0])

    def test_legacy_metadata_keeps_original_names_and_colors(self):
        clean,meta=fixture((1,0,0),name='Shop Kiss',operation='kiss',forms=True)
        for piece in meta['pieces']:
            for cut in piece['cutPaths']: cut.pop('sourceColor')
        result=exported({'doc':(clean,meta)})
        space=result.pages[0]['/Resources']['/ColorSpace']['/EZCut']
        self.assertEqual(space[1],'/Shop Kiss')
        self.assertEqual(list(space[3].get_object()['/C1']),[1,0,0])

    def test_layer_only_process_colors_keep_their_values(self):
        from test_mixed_cuts import mixed_fixture
        writer=PdfWriter(clone_from=io.BytesIO(mixed_fixture(generic=False)))
        page=writer.pages[0]; stream=DecodedStreamObject()
        stream.set_data(page.get_contents().get_data().replace(b'/Thru CS 1 SCN',b'0.13 0.32 0.71 RG').replace(b'/Kiss CS 1 SCN',b'0.2 0.5 0.1 0.3 K'))
        page[NameObject('/Contents')]=writer._add_object(stream)
        raw=io.BytesIO();writer.write(raw)
        clean,meta=read_document(raw.getvalue(),cut_mapping=defaults())
        result=exported({'doc':(clean,meta)})
        spaces={str(s[1]):s for s in result.pages[0]['/Resources']['/ColorSpace'].values()}
        for name,kind,values in [('CutContour_Thru-cut','/DeviceRGB',[.13,.32,.71]),('CutContour_Kiss-cut','/DeviceCMYK',[.2,.5,.1,.3])]:
            self.assertEqual(spaces['/'+name][2],kind)
            self.assertEqual(list(spaces['/'+name][3].get_object()['/C1']),values)

    def test_preview_uses_actual_source_color_and_tint(self):
        from pdf_cut_colors import CutColors
        clean,meta=fixture((0,1,0),name='Shop Green Kiss',operation='kiss',tint=.5)
        colors=CutColors({'doc':(clean,meta)},{'doc':PdfReader(io.BytesIO(clean))},defaults())
        cut=meta['pieces'][0]['cutPaths'][0]
        color=colors.preview_color('doc',cut)
        red,green,blue=[int(color[i:i+2],16) for i in (1,3,5)]
        self.assertEqual(green,255)
        self.assertAlmostEqual(red,128,delta=1)
        self.assertEqual(red,blue)

    def test_broken_saved_color_reference_is_not_silently_replaced(self):
        clean,meta=fixture()
        meta['pieces'][0]['cutPaths'][0]['sourceColor']['resource']='/Missing'
        with self.assertRaisesRegex(ValueError,'original cut color is unavailable'):
            exported({'doc':(clean,meta)})
