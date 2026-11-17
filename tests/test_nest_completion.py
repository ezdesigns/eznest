"""Completion feedback follows successful new runs, not stale or failed jobs."""
import unittest
from playwright.sync_api import sync_playwright, expect
import test_web_mvp
from test_mixed_cuts import mixed_fixture


class NestCompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_web_mvp.WebMvpTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_success_review_restore_and_failed_run(self):
        with sync_playwright() as pw:
            browser,page=self.fixture.open_page(pw)
            try:
                notice=page.locator('#nest-complete')
                expect(notice).to_be_hidden()
                page.select_option('#nesting-effort','5')
                page.set_input_files('#file',{'name':'Completion.pdf','mimeType':'application/pdf','buffer':mixed_fixture(generic=False,registration=False)})
                page.wait_for_function('() => !importing && kits.length === 1')
                expect(notice).to_be_hidden()
                self.fixture.start_nesting(page)
                expect(notice).to_be_visible(timeout=90000)
                expect(notice).to_contain_text('Your nest is complete')
                self.assertEqual(page.get_attribute('body','data-step'),'check')
                self.assertFalse(page.evaluate("document.querySelector('#nest-complete').contains(document.activeElement)"))
                for width,height in [(1280,900),(390,600)]:
                    page.set_viewport_size({'width':width,'height':height})
                    box=notice.bounding_box()
                    self.assertGreaterEqual(box['x'],0)
                    self.assertLessEqual(box['x']+box['width'],width)
                    self.assertLess(box['y']+box['height'],height)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'nest-complete-{width}.png'))
                page.emulate_media(reduced_motion='reduce')
                self.assertEqual(notice.evaluate('n => getComputedStyle(n).animationName'),'none')
                self.assertEqual(page.locator('.nest-complete-check path').evaluate('n => getComputedStyle(n).animationName'),'none')
                page.set_viewport_size({'width':1280,'height':900})
                page.click('#export')
                expect(notice).to_be_hidden()
                self.assertEqual(page.get_attribute('body','data-step'),'confirm')
                page.click('#confirm-back')
                expect(notice).to_be_hidden()
                page.reload();self.fixture.wait_ready(page)
                expect(notice).to_be_hidden()
                page.click('#improve')
                expect(notice).to_be_visible(timeout=90000)
                page.locator('#nest-complete-close').press('Enter')
                self.assertEqual(page.get_attribute('body','data-step'),'check')
                expect(notice).to_be_hidden()
                expect(page.locator('#export')).to_be_focused()
                page.route('**/api/improve',lambda route:route.fulfill(status=400,content_type='application/json',body='{"error":"Test search could not start"}'))
                page.click('#improve')
                expect(page.locator('#status')).to_contain_text('Test search could not start')
                expect(notice).to_be_hidden()
            finally:browser.close()
