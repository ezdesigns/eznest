"""Synthetic dashed-guide review: no customer artwork or automatic exclusions."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from cut_mapping import defaults
from pdf_io import GuideReviewRequired, read_document, import_to_store
from test_mixed_cuts import mixed_fixture


def guide_fixture(forms=False):
    return mixed_fixture(forms=forms, generic=False, extra='q /Thru CS 1 SCN [12] 0 d 5 55 m 140 55 l S Q')


def approval(review):
    return {'id':review['id'], 'sourceHash':review['sourceHash'], 'excludedIds':[line['id'] for line in review['lines']]}


class GuideReviewTests(unittest.TestCase):
    def review(self, raw, mapping=None):
        with self.assertRaises(GuideReviewRequired) as raised:
            read_document(raw, cut_mapping=mapping or defaults())
        return raised.exception.review

    def test_review_keeps_source_and_remaining_cuts_and_print_pixels(self):
        import pypdfium2 as pdfium
        for forms in (False, True):
            raw=guide_fixture(forms); before=hashlib.sha256(raw).hexdigest()
            review=self.review(raw)
            self.assertEqual(len(review['lines']),2)
            self.assertEqual(sum(p['guide'] for p in review['pages'][0]['paths']),2)
            clean,meta=read_document(raw,cut_mapping=defaults(),guide_approval=approval(review))
            baseline,expected=read_document(mixed_fixture(forms=forms,generic=False),cut_mapping=defaults())
            self.assertEqual(len(meta['pieces']),2)
            self.assertEqual(len(meta['excludedGuideIds']),2)
            for actual,old in zip(meta['pieces'],expected['pieces']):
                self.assertEqual(actual['cutCounts'],old['cutCounts'])
                self.assertEqual([p['commands'] for p in actual['cutPaths']],[p['commands'] for p in old['cutPaths']])
            pixels=[]
            for content in (clean,baseline):
                with pdfium.PdfDocument(content) as doc:
                    page=doc[0]; bitmap=page.render(scale=2)
                    try:pixels.append(bitmap.to_pil().tobytes())
                    finally:bitmap.close();page.close()
            self.assertEqual(pixels[0],pixels[1])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),before)

    def test_approval_is_bound_to_all_reviewed_lines_file_and_mapping(self):
        raw=guide_fixture(); accepted=approval(self.review(raw))
        for change in ({'id':'0'*64},{'sourceHash':'0'*64},{'excludedIds':accepted['excludedIds'][:1]},
                       {'excludedIds':accepted['excludedIds']+['p1-cut1']}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'does not match'):
                read_document(raw,cut_mapping=defaults(),guide_approval={**accepted,**change})
        with self.assertRaisesRegex(ValueError,'does not match'):
            read_document(raw+b'\n',cut_mapping=defaults(),guide_approval=accepted)
        changed=defaults();changed['genericOperation']='kiss'
        with self.assertRaisesRegex(ValueError,'does not match'):
            read_document(raw,cut_mapping=changed,guide_approval=accepted)
        with self.assertRaisesRegex(ValueError,'no matching guide review'):
            read_document(mixed_fixture(),cut_mapping=defaults(),guide_approval=accepted)

    def test_multi_page_review_collects_every_candidate_before_grouping(self):
        reader=PdfReader(io.BytesIO(guide_fixture())); writer=PdfWriter()
        writer.add_page(reader.pages[0]);writer.add_page(reader.pages[0]);out=io.BytesIO();writer.write(out)
        raw=out.getvalue();review=self.review(raw)
        self.assertEqual([p['page'] for p in review['pages']],[1,2])
        self.assertEqual(len(set(p['id'] for p in review['lines'])),4)
        _,meta=read_document(raw,cut_mapping=defaults(),guide_approval=approval(review))
        self.assertEqual(len(meta['pieces']),4)

    def test_closed_or_filled_dashed_cuts_still_block(self):
        for paint in ('30 30 10 10 re S','30 30 m 45 40 l B'):
            raw=mixed_fixture(generic=False,extra='q /Thru CS 1 SCN [12] 0 d '+paint+' Q')
            with self.assertRaisesRegex(ValueError,'Dashed') as raised:
                read_document(raw,cut_mapping=defaults())
            self.assertNotIsInstance(raised.exception,GuideReviewRequired)

    def test_no_stored_document_until_review_and_exclusion_is_recorded(self):
        raw=guide_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GuideReviewRequired) as raised:
                import_to_store(raw,tmp,cut_mapping=defaults(),preserve=True)
            self.assertEqual(list(Path(tmp).iterdir()),[])
            parsed=import_to_store(raw,tmp,cut_mapping=defaults(),preserve=True,guide_approval=approval(raised.exception.review))
            meta=json.loads((Path(tmp)/(parsed['documentId']+'.json')).read_text())
            self.assertEqual(parsed['excludedGuideCount'],2)
            self.assertEqual(len(meta['excludedGuideIds']),2)
            self.assertTrue(parsed['artworkPreserved'])
            self.assertEqual(sum(sum(p['cutCounts'].values()) for p in parsed['parts']),6)


if __name__=='__main__':unittest.main()
