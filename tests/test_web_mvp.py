"""Simple web page: sample SVG and PDF nest, lock, and identical re-export."""
import copy
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import server

SCREENSHOTS = Path(__file__).resolve().parents[1] / '.local' / 'screenshots'
SCREENSHOTS.mkdir(parents=True, exist_ok=True)
from test_mixed_cuts import mixed_fixture


def launch_browser(playwright):
    last = None
    for channel in ('chrome', 'msedge'):
        try:
            return playwright.chromium.launch(channel=channel, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        except Exception as error:
            last = error
    raise AssertionError('The web page test needs Google Chrome or Microsoft Edge. ' + str(last))


class WebMvpTests(unittest.TestCase):
    def test_continuous_pdf_review_and_saved_screens_replace_setup(self):
        from playwright.sync_api import sync_playwright, expect
        from pypdf import PdfReader
        with sync_playwright() as playwright:
            browser,page=self.open_page(playwright)
            try:
                page.click('#edit-material')
                page.fill('#width','500')
                page.locator('#material-advanced').evaluate('n => n.open = true')
                page.select_option('#print-layout','continuous')
                page.click('#save-material')
                page.select_option('#nesting-effort','5')
                page.set_input_files('#file',{'name':'order.pdf','mimeType':'application/pdf','buffer':mixed_fixture()})
                page.wait_for_function('() => !importing && kits.length === 1')
                page.locator('#files input').fill('500')
                self.start_nesting(page)
                page.wait_for_function("() => ['check','blocked'].includes(document.body.dataset.step)",timeout=90000)
                self.assertEqual(page.get_attribute('body','data-step'),'check',page.locator('#checks').text_content()+' '+str(server.STATE.get('error')))
                self.assertEqual(len(server.STATE['result']['sheets']),1)
                self.assertEqual(len(server.STATE['result']['placements']),1000)
                self.assertEqual(page.locator('#piece-review-title').inner_text(),'Check 1,000 pieces')
                self.assertEqual(page.locator('#piece-review-count').inner_text(),'2 pieces × 500 copies')
                page.click('#export')
                self.assertEqual(page.input_value('#save-format'),'pdf')
                expect(page.locator('#save-summary')).to_contain_text('1,000 pieces')
                expect(page.locator('.job-panel > h2')).to_be_hidden()
                expect(page.locator('.job-panel > .material-area')).to_be_hidden()
                expect(page.locator('#layout-options')).to_be_hidden()
                page.screenshot(path=str(SCREENSHOTS/'continuous-review-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(SCREENSHOTS/'continuous-review-mobile.png'),full_page=True)
                page.select_option('#save-destination','download')
                with page.expect_download(timeout=90000) as pending:
                    page.click('#confirm-send')
                    expect(page.locator('#confirm-send')).to_be_disabled()
                    expect(page.locator('#status')).to_contain_text('Preparing')
                target=Path(self.tmp.name)/'continuous.pdf';pending.value.save_as(str(target))
                reader=PdfReader(target)
                self.assertEqual(len(reader.pages),1)
                self.assertEqual(reader.pages[0].get_contents().get_data().count(b'\nS\n'),3000)
                expect(page.locator('#saved-heading')).to_be_visible()
                expect(page.locator('.job-panel > h2')).to_be_hidden()
                expect(page.locator('.job-panel > .material-area')).to_be_hidden()
                expect(page.locator('#layout-options')).to_be_hidden()
                page.screenshot(path=str(SCREENSHOTS/'continuous-saved-mobile.png'),full_page=True)
                page.reload();self.wait_ready(page)
                self.assertEqual(page.input_value('#print-layout'),'continuous')
            finally:browser.close()

    def test_section_preview_excludes_neighboring_artwork(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                # The second section starts inside the first section's viewBox
                # padding. It must not appear under the first section's ruler.
                counts = page.evaluate('''() => {
                    const state = {
                        job: {documentSources: {}, parts: [{id:'a', preview:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>', previewWidth:10, previewHeight:10}]},
                        result: {width:100, usedLength:200, placements:[
                            {id:'a', x:5, y:5, rotation:0, sheet:0},
                            {id:'a', x:5, y:101, rotation:0, sheet:1}]},
                        manifest: {sheets:[{index:0,offset:0,usedLength:100},{index:1,offset:100,usedLength:100}]}
                    };
                    return [0,1].map(index => {
                        renderSheet(document.querySelector('#preview'), state, index);
                        const images = [...document.querySelectorAll('#preview image')];
                        return images.map(image => image.parentNode.getAttribute('transform'));
                    });
                }''')
                self.assertEqual(counts, [['translate(5 5) rotate(0)'], ['translate(5 101) rotate(0)']])
            finally:
                browser.close()

    def test_unnamed_cut_review_requires_choice_and_cancel_keeps_job(self):
        from playwright.sync_api import sync_playwright, expect
        from test_sticker_orders import outline_fixture
        with sync_playwright() as playwright:
            browser,page=self.open_page(playwright)
            try:
                page.set_input_files('#file',{'name':'prepared.pdf','mimeType':'application/pdf','buffer':mixed_fixture()})
                page.wait_for_function('() => !importing && kits.length === 1',timeout=15000)
                previous=page.evaluate('kits[0].data.documentId')
                incoming={'name':'stickers.pdf','mimeType':'application/pdf','buffer':outline_fixture()}
                page.set_input_files('#more',incoming)
                expect(page.locator('#cut-review')).to_be_visible(timeout=15000)
                expect(page.locator('#cut-review-accept')).to_be_disabled()
                expect(page.locator('#cut-review-pages path')).to_have_count(2)
                page.screenshot(path=str(SCREENSHOTS/'cut-review-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(SCREENSHOTS/'cut-review-mobile.png'),full_page=True)
                page.keyboard.press('Escape')
                page.wait_for_function('() => !importing')
                self.assertEqual(page.evaluate('kits.length'),1)
                self.assertEqual(page.evaluate('kits[0].data.documentId'),previous)
                page.set_input_files('#more',incoming)
                expect(page.locator('#cut-review')).to_be_visible(timeout=15000)
                page.select_option('#cut-review-operation','kiss')
                page.click('#cut-review-accept')
                page.wait_for_function('() => !importing && kits.length === 2',timeout=15000)
                self.assertEqual(page.evaluate('kits[1].data.parts.map(p => p.cutCounts.kiss)'),[1,1])
            finally:browser.close()

    def test_large_pdf_streams_without_base64_and_keeps_cuts(self):
        from playwright.sync_api import sync_playwright, expect
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
        # Valid inert PDF data exceeds 256 MB without changing the artwork.
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(mixed_fixture())))
        padding = DecodedStreamObject()
        padding.set_data(b'x' * 270_000_000)
        writer.root_object[NameObject('/EZTestPadding')] = writer._add_object(padding)
        path = Path(self.tmp.name) / 'large-prepared.pdf'
        with path.open('wb') as target:
            writer.write(target)
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                uploads = []
                page.on('request', lambda r: uploads.append(r) if '/api/document/import' in r.url else None)
                page.set_input_files('#file', str(path))
                page.wait_for_function('() => !importing && kits.length === 1', timeout=120000)
                self.assertEqual(len(uploads), 1)
                self.assertTrue(uploads[0].url.endswith('/api/document/import-file'))
                self.assertEqual(uploads[0].headers['content-type'], 'application/pdf')
                expect(page.locator('#status')).not_to_contain_text('MB limit')
                self.assertEqual(page.evaluate('kits[0].data.parts.length'), 2)
                self.assertEqual(page.evaluate('kits[0].data.parts.map(p => p.cutCounts)'),
                                 [{'thru':1,'kiss':2,'contour':0}] * 2)
            finally:
                browser.close()

    def test_centered_dialogs_cancel_edits_and_output_invitation_keeps_job(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.select_option('#nesting-effort', '5')
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'", timeout=90000)
                before = json.load(urlopen(self.url() + '/api/state'))
                page.locator('#in-house').focus()
                page.keyboard.press('Enter')
                expect(page.locator('#nesting-effort')).to_be_focused()
                expect(page.locator('#confirm')).to_be_hidden()
                saved_width = page.input_value('#width')
                writes = []
                page.on('request', lambda r: writes.append(r.url) if r.method == 'POST' else None)
                page.click('#edit-material')
                page.fill('#width', '123')
                page.mouse.click(8, 8)
                expect(page.locator('#material-dialog')).not_to_be_visible()
                self.assertEqual(page.input_value('#width'), saved_width)
                page.click('#edit-material')
                page.fill('#width', '124')
                # A drag out of the field is not a backdrop click.
                field = page.locator('#width').bounding_box()
                page.mouse.move(field['x'] + 10, field['y'] + 10)
                page.mouse.down(); page.mouse.move(8, 8); page.mouse.up()
                expect(page.locator('#material-dialog')).to_be_visible()
                page.keyboard.press('Escape')
                self.assertEqual(page.input_value('#width'), saved_width)
                page.click('#settings-open')
                self.assertTrue(page.locator('#settings').evaluate("n => n.matches(':modal')"))
                box = page.locator('#settings').bounding_box()
                self.assertAlmostEqual(box['x'] + box['width']/2, 640, delta=2)
                self.assertAlmostEqual(box['y'] + box['height']/2, 450, delta=2)
                for _ in range(8):
                    page.keyboard.press('Tab')
                    self.assertTrue(page.locator('#settings').evaluate('n => n.contains(document.activeElement)'))
                page.mouse.click(8, 8)
                expect(page.locator('#settings')).not_to_be_visible()
                effort = page.input_value('#nesting-effort')
                self.assertEqual(page.locator('#in-house').get_attribute('aria-pressed'), 'true')
                expect(page.locator('#in-house')).to_have_text('In-house')
                expect(page.locator('#max-output')).to_contain_text("Don't print")
                self.assertEqual(page.locator('#max-output').get_attribute('aria-label'), "Don't print. Still get paid. Learn about OUTPUT")
                self.assertEqual(page.locator('#max-output').get_attribute('aria-pressed'), 'false')
                self.assertEqual(page.locator('#max-output').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(243, 251, 246)')
                self.assertEqual(page.locator('#in-house').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(239, 245, 255)')
                pill = page.locator('#max-output .paid-badge')
                self.assertEqual(pill.inner_text(), 'Still get paid 🤑')
                self.assertEqual(pill.evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(21, 128, 61)')
                self.assertNotEqual(pill.evaluate('n => getComputedStyle(n).color'), 'rgb(217, 47, 0)')
                self.assertNotEqual(pill.evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(217, 47, 0)')
                page.click('#max-output .paid-badge')
                expect(page.locator('#max-output-dialog')).to_be_visible()
                expect(page.locator('#max-output-close')).to_be_focused()
                self.assertTrue(page.locator('#max-output-dialog').evaluate("n => n.matches(':modal')"))
                expect(page.locator('#max-output-title')).to_have_text("Don't print!")
                dialog_text = page.locator('#max-output-dialog').inner_text()
                self.assertIn('Have AI route the job to the best print shop near you, based on what each shop can make.', dialog_text)
                self.assertIn('You still get paid.', dialog_text)
                self.assertIn('Why use it?', dialog_text)
                self.assertIn('You don\'t have enough material', dialog_text)
                self.assertIn('Your customer is too far away', dialog_text)
                self.assertIn('You\'re too busy to hit the date', dialog_text)
                self.assertIn('You need to focus on another job', dialog_text)
                self.assertNotIn('What is OUTPUT?', dialog_text)
                self.assertNotIn('Use it when', dialog_text)
                self.assertNotIn('You stay the shop your customer knows', dialog_text)
                self.assertNotIn('otherwise turn away', dialog_text)
                self.assertNotIn('Can\'t print it? Another shop can.', dialog_text)
                self.assertNotIn('Too many pieces', dialog_text)
                self.assertNotIn('never contacts', dialog_text.lower())
                self.assertNotIn('Early pilot.', dialog_text)
                self.assertNotIn('More revenue', dialog_text)
                self.assertNotIn('Route the print.', dialog_text)
                self.assertNotIn('How it works', dialog_text)
                self.assertEqual(page.locator('#max-output-dialog .waitlist-note').count(), 0)
                waitlist = page.locator('#max-output-waitlist')
                learn = page.locator('#max-output-learn')
                self.assertEqual(waitlist.inner_text(), 'Join the waitlist')
                self.assertEqual(learn.inner_text(), 'Learn more')
                self.assertEqual(page.locator('.output-points li').count(), 4)
                self.assertEqual(page.locator('#max-output-dialog .paid-line').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(21, 128, 61)')
                root = Path(__file__).resolve().parents[1]
                self.assertEqual((root / 'web.js').read_text().count('https://output.jeezlabs.io/'), 1)
                self.assertNotIn('https://output.jeezlabs.io/', (root / 'web.html').read_text())
                for link in (waitlist, learn):
                    self.assertEqual(link.get_attribute('href'), 'https://output.jeezlabs.io/')
                    self.assertEqual(link.get_attribute('target'), '_blank')
                    self.assertIn('noopener', link.get_attribute('rel'))
                    self.assertEqual(link.get_attribute('referrerpolicy'), 'no-referrer')
                self.assertEqual(waitlist.evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(17, 17, 17)')
                box = page.locator('#max-output-dialog').bounding_box()
                self.assertAlmostEqual(box['x'] + box['width'] / 2, 640, delta=2)
                page.set_viewport_size({'width': 390, 'height': 844})
                box = page.locator('#max-output-dialog').bounding_box()
                self.assertGreaterEqual(box['x'], 0)
                self.assertLessEqual(box['x'] + box['width'], 390)
                page.keyboard.press('Escape')
                expect(page.locator('#max-output-dialog')).to_be_hidden()
                self.assertEqual(page.locator('#in-house').get_attribute('aria-pressed'), 'true')
                self.assertEqual(page.input_value('#nesting-effort'), effort)
                self.assertEqual(json.load(urlopen(self.url() + '/api/state'))['id'], before['id'])
                self.assertEqual(page.input_value('#sets'), '1')
                self.assertEqual(writes, [])
            finally:
                browser.close()

    def set_legacy_width(self, page, value):
        # Restored jobs still carry their original width. The simple page edits
        # new widths through the material dialog, not this hidden compatibility field.
        page.locator('#nest-width').evaluate("(node, value) => { node.value = value; node.dispatchEvent(new Event('input', {bubbles:true})); }", value)

    def test_simple_flow_has_one_quantity_and_material_width(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                expect(page.locator('#start-nesting')).to_be_visible()
                expect(page.locator('#start-nesting')).to_be_disabled()
                expect(page.locator('.upload-icon')).to_be_visible()
                expect(page.locator('#job-options')).to_be_hidden()
                expect(page.locator('#width-override')).to_be_hidden()
                expect(page.locator('.how-it-works')).to_have_count(0)
                expect(page.locator('#in-house')).to_contain_text('In-house')
                page.click('#edit-material')
                page.fill('#width', '240')
                page.click('#save-material')
                self.assertAlmostEqual(float(page.input_value('#nest-width')) * 25.4, 240, places=1)
                page.select_option('#nesting-effort', '5')
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                expect(page.locator('#files input[type=number]')).to_be_visible()
                expect(page.locator('#start-nesting')).to_be_enabled(timeout=15000)
                page.locator('#files input[type=number]').fill('2')
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'", timeout=90000)
                result = json.load(urlopen(self.url() + '/api/state'))
                self.assertEqual(len(result['result']['placements']), 8)
                self.assertAlmostEqual(result['result']['width'], 240, places=1)
            finally:
                browser.close()

    def start_nesting(self, page):
        page.wait_for_function("() => !importing", timeout=30000)
        if page.get_attribute('body', 'data-step') == 'configure':
            # Import and edits must wait for the operator; never save a stale fit.
            self.assertTrue(page.locator('#export').is_disabled())
            if page.locator('#start-nesting').is_enabled():
                page.locator('#settings').evaluate('node => node.close()')
                page.click('#start-nesting')

    def test_guide_review_cancel_failure_and_confirm_preserve_current_job(self):
        from playwright.sync_api import sync_playwright, expect
        from test_guide_review import guide_fixture
        with sync_playwright() as playwright:
            browser,page=self.open_page(playwright)
            try:
                page.locator('#layout-options').evaluate('n => { n.open = true }')
                page.select_option('#nesting-effort','5')
                page.set_input_files('#file',{'name':'prepared.pdf','mimeType':'application/pdf','buffer':mixed_fixture()})
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
                before=json.load(urlopen(self.url()+'/api/state'))
                page.set_input_files('#more',{'name':'broken.pdf','mimeType':'application/pdf','buffer':b'not a PDF'})
                expect(page.locator('#status')).to_contain_text('broken.pdf:')
                expect(page.locator('#export')).to_be_enabled()
                self.assertEqual(json.load(urlopen(self.url()+'/api/state'))['id'],before['id'])
                incoming={'name':'possible-guides.pdf','mimeType':'application/pdf','buffer':guide_fixture()}
                page.set_input_files('#more',incoming)
                expect(page.locator('#guide-review')).to_be_visible(timeout=15000)
                expect(page.locator('#guide-pages .possible-guide')).to_have_count(2)
                expect(page.locator('#guide-cancel')).to_be_focused()
                expect(page.locator('#export')).to_be_disabled()
                expect(page.locator('#more')).to_be_disabled()
                page.screenshot(path=str(SCREENSHOTS/'guide-review-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.screenshot(path=str(SCREENSHOTS/'guide-review-mobile.png'),full_page=True)
                page.keyboard.press('Escape')
                expect(page.locator('#guide-review')).to_be_hidden()
                expect(page.locator('#export')).to_be_enabled()
                expect(page.locator('#improve')).to_be_enabled()
                self.assertEqual(json.load(urlopen(self.url()+'/api/state'))['id'],before['id'])
                expect(page.locator('#files li')).to_have_count(1)
                page.set_viewport_size({'width':1280,'height':900})
                # A multi-file selection commits only after every file is accepted.
                page.set_input_files('#more',[{'name':'extra.pdf','mimeType':'application/pdf','buffer':mixed_fixture()},incoming])
                expect(page.locator('#guide-review')).to_be_visible(timeout=15000)
                page.click('#guide-cancel')
                expect(page.locator('#files li')).to_have_count(1)
                self.assertEqual(json.load(urlopen(self.url()+'/api/state'))['id'],before['id'])
                page.set_input_files('#more',incoming)
                expect(page.locator('#guide-review')).to_be_visible(timeout=15000)
                page.click('#guide-exclude')
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check' && document.querySelector('#checks').textContent.includes('2 guides excluded')",timeout=90000)
                after=json.load(urlopen(self.url()+'/api/state'))
                self.assertNotEqual(after['id'],before['id'])
                self.assertEqual(len(after['job']['productionJobs']),2)
                self.assertEqual(len(after['job']['parts']),4)
                self.assertEqual(sum(sum(p['cutCounts'].values()) for p in after['job']['parts']),12)
                expect(page.locator('#export')).to_be_enabled()
                page.reload();self.wait_ready(page)
                expect(page.locator('#checks')).to_contain_text('2 guides excluded')
                expect(page.locator('#export')).to_be_enabled()
            finally:browser.close()

    def test_tester_savings_feedback_and_optional_setup(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser=launch_browser(playwright)
            page=browser.new_page(viewport={'width':1280,'height':900},accept_downloads=True)
            try:
                page.goto(self.url()+'/web'); self.wait_ready(page)
                page.click('#setup-save')
                expect(page.locator('#setup')).to_be_hidden()
                self.assertIsNone(server.OUTPUT.root)
                page.click('#edit-material')
                page.fill('#roll-length','1200'); page.fill('#roll-cost','300')
                page.click('#save-material')
                page.locator('#layout-options').evaluate('n => { n.open = true }')
                page.select_option('#nesting-effort','5')
                sample=Path(__file__).resolve().parents[1]/'sample-artwork.svg'
                page.set_input_files('#file', {'name':'sample-artwork-long-job-name-for-quantity-review.svg',
                                             'mimeType':'image/svg+xml','buffer':sample.read_bytes()})
                try:
                    self.start_nesting(page)
                    page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
                except Exception:
                    detail=page.evaluate("() => ({step:document.body.dataset.step,status:document.querySelector('#status').textContent,checks:document.querySelector('#checks').textContent})")
                    raise AssertionError('Tester job did not finish: '+json.dumps(detail)+'; '+str(server.STATE.get('error'))) from None
                state=json.load(urlopen(self.url()+'/api/state'))
                self.assertEqual(state['job']['webOptions']['rollCost'],300)
                area=(54*25.4/1000)*(1200*25.4/1000)
                self.assertAlmostEqual(state['job']['settings']['costPerSquareMeter'], 300/area, places=6)
                self.assertEqual(page.locator('#previous-length').count(),0)
                expect(page.locator('#nest-savings')).to_be_hidden()
                server.STATE['nestSavings']={'baselineLengthMm':state['result']['usedLength']+304.8}
                page.reload();self.wait_ready(page)
                expect(page.locator('#savings-value')).to_have_text('$3.00 saved')
                expect(page.locator('#savings-context')).to_contain_text('1.00 ft')
                page.click('#piece-review summary')
                expect(page.locator('.piece-card')).to_have_count(len(state['job']['parts']))
                self.assertEqual(page.locator('.piece-card strong').all_text_contents(),[p['name'] for p in state['job']['parts']])
                page.reload();self.wait_ready(page)
                self.assertEqual(page.input_value('#roll-cost'),'300')
                expect(page.locator('#savings-value')).to_have_text('$3.00 saved')
                # Core result and Save action fit on a common shop laptop display.
                page.set_viewport_size({'width':1366,'height':768})
                page.evaluate('scrollTo(0, 0)')
                save_box=page.locator('#export').bounding_box()
                self.assertLessEqual(save_box['y']+save_box['height'],768)
                self.assertGreaterEqual(save_box['y'],0)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                self.assertEqual(page.locator('.job-panel select[aria-label="Material"]:visible').count(),1)
                self.assertTrue(page.locator('.file-name').evaluate('n => n.scrollWidth <= n.clientWidth && n.scrollHeight <= n.clientHeight'))
                page.screenshot(path=str(SCREENSHOTS/'tester-savings-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(SCREENSHOTS/'tester-savings-mobile.png'),full_page=True)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.click('#feedback-open')
                self.assertFalse(page.is_checked('#feedback-numbers'))
                page.fill('#feedback-message','Make preview larger')
                self.assertNotIn('lengthFt',page.text_content('#feedback-preview'))
                page.check('#feedback-numbers')
                preview=page.text_content('#feedback-preview')
                self.assertIn('lengthFt:',preview)
                self.assertNotIn('sample-artwork',preview)
                self.assertNotIn(state['id'],preview)
                page.click('#feedback-dialog details summary')
                page.locator('#feedback-download').focus()
                with page.expect_download() as download:page.keyboard.press('Enter')
                self.assertEqual(download.value.suggested_filename,'EZ-Nest-feedback.txt')
                self.assertFalse(json.load(urlopen(self.url()+'/api/state')).get('released'))
                page.screenshot(path=str(SCREENSHOTS/'tester-feedback-mobile.png'),full_page=True)
                page.click('#feedback-close');page.click('#feedback-open')
                self.assertFalse(page.is_checked('#feedback-numbers'))
            finally:browser.close()

    def test_piece_review_and_saved_effort_do_not_replace_layout(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser,page=self.open_page(playwright)
            try:
                page.locator('#layout-options').evaluate('n => { n.open = true }')
                page.select_option('#nesting-effort','5')
                page.set_input_files('#file',str(Path(__file__).resolve().parents[1]/'sample-artwork.svg'))
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
                before=json.load(urlopen(self.url()+'/api/state'))
                self.assertEqual(before['job']['settings']['seconds'],5)
                page.click('#piece-review summary')
                expect(page.locator('.piece-card')).to_have_count(len(before['job']['parts']))
                page.wait_for_function("() => [...document.querySelectorAll('.piece-card img')].every(i => i.complete && i.naturalWidth > 0)")
                self.assertEqual(page.locator('.piece-quantity').all_text_contents(),[f"{p['quantity']} of {p['quantity']} copies" for p in before['job']['parts']])
                page.locator('#layout-options').evaluate('n => { n.open = true }')
                page.select_option('#nesting-effort','90')
                self.assertEqual(json.load(urlopen(self.url()+'/api/state'))['id'],before['id'])
                page.reload();self.wait_ready(page)
                self.assertEqual(page.input_value('#nesting-effort'),'90')
                expect(page.locator('#effort-summary')).to_have_text('Best fit · 90 seconds')
                self.assertTrue(page.locator('#nesting-effort').is_visible())
                self.assertEqual(json.load(urlopen(self.url()+'/api/state'))['id'],before['id'])
                page.click('#piece-review summary')
                page.screenshot(path=str(SCREENSHOTS/'piece-review-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(SCREENSHOTS/'piece-review-mobile.png'),full_page=True)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.set_viewport_size({'width':1280,'height':900})
                page.click('#improve')
                page.wait_for_function("() => document.body.dataset.step === 'nest'")
                self.assertEqual(json.load(urlopen(self.url()+'/api/state'))['job']['settings']['seconds'],90)
                page.click('#stop')
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=10000)
                after=json.load(urlopen(self.url()+'/api/state'))
                self.assertLessEqual(after['result']['usedLength'],before['result']['usedLength'])
                self.assertEqual(after['job']['parts'],before['job']['parts'])
            finally:
                browser.close()

    def test_tighter_fit_keyboard_action_and_stop_preserve_best(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser,page=self.open_page(playwright)
            try:
                self.assertEqual(page.input_value('#seconds'),'30')
                page.locator('#seconds').evaluate("node => node.value = '1'")
                page.set_input_files('#file',str(Path(__file__).resolve().parents[1]/'sample-artwork.svg'))
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
                before=json.load(urlopen(self.url()+'/api/state'))
                expect(page.locator('#improve')).to_be_visible()
                page.locator('#improve').focus()
                with page.expect_response(lambda r:r.url.endswith('/api/improve')) as request:
                    page.keyboard.press('Enter')
                self.assertEqual(request.value.status,200)
                self.assertNotEqual(page.get_attribute('body','data-step'),'confirm')
                page.click('#stop')
                self.start_nesting(page)
                page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=10000)
                after=json.load(urlopen(self.url()+'/api/state'))
                self.assertLessEqual(after['result']['usedLength'],before['result']['usedLength'])
                self.assertEqual(after['job']['parts'],before['job']['parts'])
                self.assertEqual(after['job']['settings']['rotations'],before['job']['settings']['rotations'])
                page.screenshot(path=str(SCREENSHOTS/'tighter-fit-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(SCREENSHOTS/'tighter-fit-mobile.png'),full_page=True)
            finally:
                browser.close()

    def test_low_stock_threshold_restock_units_and_refresh(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                self.assertEqual(page.locator('.stock-alert').count(), 0)
                page.click('#edit-material')
                page.select_option('#unit', 'in')
                page.fill('#roll-length', '1000')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '100')
                page.click('#save-material')
                expect(page.locator('.stock-alert')).to_have_text('Low stock · 100 in left')
                page.screenshot(path=str(SCREENSHOTS / 'low-stock-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'low-stock-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.reload(); self.wait_ready(page)
                expect(page.locator('.stock-alert')).to_have_text('Low stock · 100 in left')
                page.click('#edit-material')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#low-stock', '50')
                page.click('#save-material')
                self.assertEqual(page.locator('.stock-alert').count(), 0)
                page.click('#edit-material')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '50')
                page.select_option('#unit', 'mm')
                self.assertEqual(page.input_value('#low-stock'), '1270')
                page.click('#save-material')
                expect(page.locator('.stock-alert')).to_have_text('Low stock · 1270 mm left')
                page.click('#edit-material')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '0')
                page.click('#save-material')
                expect(page.locator('.stock-alert')).to_have_text('Out of stock · 0 mm left')
                page.reload(); self.wait_ready(page)
                expect(page.locator('.stock-alert')).to_have_text('Out of stock · 0 mm left')
                page.click('#edit-material')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '2000')
                page.click('#save-material')
                self.assertEqual(page.locator('.stock-alert').count(), 0)
                page.click('#edit-material')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '')
                page.click('#save-material')
                self.assertEqual(page.locator('.stock-alert').count(), 0)
            finally:
                browser.close()

    def test_windows_save_cancel_save_and_retained_receipt(self):
        from playwright.sync_api import sync_playwright, expect
        source = Path(self.tmp.name) / 'kit.pdf'
        original = mixed_fixture()
        source.write_bytes(original)
        folder = Path(self.tmp.name) / 'chosen'
        folder.mkdir()
        target = folder / 'Renamed kit.pdf'
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.evaluate('localSave = true')
                page.set_input_files('#file', str(source))
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                page.click('#export')
                self.assertEqual(page.input_value('#save-destination'), 'choose')
                expect(page.locator('#save-name-row')).not_to_be_visible()
                with patch('print_export.pick_save_path', return_value=None) as picker:
                    page.click('#confirm-send')
                    expect(page.locator('#confirm-send')).to_be_enabled()
                    picker.assert_called_once_with('kit', 'pdf')
                self.assertEqual(page.get_attribute('body', 'data-step'), 'confirm')
                self.assertTrue(page.locator('#delivery-receipt').is_hidden())
                self.assertFalse(server.STATE.get('released'))
                self.assertFalse(target.exists())
                expect(page.locator('#folder-picker')).not_to_be_visible()
                with patch('print_export.pick_save_path', return_value=str(target.resolve())):
                    page.click('#confirm-send')
                    expect(page.locator('#delivery-receipt')).to_have_text('Saved to ' + str(target.resolve()))
                self.assertTrue(target.read_bytes().startswith(b'%PDF'))
                self.assertFalse(server.STATE['deliveryCompleted'])
                self.assertIsNone(server.STATE.get('savedPath'))
                self.assertEqual(source.read_bytes(), original)
                page.reload(); self.wait_ready(page)
                expect(page.locator('#delivery-receipt')).to_have_text('Saved to ' + str(target.resolve()))
                self.assertEqual(page.locator('#status').inner_text(), '')
                page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                page.click('#browse-output')
                page.fill('#folder-path', str(folder))
                page.click('#folder-go')
                expect(page.locator('#folder-use')).to_be_enabled()
                page.click('#folder-use')
                expect(page.locator('#folder-picker')).not_to_be_visible()
                self.assertEqual(server.OUTPUT.root, folder.resolve())
                page.reload(); self.wait_ready(page)
                page.click('#export')
                self.assertEqual(page.input_value('#save-destination'), 'folder')
                self.assertEqual(page.input_value('#save-name'), 'Renamed kit')
            finally:
                browser.close()

    def setUp(self):
        self.old = (server.WORK, server.PORT, server.HOST, copy.deepcopy(server.STATE), server.PROCESS)
        self.old_output = server.OUTPUT
        self.tmp = tempfile.TemporaryDirectory()
        server.WORK = Path(self.tmp.name)
        server.OUTPUT = server.OutputFolder(server.WORK / 'output-folder.json')
        server.STATE.clear()
        server.STATE.update(status='idle')
        server.PROCESS = None
        self.service = None
        self.thread = None
        self.start()

    def start(self):
        self.service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = self.service.server_port
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        last = None
        while time.monotonic() < deadline:
            try:
                with urlopen(self.url() + '/api/session', timeout=0.2) as response:
                    if response.status == 200:
                        return
            except OSError as error:
                last = error
                time.sleep(0.02)
        raise RuntimeError('eznest did not accept connections. ' + str(last))

    def stop(self):
        if server.PROCESS and server.PROCESS.poll() is None:
            server.PROCESS.terminate()
            server.PROCESS.wait(timeout=5)
        server.PROCESS = None
        if server.DOCUMENT_LOCK.locked():
            server.DOCUMENT_LOCK.release()
        if self.service:
            self.service.shutdown()
            self.service.server_close()
            self.thread.join(timeout=5)
            self.service = None

    def tearDown(self):
        self.stop()
        server.WORK, server.PORT, server.HOST, previous, server.PROCESS = self.old
        server.OUTPUT = self.old_output
        server.STATE.clear()
        server.STATE.update(previous)
        self.tmp.cleanup()

    def url(self):
        return f'http://127.0.0.1:{server.PORT}'

    def wait_ready(self, page):
        # Boot sets this only after the shop stylesheet is on the page and the
        # session call has returned. An empty status line was that signal never arriving.
        try:
            page.wait_for_function("() => document.body.dataset.ready === '1'")
            # Most tests exercise the browser fallback; chooser coverage opts in.
            page.evaluate('localSave = false')
        except Exception:
            detail = page.evaluate(
                "() => JSON.stringify({ready: document.body && document.body.dataset.ready || '',"
                " alarm: getComputedStyle(document.documentElement).getPropertyValue('--alarm').trim(),"
                " status: (document.querySelector('#status') || {}).textContent || ''})"
            )
            raise AssertionError('Shop page was not ready. ' + detail) from None

    def test_desktop_workspace_remains_the_front_page(self):
        with urlopen(self.url() + '/', timeout=10) as response:
            desktop = response.read().decode()
        with urlopen(self.url() + '/web', timeout=10) as response:
            page = response.read().decode()
        self.assertIn('Nest selected jobs', desktop)
        self.assertIn('href="/web"', desktop)
        self.assertIn('Upload your print here', page)
        self.assertIn('Stop · keep best', page)
        self.assertIn('id="files"', page)
        self.assertIn('Add files', page)
        self.assertIn('max="800"', page)
        self.assertNotIn('id="nest"', page)
        self.assertIn('/svg-io.js', page)
        self.assertNotIn('<script>', page.lower().split('<body', 1)[-1].replace('src=', ''))

    def open_page(self, playwright, shots=False):
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        page.goto(self.url() + '/web', wait_until='domcontentloaded')
        self.wait_ready(page)
        page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
        self.assertEqual(page.locator('#material option:checked').inner_text(), 'Moto Regular')
        self.assertEqual(page.input_value('#width'), '51.5')
        self.assertEqual(page.input_value('#nest-width'), '51.5')
        self.assertIn('on 51.5" wide', page.locator('#used-width').inner_text())
        self.assertEqual(page.input_value('#roll'), '54')
        self.assertEqual(page.input_value('#mark-margin'), '0.4')
        self.assertEqual(page.input_value('#sheet'), '60')
        self.assertEqual(page.input_value('#auto-bleed'), '0')
        self.assertEqual(page.input_value('#thru-name'), 'CutContour_Thru-cut')
        self.assertEqual(page.input_value('#kiss-name'), 'CutContour_Kiss-cut')
        self.assertEqual(page.input_value('#material'), 'white-gloss')
        self.assertGreaterEqual(page.locator('#material option').count(), 4)
        self.assertFalse(page.locator('#staging-on').is_checked())
        self.assertEqual(page.locator('#material option[value="white-gloss"]').get_attribute('data-quickset'), 'Substance Gloss GL [EZ Designs 80600] @ 720-CT')
        self.assertEqual(page.locator('#material option[value="white-gloss"]').get_attribute('data-printer'), 'Epson S80600')
        self.assertFalse(page.locator('#draw-marks').is_checked())
        self.assertIn('EPSON SureColor S80600 ONYX Input', page.locator('#settings').inner_text())
        page.select_option('#cut-preset', 'ln')
        self.assertEqual(page.input_value('#thru-name'), 'LNThru-cut')
        self.assertEqual(page.input_value('#kiss-name'), 'LNKiss-cut')
        page.select_option('#cut-preset', 'output')
        self.assertEqual(page.input_value('#thru-name'), 'CutContour_Thru-cut')
        self.assertEqual(page.input_value('#kiss-name'), 'CutContour_Kiss-cut')
        if shots:
            page.locator('#settings .panel').evaluate('node => { node.style.maxHeight = "none"; node.style.overflow = "visible"; }')
            page.screenshot(path=str(SCREENSHOTS / 'eznest-gear-desktop.png'))
            page.locator('#settings .panel').screenshot(path=str(SCREENSHOTS / 'eznest-gear-panel-desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 900})
            page.screenshot(path=str(SCREENSHOTS / 'eznest-gear-mobile.png'))
            page.locator('#settings .panel').screenshot(path=str(SCREENSHOTS / 'eznest-gear-panel-mobile.png'))
            page.set_viewport_size({'width': 1280, 'height': 900})
        page.locator('#settings').evaluate('node => node.close()')
        page.click('#edit-material')
        page.select_option('#unit', 'mm')
        page.fill('#width', '220')
        page.locator('#material-advanced').evaluate('n => { n.open = true }')
        page.fill('#gap', '3')
        page.locator('#material-advanced').evaluate('n => { n.open = true }')
        page.fill('#margin', '5')
        page.click('#save-material')
        self.assertTrue(page.locator('#preset-editor').is_hidden())
        return browser, page

    def download(self, page, shortcut=False):
        page.evaluate('localSave = false')
        with page.expect_download(timeout=30000) as pending:
            if shortcut:
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.keyboard.press('Enter')
            else:
                page.click('#export')
            page.select_option('#save-destination', 'download')
            page.select_option('#save-format', 'pack')
            page.locator('#confirm-send').click()
        item = pending.value
        target = Path(self.tmp.name) / (item.suggested_filename or 'eznest.zip')
        item.save_as(str(target.resolve()))
        return target.read_bytes()

    def test_settings_help_and_save_feedback(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                info = page.locator('#settings').get_by_role('button', name='About Through-cut name', exact=True)
                original = page.input_value('#thru-name')
                info.hover()
                expect(page.get_by_role('tooltip')).to_contain_text('does not set the blade depth')
                page.keyboard.press('Escape')
                expect(page.get_by_role('tooltip')).to_be_hidden()
                info.focus()
                expect(page.get_by_role('tooltip')).to_be_visible()
                page.keyboard.press('Enter')
                self.assertEqual(page.input_value('#thru-name'), original)
                self.assertEqual(page.locator('body').get_attribute('data-step'), 'drop')
                self.assertEqual(page.locator('.setting-info').count(), 0)
                self.assertEqual(page.get_by_text('Known limits', exact=True).count(), 0)
                self.assertEqual(page.get_by_text('Import help', exact=True).count(), 0)
                expect(page.get_by_role('heading', name='1 Upload job')).to_be_visible()
                expect(page.locator('#max-output')).to_be_enabled()
                page.keyboard.press('Escape')
                page.set_viewport_size({'width': 390, 'height': 844})
                info.click()
                expect(page.get_by_role('tooltip')).to_be_visible()
                box = page.get_by_role('tooltip').bounding_box()
                self.assertGreaterEqual(box['x'], 0)
                self.assertLessEqual(box['x'] + box['width'], 390)
                self.assertGreaterEqual(box['y'], 0)
                self.assertLessEqual(box['y'] + box['height'], 844)
                page.keyboard.press('Escape')
                page.select_option('#generic-cut', 'kiss')
                page.click('#save-settings')
                expect(page.locator('#settings-saved')).to_have_text('Saved.')
                page.reload(); self.wait_ready(page)
                self.assertEqual(page.input_value('#generic-cut'), 'kiss')
                page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                page.route('**/api/output/connect', lambda route: route.fulfill(status=400, content_type='application/json', body='{"error":"Test folder unavailable"}'))
                page.click('#save-settings')
                expect(page.locator('#settings-saved')).to_contain_text('Could not save all settings. Test folder unavailable')
                page.unroute('**/api/output/connect')
                page.evaluate("() => { Storage.prototype.setItem = () => { throw new Error('storage blocked'); }; }")
                page.click('#save-settings')
                expect(page.locator('#settings-saved')).to_contain_text('This browser could not save your preferences')
                expect(page.locator('#save-settings')).to_be_enabled()
                expect(page.locator('#lan')).to_be_disabled()
            finally:
                browser.close()

    def test_sample_svg_nests_locks_and_reexports(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright, shots=True)
            try:
                page.locator('#settings').evaluate('node => node.close()')
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-empty.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-empty.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                self.assertEqual(page.locator('#sheets .num').inner_text().strip(), '1')
                self.assertIn('ft', page.locator('#length').inner_text().casefold())
                state = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertAlmostEqual(state['result']['width'], 220, places=2)
                self.assertAlmostEqual(state['job']['settings']['markMargin'], 10.16, places=1)
                self.assertAlmostEqual(state['job']['settings']['margin'], 15.16, places=1)
                self.assertAlmostEqual(state['job']['settings']['sheetLength'], 1524, places=0)
                self.assertEqual(state['job']['media']['hotFolderLabel'], 'EPSON SureColor S80600 ONYX Input')
                self.assertAlmostEqual(state['job']['media']['printableWidthMm'], 220, places=2)
                self.assertFalse(state['job']['settings']['drawRegmarks'])
                shown = float(page.locator('#waste .num').inner_text())
                self.assertEqual(round(shown), round((1 - state['result']['utilization']) * 100))
                self.assertEqual((page.locator('#preview [id*="Kiss-cut"]').first.get_attribute('stroke') or '').lower(), '#e6007e')
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                self.assertEqual(page.locator('#sheet-id').text_content(), state['id'])
                self.assertTrue(page.locator('#sheet-id').is_hidden())
                self.assertNotIn('problem', page.locator('#gate').get_attribute('class') or '')
                self.assertEqual(page.locator('#lock').count(), 0)
                self.assertEqual(page.locator('#export').inner_text(), 'Review and save')
                page.locator('#settings').evaluate('node => node.close()')
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.keyboard.press('Space')
                self.assertFalse(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
                page.screenshot(path=str(SCREENSHOTS / 'eznest-web-desktop.png'), full_page=True)
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-ready.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-web-mobile.png'), full_page=True)
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-ready.png'), full_page=True)
                box = page.locator('#export').bounding_box()
                self.assertLessEqual(box['x'] + box['width'], 390)
                page.set_viewport_size({'width': 1280, 'height': 900})
                first = self.download(page, shortcut=True)
                page.wait_for_function("() => /^[a-f0-9]{64}$/.test(document.querySelector('#layout-hash').value)")
                digest = page.locator('#layout-hash').input_value()
                ident = page.locator('#layout-id').input_value()
                self.assertEqual(hashlib.sha256(first).hexdigest(), digest)
                second = self.download(page)
                self.assertEqual(first, second)
                with ZipFile(io.BytesIO(first)) as archive:
                    artwork = archive.read('artwork.svg').decode('utf-8')
                self.assertIn('CutContour_Kiss-cut', artwork)
                self.assertIn('M0 0L62 55H0Z', artwork)
                self.assertIn('#dd38b8', artwork)
                self.assertNotIn('#D92F00', artwork)
                self.assertIn('clipPath', artwork)
                self.assertNotIn('data-ezn-bleed', artwork)
                self.assertIn(ident, artwork)
                self.assertNotIn('LNRegmark', artwork)
                self.assertNotIn('barcode', artwork.casefold())
                self.stop()
                server.STATE.clear()
                server.restore_state()
                self.start()
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                page.wait_for_function("(hash) => document.querySelector('#layout-hash').value === hash", arg=digest, timeout=15000)
                self.assertEqual(page.locator('#layout-id').input_value(), ident)
                self.assertIn('kiss', page.locator('#checks').inner_text().casefold())
                restored = self.download(page)
                self.assertEqual(restored, first)
            finally:
                browser.close()

    def test_pdf_export_keeps_named_cut_spots(self):
        from playwright.sync_api import sync_playwright
        source = Path(self.tmp.name) / 'kit.pdf'
        source.write_bytes(mixed_fixture())
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.set_input_files('#file', str(source))
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                self.assertIn('thru', page.locator('#checks').inner_text().casefold())
                self.assertIn('kiss', page.locator('#checks').inner_text().casefold())
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                self.assertEqual(page.locator('#preview .preview-cut[data-operation="thru"]').count(), 2)
                self.assertEqual(page.locator('#preview .preview-cut[data-operation="kiss"]').count(), 4)
                cut_width = page.locator('#preview .preview-cut[data-operation="thru"]').first.evaluate('node => node.getBBox().width')
                self.assertAlmostEqual(cut_width, 100*25.4/72, places=4)
                first = self.download(page)
                second = self.download(page)
                self.assertEqual(first, second)
                self.assertEqual(hashlib.sha256(first).hexdigest(), page.locator('#layout-hash').input_value())
                with ZipFile(io.BytesIO(first)) as archive:
                    pdf = archive.read('artwork.pdf')
                self.assertIn(b'CutContour_Thru-cut', pdf)
                self.assertIn(b'CutContour_Kiss-cut', pdf)
                page.click('#export')
                page.select_option('#save-destination', 'download')
                page.select_option('#save-format', 'pdf')
                self.assertEqual(page.input_value('#save-name'), 'kit')
                with page.expect_download(timeout=30000) as pending:
                    page.click('#confirm-send')
                self.assertEqual(pending.value.suggested_filename, 'kit.pdf')
                page.click('#export')
                page.fill('#save-name', 'Customer kit - Chrome')
                with page.expect_download(timeout=30000) as pending:
                    page.click('#confirm-send')
                downloaded = pending.value
                self.assertEqual(downloaded.suggested_filename, 'Customer kit - Chrome.pdf')
                direct = Path(self.tmp.name) / 'direct.pdf'
                downloaded.save_as(str(direct))
                self.assertEqual(direct.read_bytes(), pdf)
                self.assertEqual(page.locator('#delivery-receipt').inner_text(), 'Downloaded Customer kit - Chrome.pdf')
                self.assertNotIn(b'LNThru-cut', pdf)
                self.assertNotIn(b'LNKiss-cut', pdf)
                from pypdf import PdfReader
                content = PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data()
                self.assertNotIn(b'LNRegmark', content)
                self.assertNotIn(b'barcode', pdf.lower())
            finally:
                browser.close()

    def test_svg_prepared_artwork_stays_unexpanded_through_source_transforms(self):
        from playwright.sync_api import sync_playwright
        cases = [
            '<rect width="2" height="2" fill="#ff0000"/>',
            '<g transform="translate(1 1) scale(2)"><g transform="scale(.5 1.5)"><rect width="2" height="1" fill="#ff0000"/></g></g>',
            '<g transform="translate(1 1)"><g transform="matrix(2 .25 .5 .75 0 0)"><rect width="1" height="2" fill="#ff0000"/></g></g>',
        ]
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.evaluate("document.querySelector('#auto-bleed').value = '0.125'")
                self.assertEqual(page.evaluate('autoBleedMm()'), 0)
                for index, body in enumerate(cases):
                    with self.subTest(transform=index):
                        measured = page.evaluate(r"""async ({body, angle}) => {
                            const source = '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 10 10">' + body + '</svg>';
                            const job = EZNSVG.importSVG(source);
                            const part = job.parts[0];
                            const result = {width:120, usedLength:120, placements:[{id:part.id, x:50, y:30, rotation:angle}]};
                            const svg = EZNSVG.buildSVG(job, result);
                            const original = svg.querySelector('[data-ezn-boundary="true"]');
                            const before = original.outerHTML;
                            const artworkBefore = EZNSVG.serialize(svg);
                            applyAutoBleed(svg, job, result);
                            const artworkUnchanged = artworkBefore === EZNSVG.serialize(svg);
                            const radians = angle*Math.PI/180;
                            const points = part.points.map(([x,y]) => [50+x*Math.cos(radians)-y*Math.sin(radians),30+x*Math.sin(radians)+y*Math.cos(radians)]);
                            const expected = [Math.min(...points.map(p=>p[0])), Math.min(...points.map(p=>p[1])),
                                              Math.max(...points.map(p=>p[0])), Math.max(...points.map(p=>p[1]))];
                            const bounds = [];
                            for (const density of [5,10]) {
                                svg.setAttribute('width', String(120*density));
                                svg.setAttribute('height', String(120*density));
                                const image = new Image();
                                const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(EZNSVG.serialize(svg));
                                try {
                                    await new Promise((resolve,reject) => {image.onload=resolve; image.onerror=reject; image.src=url;});
                                    const canvas = document.createElement('canvas'); canvas.width=canvas.height=120*density;
                                    const context = canvas.getContext('2d'); context.drawImage(image,0,0);
                                    const pixels = context.getImageData(0,0,canvas.width,canvas.height).data;
                                    let x0=canvas.width,y0=canvas.height,x1=0,y1=0;
                                    for(let y=0;y<canvas.height;y++) for(let x=0;x<canvas.width;x++) {
                                        if(pixels[(y*canvas.width+x)*4+3]>127) {x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x+1);y1=Math.max(y1,y+1);}
                                    }
                                    bounds.push([x0/density,y0/density,x1/density,y1/density]);
                                } finally {URL.revokeObjectURL(url);}
                            }
                            return {expected,bounds,artworkUnchanged,originalUnchanged:before===original.outerHTML};
                        }""", {'body':body, 'angle':31 if index == 2 else 0})
                        self.assertTrue(measured['originalUnchanged'])
                        self.assertTrue(measured['artworkUnchanged'])
                        for density, bounds in zip([5, 10], measured['bounds']):
                            for actual, expected in zip(bounds, measured['expected']):
                                self.assertAlmostEqual(actual, expected, delta=2/density + .02)
            finally:
                browser.close()

    def test_prepared_artwork_keeps_auto_bleed_disabled(self):
        from playwright.sync_api import sync_playwright
        source = Path(self.tmp.name) / 'bleed.pdf'
        source.write_bytes(mixed_fixture())
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.set_input_files('#file', str(source))
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                before = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertTrue(page.locator('#auto-bleed').is_hidden())
                page.click('#piece-review summary')
                page.wait_for_function("() => [...document.querySelectorAll('.piece-card img')].length > 0 && [...document.querySelectorAll('.piece-card img')].every(i => i.complete && i.naturalWidth > 0)")
                self.assertEqual(page.locator('.piece-card').count(),len(before['job']['parts']))
                self.assertNotIn('thru',page.locator('#piece-cards').inner_text())
                self.assertNotIn('kiss',page.locator('#piece-cards').inner_text())
                page.locator('#auto-bleed').evaluate("node => { node.value = '0.125'; node.dispatchEvent(new Event('change', {bubbles:true})); }")
                self.start_nesting(page)
                page.wait_for_function("old => current && current.id !== old && !busy && current.status === 'ready'", arg=before['id'], timeout=90000)
                after = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertNotEqual(before['id'], after['id'])
                self.assertEqual(after['job']['settings']['autoBleedMm'], 0)
                self.assertTrue(all('nestingPoints' not in p for p in after['job']['parts']))
                from engine import validate_result
                validate_result(after['job'], after['result'])
                first = self.download(page)
                with ZipFile(io.BytesIO(first)) as archive:
                    self.assertIn('artwork.pdf', archive.namelist())
            finally:
                browser.close()

    def test_red_status_disables_send(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                self.set_legacy_width(page, '0.6')
                page.locator('#settings').evaluate('node => node.close()')
                self.start_nesting(page)
                page.wait_for_selector('#gate.problem', timeout=90000)
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertNotIn('cuts ok', page.locator('#gate').inner_text().casefold())
                color = page.locator('#gate').evaluate(
                    "el => JSON.stringify({color: getComputedStyle(el).color,"
                    " adjust: getComputedStyle(el).forcedColorAdjust,"
                    " forced: matchMedia('(forced-colors: active)').matches,"
                    " alarm: getComputedStyle(document.documentElement).getPropertyValue('--alarm').trim()})"
                )
                self.assertIn('217, 47, 0', color)
                self.assertNotEqual(page.locator('#export').evaluate('el => getComputedStyle(el).backgroundColor'), 'rgb(17, 17, 17)')
                page.locator('#export').focus()
                page.keyboard.press('Space')
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertFalse(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-blocked.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-blocked.png'), full_page=True)
            finally:
                browser.close()

    def test_upload_and_changes_wait_for_start_nesting(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                solves=[]
                page.on('request', lambda request: solves.append(request.url) if request.url.endswith('/api/solve') else None)
                self.assertEqual(page.locator('#nest').count(), 0)
                page.locator('#settings').evaluate('node => node.close()')
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                page.wait_for_function("() => document.body.dataset.step === 'configure' && !importing")
                self.assertEqual(solves, [])
                self.assertFalse(page.locator('#drop-screen').is_hidden())
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#checks')?.textContent || '')", timeout=90000)
                self.assertEqual(page.locator('#sheets .num').inner_text().strip(), '1')
                self.assertIn('4 piece', page.locator('#checks').inner_text().casefold())
                page.locator('#files input[type=number]').fill('2')
                self.assertEqual(len(solves), 1)
                self.assertTrue(page.locator('#export').is_hidden())
                self.start_nesting(page)
                page.wait_for_function("() => /8 pieces/i.test(document.querySelector('#checks')?.textContent || '')", timeout=90000)
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                self.assertNotIn('problem', page.locator('#gate').get_attribute('class') or '')
                page.click('#start-over')
                page.wait_for_function("() => document.body.dataset.step === 'drop'")
                self.assertEqual(page.input_value('#sets'), '1')
                self.assertFalse(page.locator('#job-options').evaluate('n => n.open'))
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                page.wait_for_function("() => document.body.dataset.step === 'configure' && !importing")
                page.locator('#start-nesting').focus()
                page.keyboard.press('Enter')
                page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
                self.assertEqual(len(solves), 3)
                state=json.load(urlopen(self.url()+'/api/state'))
                self.assertEqual(state['job']['productionJobs'][0]['sets'],1)
                self.assertEqual(len(state['result']['placements']),4)
            finally:
                browser.close()


    def test_legacy_job_width_nests_and_blocks(self):
        from playwright.sync_api import sync_playwright
        sample = str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg')
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.locator('#settings').evaluate('node => node.close()')
                self.assertEqual(page.input_value('#nest-width'), '51.5')
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-empty.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-empty.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', sample)
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                full = json.load(urlopen(self.url() + '/api/state', timeout=10))['result']['width']
                self.assertAlmostEqual(full, 51.5 * 25.4, places=1)
                self.set_legacy_width(page, '30')
                self.start_nesting(page)
                page.wait_for_function(
                    """() => {
                      const gate = document.querySelector('#gate');
                      const width = Number(document.body.dataset.nestWidth);
                      return Math.abs(width - 762) < 1 && /cuts ok/i.test(gate?.textContent || '')
                        && !gate.classList.contains('problem');
                    }""",
                    timeout=90000)
                narrow = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertAlmostEqual(narrow['result']['width'], 30 * 25.4, places=1)
                self.assertLess(narrow['result']['width'], full - 100)
                self.assertAlmostEqual(narrow['job']['settings']['sheetLength'], 60 * 25.4, places=0)
                self.assertEqual(page.locator('#used-width').inner_text(), 'on 30" wide')
                self.assertFalse(page.locator('#export').is_disabled())
                page.locator('#settings').evaluate('node => node.close()')
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-ready.png'), full_page=True)
                page.screenshot(path=str(SCREENSHOTS / 'eznest-width-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-ready.png'), full_page=True)
                page.screenshot(path=str(SCREENSHOTS / 'eznest-width-mobile.png'), full_page=True)
                self.assertTrue(page.locator('#nest-width').is_hidden())
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.set_viewport_size({'width': 1280, 'height': 900})
                self.set_legacy_width(page, '60')
                self.start_nesting(page)
                page.wait_for_selector('#gate.problem', timeout=15000)
                self.assertIn('printable', page.locator('#gate').inner_text().casefold())
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertNotIn('cuts ok', page.locator('#gate').inner_text().casefold())
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-blocked.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-blocked.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                self.set_legacy_width(page, '2')
                page.wait_for_function("() => /wider than this width/i.test(document.querySelector('#gate')?.textContent || '')", timeout=15000)
                self.assertTrue(page.locator('#gate').evaluate("el => el.classList.contains('problem')"))
                self.assertTrue(page.locator('#export').is_disabled())
                self.set_legacy_width(page, '0')
                page.wait_for_function("() => /greater than 0/i.test(document.querySelector('#gate')?.textContent || '')", timeout=15000)
                self.assertTrue(page.locator('#export').is_disabled())
            finally:
                browser.close()


    def test_gang_sheet_keeps_each_files_quantity(self):
        from playwright.sync_api import sync_playwright
        sample = (Path(__file__).resolve().parents[1] / 'sample-artwork.svg').read_text(encoding='utf-8')
        badge = Path(self.tmp.name) / 'badge.svg'
        label = Path(self.tmp.name) / 'label.svg'
        badge.write_text(sample, encoding='utf-8')
        label.write_text(sample, encoding='utf-8')
        shots = SCREENSHOTS
        shots.mkdir(parents=True, exist_ok=True)

        def ready(count):
            return (
                "() => { const text = document.querySelector('#checks')?.textContent || '';"
                " const gate = document.querySelector('#gate');"
                f" return /^\\s*{count} pieces/i.test(text) && gate && !gate.classList.contains('problem'); }}"
            )

        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.locator('#settings').evaluate('node => node.close()')
                page.set_input_files('#file', [str(badge), str(label)])
                self.start_nesting(page)
                page.wait_for_function(ready(8), timeout=90000)
                self.assertEqual(page.locator('#files li').count(), 2)
                self.assertIn('badge.svg', page.locator('#files').inner_text())
                self.assertIn('label.svg', page.locator('#files').inner_text())
                self.assertEqual(page.locator('#files input').nth(0).input_value(), '1')
                self.assertEqual(page.locator('#files input').nth(1).input_value(), '1')
                self.assertEqual(page.locator('#files button').count(), 2)
                page.locator('#files input').nth(1).fill('2')
                self.assertEqual(page.locator('#files input').nth(1).input_value(), '2')
                self.assertEqual(page.locator('.file-count').nth(1).inner_text(), '4 pieces × 2 = 8 total')
                self.start_nesting(page)
                page.wait_for_function(ready(12), timeout=90000)
                self.assertEqual(page.locator('#piece-count').inner_text(), '12 pieces')
                self.assertTrue(page.locator('#result-heading').is_hidden())
                self.assertEqual(page.locator('#piece-review-title').inner_text(), 'Check 12 pieces')
                self.assertEqual(page.locator('#piece-review-count').inner_text(), '4 pieces × 1 copy + 4 pieces × 2 copies')
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                page.screenshot(path=str(shots / 'gang-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'gang-mobile.png'), full_page=True)
                remove = page.locator('#files button').first.bounding_box()
                self.assertLessEqual(remove['x'] + remove['width'], 390)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.locator('#files button').first.click()
                self.start_nesting(page)
                page.wait_for_function(ready(8), timeout=90000)
                self.assertEqual(page.locator('#files li').count(), 1)
                self.assertIn('label.svg', page.locator('#files').inner_text())
                self.assertNotIn('badge.svg', page.locator('#files').inner_text())
                page.set_input_files('#more', str(badge))
                self.start_nesting(page)
                page.wait_for_function(ready(12), timeout=90000)
                self.assertEqual(page.locator('#files li').count(), 2)
                self.assertFalse(page.locator('#add-files').is_hidden())
                self.assertTrue(page.locator('#stop').is_hidden())
                self.assertEqual(page.locator('#stop').text_content().strip(), 'Stop · keep best')
            finally:
                browser.close()

    def test_pdf_compatible_ai_imports_and_unreadable_ai_says_save_as_pdf(self):
        from playwright.sync_api import sync_playwright
        good = Path(self.tmp.name) / 'kit.ai'
        bad = Path(self.tmp.name) / 'poster.ai'
        good.write_bytes(mixed_fixture())
        bad.write_bytes(b'%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 200 100\n')
        shots = SCREENSHOTS
        shots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.locator('#settings').evaluate('node => node.close()')
                page.set_input_files('#file', str(bad))
                page.wait_for_selector('#status.error', timeout=20000)
                self.assertEqual(page.locator('#status').inner_text().strip(), 'poster.ai: Use PDF, or save AI with Create PDF Compatible File enabled.')
                self.assertNotIn('Reading', page.locator('#status').inner_text())
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertEqual(page.locator('body').get_attribute('data-step'),'drop')
                self.assertEqual(page.locator('#checks').inner_text().strip(),'')
                page.screenshot(path=str(shots / 'ai-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'ai-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', str(good))
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                self.assertIn('thru', page.locator('#checks').inner_text().casefold())
                self.assertIn('kiss', page.locator('#checks').inner_text().casefold())
                packed = self.download(page)
                with ZipFile(io.BytesIO(packed)) as archive:
                    pdf = archive.read('artwork.pdf')
                self.assertIn(b'CutContour_Thru-cut', pdf)
                self.assertIn(b'CutContour_Kiss-cut', pdf)
            finally:
                browser.close()

    def test_refresh_restores_pdf_and_svg_inputs_and_resumes_running_job(self):
        from playwright.sync_api import sync_playwright
        pdf = Path(self.tmp.name) / 'refresh.ai'
        pdf.write_bytes(mixed_fixture())
        svg = Path(__file__).resolve().parents[1] / 'sample-artwork.svg'
        with sync_playwright() as playwright:
            for file in (pdf, svg):
                with self.subTest(format=file.suffix):
                    server.STATE.clear()
                    server.STATE.update(status='idle')
                    browser, page = self.open_page(playwright)
                    try:
                        page.locator('#seconds').evaluate("node => node.value = '1'")
                        page.click('#edit-material')
                        page.click('#material-advanced summary')
                        self.assertTrue(page.locator('#auto-bleed').is_hidden())
                        self.assertTrue(page.locator('#bleed').is_hidden())
                        page.select_option('#rotations', '0,180')
                        page.click('#save-material')
                        page.set_input_files('#file', str(file))
                        page.wait_for_function('() => !importing && kits.length === 1')
                        page.locator('#files input[type=number]').fill('2')
                        self.start_nesting(page)
                        page.wait_for_function("() => document.body.dataset.step === 'check' && /cuts ok/i.test(document.querySelector('#gate').textContent)", timeout=90000)
                        before = json.load(urlopen(self.url() + '/api/state', timeout=10))
                        page.reload()
                        self.wait_ready(page)
                        self.assertEqual(page.locator('#files li').count(), 1)
                        self.assertEqual(page.locator('#files input').input_value(), '2')
                        self.assertEqual(page.input_value('#sets'), '2')
                        self.assertEqual(page.input_value('#unit'), 'mm')
                        self.assertEqual(page.input_value('#auto-bleed'), '0')
                        self.assertEqual(page.input_value('#rotations'), '0,180')
                        self.assertAlmostEqual(float(page.input_value('#gap')), 3)
                        unchanged = json.load(urlopen(self.url() + '/api/state', timeout=10))
                        self.assertEqual(unchanged['id'], before['id'])
                        self.assertEqual(unchanged['result'], before['result'])
                        with page.expect_response(lambda response: response.url.endswith('/api/solve'), timeout=10000) as search:
                            page.locator('#files input[type=number]').fill('3')
                            self.start_nesting(page)
                        self.assertEqual(search.value.status, 200)
                        running = json.load(urlopen(self.url() + '/api/state', timeout=10))
                        self.assertEqual(running['status'], 'running')
                        self.assertEqual(running['job']['productionJobs'][0]['sets'], 3)
                        page.reload()
                        self.wait_ready(page)
                        self.start_nesting(page)
                        page.wait_for_function("() => document.body.dataset.step === 'check' && /cuts ok/i.test(document.querySelector('#gate').textContent)", timeout=90000)
                        after = json.load(urlopen(self.url() + '/api/state', timeout=10))
                        self.assertEqual(after['job']['productionJobs'][0]['sets'], 3)
                        self.assertEqual(len(after['result']['placements']) * 2, len(before['result']['placements']) * 3)
                        self.assertEqual(after['job']['settings'], {**before['job']['settings'],'seconds':30})
                        self.assertEqual(page.locator('#files input').input_value(), '3')
                        self.assertEqual(page.input_value('#sets'), '3')
                        self.assertEqual(after['job'].get('documentSources'), before['job'].get('documentSources'))
                        self.assertEqual(after['job'].get('svgSources'), before['job'].get('svgSources'))
                    finally:
                        browser.close()

    def test_shop_settings_persist(self):
        from playwright.sync_api import sync_playwright
        folder = Path(self.tmp.name) / 'hot'
        folder.mkdir()
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.select_option('#material','custom')
                page.fill('#preset-name', 'Shop vinyl')
                page.fill('#width', '30')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#gap', '0.2')
                page.fill('#roll-length', '3600')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '1800')
                page.click('#save-material')
                saved_material = page.input_value('#material')
                # A removed job override must not replace the saved material
                # width when reopening an empty job.
                self.set_legacy_width(page, '31')
                page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                page.fill('#thru-name', 'ShopThru')
                page.fill('#kiss-name', 'ShopKiss')
                page.fill('#hot-folder', str(folder))
                page.locator('#hot-folder').dispatch_event('change')
                page.wait_for_function("() => /Default print folder saved/i.test(document.querySelector('#status').textContent)", timeout=10000)
                page.reload()
                self.wait_ready(page)
                self.assertEqual(page.input_value('#material'), saved_material)
                self.assertIn('Shop vinyl', page.locator('#material option:checked').inner_text())
                self.assertEqual(page.input_value('#preset-name'), 'Shop vinyl')
                self.assertEqual(page.input_value('#gap'), '0.2')
                self.assertEqual(page.input_value('#available-length'), '1800')
                self.assertEqual(page.input_value('#nest-width'), '30')
                self.assertEqual(page.input_value('#thru-name'), 'ShopThru')
                self.assertEqual(page.input_value('#kiss-name'), 'ShopKiss')
                self.assertEqual(Path(page.input_value('#hot-folder')), folder.resolve())
                self.assertEqual(page.input_value('#cut-preset'), 'custom')
            finally:
                try:
                    page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                    page.fill('#hot-folder', '')
                    page.locator('#hot-folder').dispatch_event('change')
                    page.wait_for_function("() => /Choose a location when saving/i.test(document.querySelector('#status').textContent)", timeout=10000)
                except Exception:
                    pass
                browser.close()

    def test_material_rolls_save_switch_cancel_and_check_available_stock(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.select_option('#material','holographic')
                self.assertEqual(page.input_value('#preset-name'), 'Moto Holographic')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#gap', '0.25')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#margin', '0.3')
                page.fill('#roll-length', '3600')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '1800')
                page.click('#save-material')
                self.assertTrue(page.locator('#preset-editor').is_hidden())
                page.select_option('#material','white-gloss')
                self.assertEqual(page.input_value('#gap'), '0.12')
                self.assertEqual(page.input_value('#available-length'), '')
                page.select_option('#material','holographic')
                self.assertEqual(page.input_value('#gap'), '0.25')
                self.assertEqual(page.input_value('#margin'), '0.3')
                self.assertEqual(page.input_value('#available-length'), '1800')
                page.select_option('#material','custom')
                page.fill('#preset-name', 'Moto Holographic')
                page.click('#save-material')
                self.assertIn('already exists', page.inner_text('#preset-error'))
                page.fill('#preset-name', 'Small remnant')
                page.fill('#width', '55')
                page.click('#save-material')
                self.assertIn('wider than the roll', page.inner_text('#preset-error'))
                page.click('#cancel-material')
                self.assertEqual(page.input_value('#width'), '51.5')
                self.assertEqual(page.input_value('#material'), 'holographic')
                page.click('#edit-material')
                page.fill('#width', '20')
                page.locator('#material-dialog').get_by_role('button',name='About Printable width',exact=True).hover()
                self.assertTrue(page.locator('#setting-help').evaluate('n => { const r=n.getBoundingClientRect(); return n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)); }'))
                page.screenshot(path=str(SCREENSHOTS/'material-editor-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(SCREENSHOTS/'material-editor-mobile.png'),full_page=True)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.set_viewport_size({'width':1280,'height':900})
                page.keyboard.press('Escape')
                self.assertFalse(page.locator('#material-dialog').evaluate('n => n.open'))
                self.assertEqual(page.input_value('#width'), '51.5')
                self.assertFalse(page.locator('#material').is_disabled())
                page.select_option('#material','custom')
                page.fill('#preset-name', 'Small remnant')
                page.locator('#material-advanced').evaluate('n => { n.open = true }')
                page.fill('#available-length', '2')
                page.click('#save-material')
                remnant = page.input_value('#material')
                page.reload()
                self.wait_ready(page)
                self.assertEqual(page.input_value('#material'), remnant)
                self.assertEqual(page.input_value('#available-length'), '2')
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                self.start_nesting(page)
                page.wait_for_selector('#gate.problem', timeout=90000)
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertEqual(page.input_value('#available-length'), '2')
            finally:
                browser.close()

    def test_shop_server_gear(self):
        from playwright.sync_api import sync_playwright
        shots = SCREENSHOTS
        shots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            try:
                page.route('**/api/update', lambda route: route.fulfill(status=200, content_type='application/json', body=json.dumps({
                    'ok': True, 'current': '1.0.0-rc.1', 'latest': '1.0.0-rc.1', 'updated': False, 'message': 'This is the latest release.'
                })))
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.locator('#setup').screenshot(path=str(shots / 'first-run-desktop.png'))
                page.click('#setup-preset')
                page.locator('#setup').screenshot(path=str(shots / 'first-run-preset-desktop.png'))
                page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                page.click('#settings-updates > summary')
                self.assertEqual(page.locator('#app-version').inner_text(), '1.0.0-rc.5')
                self.assertEqual(page.locator('#update').inner_text(), 'Check for update')
                self.assertTrue(page.locator('#updates').is_checked())
                self.assertFalse(page.locator('#update').is_hidden())
                self.assertFalse(page.locator('#lan').is_checked())
                self.assertTrue(page.locator('#lan-note').is_hidden())
                page.click('#update')
                page.wait_for_function("() => /latest release/i.test(document.querySelector('#status').textContent)", timeout=10000)
                page.locator('#updates').uncheck()
                page.wait_for_function("() => document.querySelector('#update').hidden")
                self.assertFalse(page.locator('#updates').is_checked())
                self.assertTrue(page.locator('#lan').is_disabled())
                page.locator('#settings-delivery').evaluate('node => node.open = true')
                self.assertTrue(page.locator('#lan-access').is_hidden())
                self.assertIn('Shop network access is configured when the app starts.', page.locator('#lan-access').text_content())
                page.locator('#onyx-pc').check()
                page.wait_for_function("() => document.querySelector('#hot-default').textContent.includes('C:\\\\ONYX\\\\')")
                self.assertIn(r'C:\ONYX\EPSON SureColor S80600 ONYX Input', page.locator('#hot-default').inner_text())
                page.locator('#onyx-pc').uncheck()
                page.wait_for_function("() => document.querySelector('#hot-default').textContent.includes('\\\\\\\\ONYX\\\\')")
                self.assertIn(r'\\ONYX\EPSON SureColor S80600 ONYX Input', page.locator('#hot-default').inner_text())
                self.assertEqual(page.input_value('#hot-folder'), '')
                page.locator('#settings .panel').evaluate('node => { node.style.maxHeight = "none"; node.style.overflow = "visible"; }')
                page.locator('#settings .panel').screenshot(path=str(shots / 'settings-desktop.png'))
                page.locator('#settings .panel').screenshot(path=str(shots / 'lan-desktop.png'))
                page.set_viewport_size({'width': 390, 'height': 900})
                page.locator('#settings .panel').screenshot(path=str(shots / 'lan-mobile.png'))
            finally:
                browser.close()

    def contour_file(self, name):
        artwork = '''<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="80mm" viewBox="0 0 200 80">
          <g id="CutContour" data-name="CutContour" data-ezn-layer="true">
            <rect id="piece" x="8" y="8" width="160" height="60" fill="#f2c14e"/>
          </g>
        </svg>'''
        source = Path(self.tmp.name) / name
        source.write_text(artwork, encoding='utf-8')
        return source

    def drop_plain_contour(self, page, name):
        page.set_input_files('#file', str(self.contour_file(name)))
        self.start_nesting(page)
        page.wait_for_function(
            "text => (document.querySelector('#checks')?.textContent || '').trim() === text",
            arg='Plain CutContour found: Kiss or Thru?',
            timeout=90000)

    def sent_artwork(self, page):
        page.click('#export')
        page.wait_for_selector('#confirm:not([hidden])')
        with page.expect_download(timeout=30000) as pending:
            page.click('#confirm-send')
        item = pending.value
        target = Path(self.tmp.name) / (item.suggested_filename or 'eznest.zip')
        item.save_as(str(target.resolve()))
        with ZipFile(target) as archive:
            return archive.read('artwork.svg').decode('utf-8')

    def test_plain_cutcontour_maps_to_kiss(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                self.drop_plain_contour(page, 'plain-kiss.svg')
                self.assertEqual(page.locator('#checks').inner_text().strip(), 'Plain CutContour found: Kiss or Thru?')
                self.assertEqual(page.locator('#choose-kiss').get_attribute('aria-pressed'), 'true')
                self.assertEqual(page.locator('#choose-thru').get_attribute('aria-pressed'), 'false')
                self.assertFalse(page.locator('#choose-confirm').is_hidden())
                self.assertTrue(page.locator('#export').is_disabled())
                page.click('#choose-confirm')
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                artwork = self.sent_artwork(page)
                self.assertIn('CutContour_Kiss-cut', artwork)
                self.assertNotIn('CutContour', artwork.replace('CutContour_Kiss-cut', ''))
            finally:
                browser.close()

    def test_plain_cutcontour_maps_to_thru(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.locator('#settings').evaluate('node => { node.showModal(); document.querySelector("#settings-cuts").open = true; document.querySelector("#settings-delivery").open = true; }')
                page.select_option('#cut-preset', 'ln')
                self.assertEqual(page.input_value('#thru-name'), 'LNThru-cut')
                self.assertEqual(page.input_value('#kiss-name'), 'LNKiss-cut')
                self.drop_plain_contour(page, 'plain-thru.svg')
                self.assertTrue(page.locator('#export').is_disabled())
                page.locator('#settings').evaluate('node => node.close()')
                page.click('#choose-thru')
                self.assertEqual(page.locator('#choose-thru').get_attribute('aria-pressed'), 'true')
                self.assertEqual(page.locator('#choose-kiss').get_attribute('aria-pressed'), 'false')
                self.assertTrue(page.locator('#export').is_disabled())
                page.click('#choose-confirm')
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                artwork = self.sent_artwork(page)
                self.assertIn('LNThru-cut', artwork)
                self.assertNotIn('LNKiss-cut', artwork)
                self.assertNotIn('CutContour', artwork)
            finally:
                browser.close()

    def test_plain_cutcontour_blocks_send_until_chosen(self):
        from playwright.sync_api import sync_playwright
        shots = SCREENSHOTS
        shots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                self.drop_plain_contour(page, 'plain-wait.svg')
                self.assertEqual(page.locator('#checks').inner_text().strip(), 'Plain CutContour found: Kiss or Thru?')
                self.assertEqual(page.locator('#choose-kiss').get_attribute('aria-pressed'), 'true')
                self.assertFalse(page.locator('#choose-confirm').is_hidden())
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertFalse(page.locator('#choice').is_hidden())
                page.keyboard.press('Enter')
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertTrue(page.locator('#confirm').is_hidden())
                page.screenshot(path=str(shots / 'rc5-cutcontour-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'rc5-cutcontour-mobile.png'), full_page=True)
            finally:
                browser.close()

    def test_unknown_cut_name_blocks_send_until_thru_or_kiss(self):
        from playwright.sync_api import sync_playwright
        artwork = '''<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="80mm" viewBox="0 0 200 80">
          <g id="cut-layer" data-name="Cut 2" data-ezn-layer="true">
            <rect id="piece" x="8" y="8" width="160" height="60" fill="#f2c14e"/>
          </g>
        </svg>'''
        source = Path(self.tmp.name) / 'cut-2.svg'
        source.write_text(artwork, encoding='utf-8')
        shots = SCREENSHOTS
        shots.mkdir(parents=True, exist_ok=True)
        sentence = 'Unknown cut layer "Cut 2". Rename to thru or kiss.'
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.screenshot(path=str(shots / 'rc2-materials-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'rc2-materials-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', str(source))
                self.start_nesting(page)
                page.wait_for_selector('#gate.problem', timeout=90000)
                self.assertEqual(page.locator('#checks').inner_text().strip(), sentence)
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertFalse(page.locator('#choose-thru').is_hidden())
                self.assertFalse(page.locator('#choose-kiss').is_hidden())
                self.assertEqual(page.locator('#choose-thru').inner_text(), 'THRU')
                self.assertEqual(page.locator('#choose-kiss').inner_text(), 'KISS')
                self.assertTrue(page.locator('#choose-confirm').is_hidden())
                page.screenshot(path=str(shots / 'rc2-unknown-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'rc2-unknown-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.keyboard.press('Enter')
                self.assertTrue(page.locator('#export').is_disabled())
                page.click('#choose-thru')
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                self.assertFalse(page.locator('#export').is_disabled())
                self.assertTrue(page.locator('#choice').is_hidden())
            finally:
                browser.close()

    def test_send_confirms_sheet_summary_before_the_file_leaves(self):
        from playwright.sync_api import sync_playwright
        shots = SCREENSHOTS
        shots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                self.start_nesting(page)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                state = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertFalse(page.locator('#readout').is_hidden())
                self.assertEqual(page.locator('#sheet-id').text_content(), state['id'])
                page.click('#export')
                page.wait_for_selector('#confirm:not([hidden])')
                self.assertTrue(page.locator('#edit-material').is_disabled())
                self.assertTrue(page.locator('#material').is_disabled())
                self.assertTrue(page.locator('#nest-width').is_disabled())
                self.assertEqual(page.locator('#confirm-summary').count(), 0)
                self.assertEqual(page.locator('#confirm-send').inner_text(), 'Download')
                self.assertEqual(page.locator('#confirm-back').inner_text(), 'Back')
                self.assertFalse(page.locator('#readout').is_hidden())
                self.assertFalse(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
                page.screenshot(path=str(shots / 'rc2-confirm-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'rc2-confirm-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.click('#confirm-back')
                self.assertTrue(page.locator('#confirm').is_hidden())
                self.assertFalse(page.locator('#export').is_hidden())
                self.assertFalse(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
                page.click('#export')
                with page.expect_download(timeout=30000) as pending:
                    page.click('#confirm-send')
                item = pending.value
                target = Path(self.tmp.name) / (item.suggested_filename or 'eznest.zip')
                item.save_as(str(target.resolve()))
                with ZipFile(target) as archive:
                    artwork = archive.read('artwork.svg').decode('utf-8')
                self.assertIn(state['id'], artwork)
                self.assertNotIn('barcode', artwork.casefold())
                self.assertTrue(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()


