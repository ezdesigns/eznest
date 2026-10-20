import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import installer_update
import server
import shop_deploy
import test_web_mvp
from output_folder import OutputFolder


class ReadinessTests(unittest.TestCase):
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
            with patch.dict('os.environ', {'ProgramFiles': str(root.parent)}), patch.object(installer_update.os, 'name', 'nt'):
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
                        page.click('#settings summary')
                        self.assertFalse(page.locator('#output-network').is_checked())
                        self.assertTrue(page.locator('#lan').is_disabled())
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
