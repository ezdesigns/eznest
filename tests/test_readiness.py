import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import installer_update
import server
import shop_deploy
import test_web_mvp
from output_folder import OutputFolder


class ReadinessTests(unittest.TestCase):
    def test_folder_setup_checks_write_access_and_leaves_no_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hot = root / 'hot'
            hot.mkdir()
            output = OutputFolder(root / 'folder.json')
            old = root / 'previous'
            old.mkdir()
            output.connect(str(old))
            with patch('output_folder.tempfile.TemporaryFile', side_effect=PermissionError('Denied')):
                with self.assertRaisesRegex(ValueError, 'cannot write'):
                    output.connect(str(hot))
            self.assertEqual(output.root, hot.resolve())
            self.assertEqual(OutputFolder(root / 'folder.json').root, hot.resolve())
            self.assertEqual(list(old.iterdir()), [])
            output.connect(str(hot))
            self.assertEqual(list(hot.iterdir()), [])

    def test_failed_delivery_restore_retry_double_click_and_undo(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            hot = server.WORK / 'hot'
            hot.mkdir()
            with sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.goto(fixture.url() + '/web')
                    fixture.wait_ready(page)
                    page.fill('#setup-hot', str(hot))
                    page.fill('#setup-printer', 'Synthetic printer')
                    page.click('#setup-save')
                    page.wait_for_function("() => document.querySelector('#setup').hidden")
                    page.set_input_files('#file', str(Path(__file__).parents[1] / 'sample-artwork.svg'))
                    page.click('#start-nesting')
                    page.wait_for_function("() => document.body.dataset.step === 'check'", timeout=90000)
                    with patch.object(server.print_export, 'save_file', side_effect=ValueError('Test hot folder disconnected')):
                        page.click('#export')
                        page.click('#confirm-send')
                        page.wait_for_function("() => document.querySelector('#status').textContent.includes('disconnected')")
                    self.assertTrue(server.STATE['released'])
                    self.assertFalse(server.STATE['deliveryCompleted'])
                    page.reload()
                    fixture.wait_ready(page)
                    self.assertEqual(page.get_attribute('body', 'data-step'), 'check')
                    self.assertTrue(page.locator('#delivery-receipt').is_hidden())
                    self.assertEqual(page.locator('#status').inner_text(), '')
                    original = server.print_export.save_file
                    def slow_save(*args):
                        time.sleep(0.3)
                        return original(*args)
                    with patch.object(server.print_export, 'save_file', side_effect=slow_save) as delivered:
                        page.click('#export')
                        page.evaluate('Promise.all([exportFile(false), exportFile(false)])')
                        self.assertEqual(delivered.call_count, 1)
                    self.assertIn('Saved to', page.locator('#delivery-receipt').inner_text())
                    self.assertTrue((hot / 'sample-artwork.zip').is_file())
                    page.reload(); fixture.wait_ready(page)
                    self.assertEqual(page.get_attribute('body', 'data-step'), 'sent')
                    self.assertEqual(page.locator('#start-over').inner_text(), 'Next job')
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'))
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'production-delivered-desktop.png'), full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'))
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'production-delivered-mobile.png'), full_page=True)
                    self.assertTrue(page.locator('#undo').is_hidden())
                    page.evaluate("async () => { await api('/api/release', {id: current.id, map: 'frozen retry'}); }")
                    server.STATE.pop('exportReceipt', None); server.persist_state()
                    page.reload(); fixture.wait_ready(page)
                    page.evaluate("document.querySelector('#allow-undo').checked = true; renderActions()")
                    page.click('#undo')
                    page.wait_for_function("() => document.querySelector('#status').textContent.includes('Removed the pack')")
                    self.assertFalse(server.STATE['deliveryCompleted'])
                    self.assertFalse(server.STATE['savedPath'])
                    page.reload()
                    fixture.wait_ready(page)
                    self.assertEqual(page.get_attribute('body', 'data-step'), 'check')
                finally:
                    browser.close()
        finally:
            fixture.tearDown()

    def test_pending_path_cannot_escape_download_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'other.exe'
            file.write_bytes(b'MZ')
            installer_update.write_json(root / 'updates/pending.json', {'verified': True, 'file': str(file), 'sha256': hashlib.sha256(b'MZ').hexdigest()})
            self.assertIsNone(installer_update.pending_state(root))

    def test_protected_update_cannot_stop_working_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Program Files' / 'eznest'
            root.mkdir(parents=True)
            (root / 'eznest.exe').write_bytes(b'MZ')
            from types import SimpleNamespace
            windows = SimpleNamespace(name='nt', environ={'ProgramFiles': str(root.parent)})
            with patch.object(installer_update, 'os', windows):
                self.assertFalse(installer_update.apply_supported(root))
                with patch.object(installer_update, 'spawn_helper') as spawn:
                    self.assertFalse(installer_update.handoff_if_pending(root, tmp))
                    spawn.assert_not_called()

    def test_first_run_retries_invalid_folder_and_persists_across_browsers(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            hot = server.WORK / 'hot'
            hot.mkdir()
            with patch.object(server, 'OUTPUT', OutputFolder(server.WORK / 'output-folder.json')):
                with sync_playwright() as playwright:
                    browser = test_web_mvp.launch_browser(playwright)
                    try:
                        page = browser.new_page(viewport={'width': 1100, 'height': 900})
                        page.goto(fixture.url() + '/web')
                        fixture.wait_ready(page)
                        self.assertTrue(page.locator('#setup').is_visible())
                        page.locator('#setup').screenshot(path=str(test_web_mvp.SCREENSHOTS / 'first-run.png'))
                        page.fill('#setup-printer', 'Customer printer')
                        page.fill('#setup-hot', str(hot / 'missing'))
                        page.fill('#setup-thru', 'MyThru')
                        page.fill('#setup-kiss', 'MyKiss')
                        page.select_option('#setup-units', 'mm')
                        page.click('#setup-save')
                        page.wait_for_function("() => !document.querySelector('#setup-error').hidden")
                        self.assertFalse(shop_deploy.load_shop(server.WORK)['setupComplete'])
                        page.fill('#setup-hot', str(hot))
                        page.click('#setup-save')
                        page.wait_for_function("() => document.querySelector('#setup').hidden")
                        page.close()
                        # A fresh browser context must receive server settings.
                        page = browser.new_page(viewport={'width': 1100, 'height': 900})
                        page.goto(fixture.url() + '/web')
                        fixture.wait_ready(page)
                        self.assertFalse(page.locator('#setup').is_visible())
                        self.assertEqual(page.input_value('#unit'), 'mm')
                        self.assertEqual(page.input_value('#thru-name'), 'MyThru')
                        self.assertEqual(page.input_value('#printer'), 'Customer printer')
                        page.click('#settings-open')
                        page.locator('#settings').wait_for(state='visible')
                        for fold in ('#settings-cuts', '#settings-delivery', '#settings-updates'):
                            self.assertFalse(page.locator(fold).evaluate('node => node.open'), fold)
                        self.assertFalse(page.locator('#output-network').is_checked())
                        self.assertTrue(page.locator('#lan').is_disabled())
                        page.locator('#settings-delivery').evaluate('node => node.open = true')
                        self.assertTrue(page.locator('#lan-access').is_hidden())
                        self.assertIn('Shop network access is configured when the app starts.', page.locator('#lan-access').text_content())
                        page.locator('#settings-delivery').evaluate('node => node.open = false')
                        self.assertEqual(page.input_value('#cut-preset'), 'custom')
                        # Use an illustrative path in the documentation screenshot,
                        # after testing persistence against the real temporary folder.
                        page.fill('#hot-folder', r'C:\Print\Input')
                        page.locator('#settings .panel').evaluate('node => { node.style.maxHeight = "none"; node.style.overflow = "visible"; }')
                        page.locator('#settings .panel').screenshot(path=str(test_web_mvp.SCREENSHOTS / 'settings.png'))
                    finally:
                        browser.close()
        finally:
            fixture.tearDown()

