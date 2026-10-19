"""Simple web page: sample SVG and PDF nest, lock, and identical re-export."""
import copy
import hashlib
import io
import json
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
        self.assertIn('Drop the kit', page)
        self.assertIn('/svg-io.js', page)
        self.assertNotIn('<script>', page.lower().split('<body', 1)[-1].replace('src=', ''))

    def open_page(self, playwright):
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        page.goto(self.url() + '/web', wait_until='domcontentloaded')
        page.wait_for_function("() => document.querySelector('#status').textContent.length > 0")
        page.select_option('#unit', 'mm')
        page.fill('#width', '220')
        page.fill('#gap', '3')
        page.fill('#margin', '5')
        page.select_option('#seconds', '5')
        page.fill('#sets', '1')
        return browser, page

    def download(self, page):
        with page.expect_download(timeout=30000) as pending:
            page.click('#export')
        item = pending.value
        target = Path(self.tmp.name) / (item.suggested_filename or 'eznest.zip')
        item.save_as(str(target))
        return target.read_bytes()

    def test_sample_svg_nests_locks_and_reexports(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, page = self.open_page(playwright)
            try:
                page.click('#sample')
                page.wait_for_selector('#kit:not([hidden])')
                self.assertIn('sample-artwork', page.locator('#kit-name').inner_text())
                self.assertIn('4 piece', page.locator('#pieces').inner_text().casefold())
                self.assertIn('kiss', page.locator('#kiss').inner_text().casefold())
                page.click('#nest')
                page.wait_for_selector('#output:not([hidden])', timeout=90000)
                self.assertEqual(page.locator('#sheets').inner_text(), '1')
                self.assertIn('ft', page.locator('#length').inner_text().casefold())
                state = json.load(urlopen(self.url() + '/api/state', timeout=10))
                shown = float(page.locator('#waste').inner_text().rstrip('%'))
                self.assertAlmostEqual(shown, (1 - state['result']['utilization']) * 100, places=1)
                self.assertEqual((page.locator('#preview [id*="Kiss-cut"]').first.get_attribute('stroke') or '').lower(), '#d92f00')
                page.screenshot(path='/tmp/eznest-web-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/eznest-web-mobile.png', full_page=True)
                box = page.locator('#export').bounding_box()
                self.assertLessEqual(box['x'] + box['width'], 390)
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.click('#lock')
                page.wait_for_function("() => /^[a-f0-9]{64}$/.test(document.querySelector('#layout-hash').value)")
                digest = page.locator('#layout-hash').input_value()
                ident = page.locator('#layout-id').input_value()
                first = self.download(page)
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
                page.wait_for_selector('#kit:not([hidden])')
                self.assertIn('thru', page.locator('#thru').inner_text().casefold())
                self.assertIn('kiss', page.locator('#kiss').inner_text().casefold())
                page.click('#nest')
                page.wait_for_selector('#output:not([hidden])', timeout=90000)
                page.click('#lock')
                page.wait_for_function("() => /^[a-f0-9]{64}$/.test(document.querySelector('#layout-hash').value)")
                first = self.download(page)
                second = self.download(page)
                self.assertEqual(first, second)
                self.assertEqual(hashlib.sha256(first).hexdigest(), page.locator('#layout-hash').input_value())
                with ZipFile(io.BytesIO(first)) as archive:
                    pdf = archive.read('artwork.pdf')
                self.assertIn(b'CutContour_Thru-cut', pdf)
                self.assertIn(b'CutContour_Kiss-cut', pdf)
                self.assertIn(b'Thru-cut', pdf)
                self.assertIn(b'Kiss-cut', pdf)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
