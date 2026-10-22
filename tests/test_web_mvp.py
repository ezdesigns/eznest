"""Simple web page: sample SVG and PDF nest, lock, and identical re-export."""
import copy
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import server
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
        self.old_updates = os.environ.get('EZ_NEST_UPDATES')
        os.environ['EZ_NEST_UPDATES'] = '0'
        self.tmp = tempfile.TemporaryDirectory()
        server.WORK = Path(self.tmp.name)
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
        if self.old_updates is None:
            os.environ.pop('EZ_NEST_UPDATES', None)
        else:
            os.environ['EZ_NEST_UPDATES'] = self.old_updates
        server.STATE.clear()
        server.STATE.update(previous)
        self.tmp.cleanup()

    def url(self):
        return f'http://127.0.0.1:{server.PORT}'

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

    def wait_for_status(self, page, timeout=60000):
        """Retry until #status has text. Windows boot can leave it empty on the first load."""
        last = None
        attempts = 3
        slice_ms = max(int(timeout / attempts), 10000)
        for attempt in range(attempts):
            try:
                page.wait_for_function(
                    "() => { const el = document.querySelector('#status'); return !!(el && el.textContent.length > 0); }",
                    timeout=slice_ms,
                )
                return
            except Exception as error:
                last = error
                if attempt + 1 >= attempts:
                    break
                page.reload(wait_until='domcontentloaded')
        raise last

    def open_page(self, playwright, shots=False):
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        page.goto(self.url() + '/web', wait_until='domcontentloaded')
        self.wait_for_status(page)
        page.locator('#settings').evaluate('node => { node.open = true }')
        self.assertEqual(page.locator('#material option:checked').inner_text(), 'White gloss, 54" roll, 51.5" printable')
        self.assertEqual(page.input_value('#width'), '51.5')
        self.assertEqual(page.input_value('#nest-width'), '51.5')
        self.assertIn('on 51.5" wide', page.locator('#used-width').inner_text())
        self.assertEqual(page.input_value('#roll'), '54')
        self.assertEqual(page.input_value('#mark-margin'), '0.5')
        self.assertEqual(page.input_value('#sheet'), '96')
        self.assertEqual(page.input_value('#auto-bleed'), '0.0625')
        self.assertEqual(page.input_value('#thru-name'), 'LNThru-cut')
        self.assertEqual(page.input_value('#kiss-name'), 'LNKiss-cut')
        self.assertEqual(page.locator('#material option[value="white-gloss"]').get_attribute('data-quickset'), 'Substance Gloss GL [EZ Designs 80600] @ 720-CT')
        self.assertEqual(page.locator('#material option[value="white-gloss"]').get_attribute('data-printer'), 'Epson S80600')
        self.assertFalse(page.locator('#draw-marks').is_checked())
        self.assertIn('EPSON SureColor S80600 ONYX Input', page.locator('#settings').inner_text())
        page.select_option('#cut-preset', 'output')
        self.assertEqual(page.input_value('#thru-name'), 'CutContour_Thru-cut')
        self.assertEqual(page.input_value('#kiss-name'), 'CutContour_Kiss-cut')
        page.select_option('#cut-preset', 'ln')
        self.assertEqual(page.input_value('#thru-name'), 'LNThru-cut')
        self.assertEqual(page.input_value('#kiss-name'), 'LNKiss-cut')
        if shots:
            page.locator('#settings .panel').evaluate('node => { node.style.maxHeight = "none"; node.style.overflow = "visible"; }')
            page.screenshot(path='/tmp/eznest-gear-desktop.png')
            page.locator('#settings .panel').screenshot(path='/tmp/eznest-gear-panel-desktop.png')
            page.set_viewport_size({'width': 390, 'height': 900})
            page.screenshot(path='/tmp/eznest-gear-mobile.png')
            page.locator('#settings .panel').screenshot(path='/tmp/eznest-gear-panel-mobile.png')
            page.set_viewport_size({'width': 1280, 'height': 900})
        page.select_option('#unit', 'mm')
        page.fill('#width', '220')
        page.fill('#gap', '3')
        page.fill('#margin', '5')
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
        item = pending.value
        target = Path(self.tmp.name) / (item.suggested_filename or 'eznest.zip')
        item.save_as(str(target))
        return target.read_bytes()

    def test_sample_svg_nests_locks_and_reexports(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright, shots=True)
            try:
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.screenshot(path='/tmp/eznest-desktop-empty.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-mobile-empty.png', full_page=True)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.set_input_files('#file', str(Path(__file__).resolve().parents[1] / 'sample-artwork.svg'))
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                self.assertEqual(page.locator('#sheets .num').inner_text().strip(), '1')
                self.assertIn('ft', page.locator('#length').inner_text().casefold())
                state = json.load(urlopen(self.url() + '/api/state', timeout=10))
                self.assertAlmostEqual(state['result']['width'], 220, places=2)
                self.assertAlmostEqual(state['job']['settings']['markMargin'], 12.7, places=1)
                self.assertAlmostEqual(state['job']['settings']['margin'], 17.7, places=1)
                self.assertGreater(state['job']['settings']['sheetLength'], 2400)
                self.assertEqual(state['job']['media']['hotFolderLabel'], 'EPSON SureColor S80600 ONYX Input')
                self.assertAlmostEqual(state['job']['media']['printableWidthMm'], 220, places=2)
                self.assertFalse(state['job']['settings']['drawRegmarks'])
                shown = float(page.locator('#waste .num').inner_text())
                self.assertEqual(round(shown), round((1 - state['result']['utilization']) * 100))
                self.assertEqual((page.locator('#preview [id*="Kiss-cut"]').first.get_attribute('stroke') or '').lower(), '#00b7ff')
                self.assertIn('cuts ok', page.locator('#gate').inner_text().casefold())
                self.assertNotIn('problem', page.locator('#gate').get_attribute('class') or '')
                self.assertEqual(page.locator('#lock').count(), 0)
                self.assertIn('send to onyx', page.locator('#export').inner_text().casefold())
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.keyboard.press('Space')
                self.assertFalse(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
                page.screenshot(path='/tmp/eznest-web-desktop.png', full_page=True)
                page.screenshot(path='/tmp/eznest-desktop-ready.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-web-mobile.png', full_page=True)
                page.screenshot(path='/tmp/eznest-mobile-ready.png', full_page=True)
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
                self.assertIn('data-ezn-bleed', artwork)
                self.assertIn('stroke-width="3.175"', artwork)
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
                self.assertIn(b'LNThru-cut', pdf)
                self.assertIn(b'LNKiss-cut', pdf)
                self.assertNotIn(b'CutContour_Thru-cut', pdf)
                self.assertNotIn(b'CutContour_Kiss-cut', pdf)
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
                page.fill('#width', '15')
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.wait_for_selector('#gate.problem', timeout=90000)
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertNotIn('cuts ok', page.locator('#gate').inner_text().casefold())
                color = page.locator('#gate').evaluate('el => getComputedStyle(el).color')
                self.assertIn('217, 47, 0', color)
                self.assertNotEqual(page.locator('#export').evaluate('el => getComputedStyle(el).backgroundColor'), 'rgb(17, 17, 17)')
                page.locator('#export').focus()
                page.keyboard.press('Space')
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertFalse(json.load(urlopen(self.url() + '/api/state', timeout=10)).get('released'))
                page.screenshot(path='/tmp/eznest-desktop-blocked.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-mobile-blocked.png', full_page=True)
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
                page.wait_for_function("() => document.querySelector('#status').textContent.length > 0")
                page.locator('#settings').evaluate('node => { node.open = false }')
                self.assertEqual(page.input_value('#nest-width'), '51.5')
                page.screenshot(path='/tmp/eznest-desktop-empty.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-mobile-empty.png', full_page=True)
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
                self.assertGreater(narrow['job']['settings']['sheetLength'], 2400)
                self.assertEqual(page.locator('#used-width').inner_text(), 'on 30" wide')
                self.assertFalse(page.locator('#export').is_disabled())
                page.locator('#settings').evaluate('node => { node.open = false }')
                page.screenshot(path='/tmp/eznest-desktop-ready.png', full_page=True)
                page.screenshot(path='/tmp/eznest-width-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-mobile-ready.png', full_page=True)
                page.screenshot(path='/tmp/eznest-width-mobile.png', full_page=True)
                box = page.locator('#nest-width').bounding_box()
                self.assertLessEqual(box['x'] + box['width'], 390)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.fill('#nest-width', '60')
                page.wait_for_selector('#gate.problem', timeout=15000)
                self.assertIn('printable', page.locator('#gate').inner_text().casefold())
                self.assertTrue(page.locator('#export').is_disabled())
                self.assertNotIn('cuts ok', page.locator('#gate').inner_text().casefold())
                page.screenshot(path='/tmp/eznest-desktop-blocked.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-mobile-blocked.png', full_page=True)
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
        shots = Path('/opt/cursor/artifacts/screenshots')
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
        shots = Path('/opt/cursor/artifacts/screenshots')
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
                self.assertIn(b'LNThru-cut', pdf)
                self.assertIn(b'LNKiss-cut', pdf)
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
                page.wait_for_function("() => document.querySelector('#status').textContent.length > 0", timeout=60000)
                page.select_option('#material', 'vinyl')
                page.fill('#nest-width', '30')
                page.locator('#settings').evaluate('node => { node.open = true }')
                page.fill('#preset-name', 'Shop vinyl')
                page.locator('#preset-name').dispatch_event('change')
                page.fill('#thru-name', 'ShopThru')
                page.fill('#kiss-name', 'ShopKiss')
                page.fill('#hot-folder', str(folder))
                page.locator('#hot-folder').dispatch_event('change')
                page.wait_for_function("() => /Hot folder set/i.test(document.querySelector('#status').textContent)", timeout=10000)
                page.reload()
                page.wait_for_function("() => document.querySelector('#status').textContent.length > 0", timeout=60000)
                self.assertEqual(page.input_value('#material'), 'vinyl')
                self.assertIn('Shop vinyl', page.locator('#material option:checked').inner_text())
                self.assertEqual(page.input_value('#preset-name'), 'Shop vinyl')
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

    def test_shop_server_gear(self):
        from playwright.sync_api import sync_playwright
        shots = Path('/opt/cursor/artifacts/screenshots')
        shots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            try:
                page.route('**/api/update', lambda route: route.fulfill(status=200, content_type='application/json', body=json.dumps({
                    'ok': True, 'current': '1.0.0-rc.1', 'latest': '1.0.0-rc.1', 'updated': False, 'message': 'This is the latest release.'
                })))
                page.goto(self.url() + '/web', wait_until='domcontentloaded')
                page.wait_for_function("() => document.querySelector('#status').textContent.length > 0")
                page.locator('#settings').evaluate('node => { node.open = true }')
                self.assertEqual(page.locator('#app-version').inner_text(), '1.0.0-rc.1')
                self.assertEqual(page.locator('#update').inner_text(), 'Update')
                self.assertFalse(page.locator('#lan').is_checked())
                self.assertTrue(page.locator('#lan-note').is_hidden())
                page.click('#update')
                page.wait_for_function("() => /latest release/i.test(document.querySelector('#status').textContent)", timeout=10000)
                page.locator('#lan').check()
                page.wait_for_function("() => !document.querySelector('#lan-note').hidden")
                self.assertIn('shop network only', page.locator('#lan-note').inner_text().casefold())
                self.assertIn(f':{server.PORT}/web', page.locator('#lan-address').inner_text())
                self.assertIn('Restart eznest to open the shop network.', page.locator('#lan-restart').inner_text())
                page.locator('#onyx-pc').check()
                page.wait_for_function("() => document.querySelector('#hot-default').textContent.includes('C:\\\\ONYX\\\\')")
                self.assertIn(r'C:\ONYX\EPSON SureColor S80600 ONYX Input', page.locator('#hot-default').inner_text())
                page.locator('#onyx-pc').uncheck()
                page.wait_for_function("() => document.querySelector('#hot-default').textContent.includes('\\\\\\\\ONYX\\\\')")
                self.assertIn(r'\\ONYX\EPSON SureColor S80600 ONYX Input', page.locator('#hot-default').inner_text())
                self.assertEqual(page.input_value('#hot-folder'), '')
                page.locator('#settings .panel').evaluate('node => { node.style.maxHeight = "none"; node.style.overflow = "visible"; }')
                page.locator('#settings .panel').screenshot(path=str(shots / 'lan-desktop.png'))
                page.set_viewport_size({'width': 390, 'height': 900})
                page.locator('#settings .panel').screenshot(path=str(shots / 'lan-mobile.png'))
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
