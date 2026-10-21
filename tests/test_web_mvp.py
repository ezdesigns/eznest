"""Simple web page: sample SVG and PDF nest, lock, and identical re-export."""
import copy
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
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
        self.assertIn('Drop your file', page)
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
        page.locator('#settings').evaluate('node => { node.open = true }')
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
        self.assertEqual(page.locator('#materials button[aria-pressed="true"]').inner_text(), 'Moto Regular')
        self.assertGreaterEqual(page.locator('#materials button').count(), 4)
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
        page.locator('#settings').evaluate('node => { node.open = false }')
        page.click('#edit-material')
        page.select_option('#unit', 'mm')
        page.fill('#width', '220')
        page.fill('#gap', '3')
        page.fill('#margin', '5')
        page.click('#save-material')
        self.assertTrue(page.locator('#preset-editor').is_hidden())
        page.fill('#nest-width', f'{220 / 25.4:.8f}')
        page.fill('#sets', '1')
        return browser, page

    def download(self, page, shortcut=False):
        with page.expect_download(timeout=30000) as pending:
            if shortcut:
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.keyboard.press('Enter')
            else:
                page.click('#export')
            page.locator('#confirm-send').click()
        item = pending.value
        target = Path(self.tmp.name) / (item.suggested_filename or 'eznest.zip')
        item.save_as(str(target))
        return target.read_bytes()

    def test_settings_help_and_save_feedback(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.locator('#settings').evaluate('node => { node.open = true }')
                info = page.locator('#settings').get_by_role('button', name='About Cut through backing', exact=True)
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
                page.locator('#settings').evaluate('node => { node.open = true }')
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
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-empty.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-empty.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
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
                self.assertEqual((page.locator('#preview [id*="Kiss-cut"]').first.get_attribute('stroke') or '').lower(), '#00b7ff')
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                self.assertEqual(page.locator('#sheet-id').text_content(), state['id'])
                self.assertTrue(page.locator('#sheet-id').is_hidden())
                self.assertNotIn('problem', page.locator('#gate').get_attribute('class') or '')
                self.assertEqual(page.locator('#lock').count(), 0)
                self.assertEqual(page.locator('#export').inner_text(), 'Review and download')
                page.locator('#settings').evaluate('node => { node.open = false }')
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
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                self.assertIn('thru', page.locator('#checks').inner_text().casefold())
                self.assertIn('kiss', page.locator('#checks').inner_text().casefold())
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                first = self.download(page)
                second = self.download(page)
                self.assertEqual(first, second)
                self.assertEqual(hashlib.sha256(first).hexdigest(), page.locator('#layout-hash').input_value())
                with ZipFile(io.BytesIO(first)) as archive:
                    pdf = archive.read('artwork.pdf')
                self.assertIn(b'CutContour_Thru-cut', pdf)
                self.assertIn(b'CutContour_Kiss-cut', pdf)
                self.assertNotIn(b'LNThru-cut', pdf)
                self.assertNotIn(b'LNKiss-cut', pdf)
                from pypdf import PdfReader
                content = PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data()
                self.assertNotIn(b'LNRegmark', content)
                self.assertNotIn(b'barcode', pdf.lower())
            finally:
                browser.close()

    def test_red_status_disables_send(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                page.fill('#nest-width', '0.6')
                page.locator('#settings').evaluate('node => { node.open = false }')
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

    def test_drop_nests_without_a_button(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                self.assertEqual(page.locator('#nest').count(), 0)
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#checks')?.textContent || '')", timeout=90000)
                self.assertEqual(page.locator('#sheets .num').inner_text().strip(), '1')
                self.assertIn('4 piece', page.locator('#checks').inner_text().casefold())
                page.fill('#sets', '2')
                page.wait_for_function("() => /8 pieces/i.test(document.querySelector('#checks')?.textContent || '')", timeout=90000)
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                self.assertNotIn('problem', page.locator('#gate').get_attribute('class') or '')
            finally:
                browser.close()


    def test_chosen_width_nests_and_blocks(self):
        from playwright.sync_api import sync_playwright
        sample = str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg')
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True).new_page()
            try:
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.locator('#settings').evaluate('node => { node.open = false }')
                self.assertEqual(page.input_value('#nest-width'), '51.5')
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-empty.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-empty.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', sample)
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                full = json.load(urlopen(self.url() + '/api/state', timeout=10))['result']['width']
                self.assertAlmostEqual(full, 51.5 * 25.4, places=1)
                page.fill('#nest-width', '30')
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
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-ready.png'), full_page=True)
                page.screenshot(path=str(SCREENSHOTS / 'eznest-width-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-ready.png'), full_page=True)
                page.screenshot(path=str(SCREENSHOTS / 'eznest-width-mobile.png'), full_page=True)
                box = page.locator('#nest-width').bounding_box()
                self.assertLessEqual(box['x'] + box['width'], 390)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.fill('#nest-width', '60')
                page.wait_for_selector('#gate.problem', timeout=15000)
                self.assertIn('printable', page.locator('#gate').inner_text().casefold())
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertNotIn('cuts ok', page.locator('#gate').inner_text().casefold())
                page.screenshot(path=str(SCREENSHOTS / 'eznest-desktop-blocked.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(SCREENSHOTS / 'eznest-mobile-blocked.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.fill('#nest-width', '2')
                page.wait_for_function("() => /wider than this width/i.test(document.querySelector('#gate')?.textContent || '')", timeout=15000)
                self.assertTrue(page.locator('#gate').evaluate("el => el.classList.contains('problem')"))
                self.assertTrue(page.locator('#export').is_disabled())
                page.fill('#nest-width', '0')
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
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.set_input_files('#file', [str(badge), str(label)])
                page.wait_for_function(ready(8), timeout=90000)
                self.assertEqual(page.locator('#files li').count(), 2)
                self.assertIn('badge.svg', page.locator('#files').inner_text())
                self.assertIn('label.svg', page.locator('#files').inner_text())
                self.assertEqual(page.locator('#files input').nth(0).input_value(), '1')
                self.assertEqual(page.locator('#files input').nth(1).input_value(), '1')
                self.assertEqual(page.locator('#files button').count(), 2)
                page.locator('#files input').nth(1).fill('2')
                self.assertEqual(page.locator('#files input').nth(1).input_value(), '2')
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                page.screenshot(path=str(shots / 'gang-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'gang-mobile.png'), full_page=True)
                remove = page.locator('#files button').first.bounding_box()
                self.assertLessEqual(remove['x'] + remove['width'], 390)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.locator('#files button').first.click()
                page.wait_for_function(ready(8), timeout=90000)
                self.assertEqual(page.locator('#files li').count(), 1)
                self.assertIn('label.svg', page.locator('#files').inner_text())
                self.assertNotIn('badge.svg', page.locator('#files').inner_text())
                page.set_input_files('#more', str(badge))
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
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.set_input_files('#file', str(bad))
                page.wait_for_selector('#gate.problem', timeout=20000)
                self.assertEqual(page.locator('#checks').inner_text().strip(), 'Save as PDF')
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertEqual(page.locator('#gate').inner_text().strip(), 'Save as PDF')
                page.screenshot(path=str(shots / 'ai-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'ai-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', str(good))
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
                        page.fill('#sets', '2')
                        page.locator('#seconds').evaluate("node => node.value = '1'")
                        page.click('#edit-material')
                        page.click('#material-advanced summary')
                        page.select_option('#auto-bleed', '0')
                        page.fill('#bleed', '0')
                        page.select_option('#rotations', '0,180')
                        page.click('#save-material')
                        page.set_input_files('#file', str(file))
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
                            page.locator('#files input').fill('3')
                        self.assertEqual(search.value.status, 200)
                        running = json.load(urlopen(self.url() + '/api/state', timeout=10))
                        self.assertEqual(running['status'], 'running')
                        self.assertEqual(running['job']['productionJobs'][0]['sets'], 3)
                        page.reload()
                        self.wait_ready(page)
                        page.wait_for_function("() => document.body.dataset.step === 'check' && /cuts ok/i.test(document.querySelector('#gate').textContent)", timeout=90000)
                        after = json.load(urlopen(self.url() + '/api/state', timeout=10))
                        self.assertEqual(after['job']['productionJobs'][0]['sets'], 3)
                        self.assertEqual(len(after['result']['placements']) * 2, len(before['result']['placements']) * 3)
                        self.assertEqual(after['job']['settings'], before['job']['settings'])
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
                page.click('#materials button[data-value=custom]')
                page.fill('#preset-name', 'Shop vinyl')
                page.fill('#gap', '0.2')
                page.fill('#available-length', '1800')
                page.click('#save-material')
                saved_material = page.input_value('#material')
                page.fill('#nest-width', '30')
                page.locator('#settings').evaluate('node => { node.open = true }')
                page.fill('#thru-name', 'ShopThru')
                page.fill('#kiss-name', 'ShopKiss')
                page.fill('#hot-folder', str(folder))
                page.locator('#hot-folder').dispatch_event('change')
                page.wait_for_function("() => /Hot folder set/i.test(document.querySelector('#status').textContent)", timeout=10000)
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
                    page.locator('#settings').evaluate('node => { node.open = true }')
                    page.fill('#hot-folder', '')
                    page.locator('#hot-folder').dispatch_event('change')
                    page.wait_for_function("() => /No hot folder/i.test(document.querySelector('#status').textContent)", timeout=10000)
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
                page.click('#materials button[data-value=holographic]')
                self.assertEqual(page.input_value('#preset-name'), 'Holographic')
                page.fill('#gap', '0.25')
                page.fill('#margin', '0.3')
                page.fill('#available-length', '1800')
                page.click('#save-material')
                self.assertTrue(page.locator('#preset-editor').is_hidden())
                page.click('#materials button[data-value=white-gloss]')
                self.assertEqual(page.input_value('#gap'), '0.12')
                self.assertEqual(page.input_value('#available-length'), '')
                page.click('#materials button[data-value=holographic]')
                self.assertEqual(page.input_value('#gap'), '0.25')
                self.assertEqual(page.input_value('#margin'), '0.3')
                self.assertEqual(page.input_value('#available-length'), '1800')
                page.click('#materials button[data-value=custom]')
                page.fill('#preset-name', 'Holographic')
                page.click('#save-material')
                self.assertIn('already exists', page.inner_text('#preset-error'))
                page.fill('#preset-name', 'Small remnant')
                page.fill('#width', '55')
                page.click('#save-material')
                self.assertIn('wider than the roll', page.inner_text('#preset-error'))
                page.click('#cancel-material')
                self.assertEqual(page.input_value('#width'), '51.5')
                self.assertEqual(page.input_value('#material'), 'holographic')
                page.click('#materials button[data-value=custom]')
                page.fill('#preset-name', 'Small remnant')
                page.fill('#available-length', '2')
                page.click('#save-material')
                remnant = page.input_value('#material')
                page.reload()
                self.wait_ready(page)
                self.assertEqual(page.input_value('#material'), remnant)
                self.assertEqual(page.input_value('#available-length'), '2')
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
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
                page.locator('#settings').evaluate('node => { node.open = true }')
                self.assertEqual(page.locator('#app-version').inner_text(), '1.0.0-rc.4')
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
                self.assertIn('--lan', page.locator('#settings').inner_text())
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
                page.wait_for_selector('#gate.problem', timeout=90000)
                self.assertEqual(page.locator('#checks').inner_text().strip(), sentence)
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertFalse(page.locator('#choose-thru').is_hidden())
                self.assertFalse(page.locator('#choose-kiss').is_hidden())
                self.assertEqual(page.locator('#choose-thru').inner_text(), 'THRU')
                self.assertEqual(page.locator('#choose-kiss').inner_text(), 'KISS')
                page.screenshot(path=str(shots / 'rc2-unknown-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(shots / 'rc2-unknown-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.keyboard.press('Enter')
                self.assertTrue(page.locator('#export').is_disabled())
                page.click('#choose-thru')
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
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                state = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertFalse(page.locator('#readout').is_hidden())
                self.assertEqual(page.locator('#sheet-id').text_content(), state['id'])
                page.click('#export')
                page.wait_for_selector('#confirm:not([hidden])')
                self.assertTrue(page.locator('#edit-material').is_disabled())
                self.assertTrue(page.locator('#nest-width').is_disabled())
                summary = page.locator('#confirm-summary').inner_text()
                self.assertIn('Moto Regular', summary)
                self.assertIn('51.5 in wide', summary)
                self.assertIn('in long', summary)
                self.assertIn('piece', summary)
                self.assertIn(state['id'], summary)
                self.assertEqual(page.locator('#confirm-send').inner_text(), 'Confirm send')
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
                item.save_as(str(target))
                with ZipFile(target) as archive:
                    artwork = archive.read('artwork.svg').decode('utf-8')
                self.assertIn(state['id'], artwork)
                self.assertNotIn('barcode', artwork.casefold())
                self.assertTrue(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()


