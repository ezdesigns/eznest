"""User-mode release checks, host admission, portable restart and browser notices."""
import opt_out
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

import installer_update
import server
import shop_deploy
from tools.package_shop_portable import package, MARKER, ASSET
from update_queue import UpdateQueue
from test_installer_update import OK
from test_shop_deploy import ScriptedOpener
import test_web_mvp


class ShopHostUpdateTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows process handles')
    def test_exited_process_with_open_parent_handle_is_not_alive(self):
        child = subprocess.Popen([sys.executable, '-c', 'pass'])
        try:
            deadline = time.monotonic() + 10
            while installer_update.pid_alive(child.pid) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertFalse(installer_update.pid_alive(child.pid))
        finally:
            child.wait(timeout=10)

    def test_public_feed_never_reads_credentials_or_accepts_installer(self):
        with patch.object(shop_deploy, 'portable_edition', return_value=True), \
             patch.object(shop_deploy, '_windows_credential') as credential, \
             patch.dict(os.environ, {'EZ_NEST_GITHUB_TOKEN': 'synthetic-do-not-send', 'EZ_NEST_GITHUB_REPO': 'other/repo'}):
            self.assertEqual(shop_deploy.github_token(None), '')
            credential.assert_not_called()
            self.assertEqual(shop_deploy.github_repo(), 'ezdesigns/eznest-downloads')
            self.assertIn('/ezdesigns/eznest-downloads/', shop_deploy.release_api())
            exe = {'name': 'eznest-setup.exe', 'browser_download_url': 'https://github.com/ezdesigns/eznest-downloads/releases/download/v2/eznest-setup.exe'}
            with self.assertRaises(ValueError):
                shop_deploy.choose_asset({'assets': [exe]}, shop_deploy.PUBLIC_DOWNLOAD_REPO)

    def test_checkbox_enables_portable_checks_but_explicit_off_wins(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(shop_deploy, 'portable_edition', return_value=True), patch.dict(os.environ):
            os.environ.pop('EZ_NEST_UPDATES', None)
            self.assertTrue(shop_deploy.updates_allowed(temp))
            shop_deploy.save_shop(temp, False, False, updates=False)
            self.assertFalse(shop_deploy.updates_allowed(temp))
            shop_deploy.save_shop(temp, False, False, updates=True)
            self.assertTrue(shop_deploy.updates_allowed(temp))
            os.environ['EZ_NEST_UPDATES'] = '0'
            self.assertFalse(shop_deploy.updates_allowed(temp))

    def test_release_check_download_checksum_and_explicit_install(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(shop_deploy, 'portable_edition', return_value=True), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}):
            shop_deploy.save_shop(temp, False, False, updates=True)
            url = 'https://github.com/ezdesigns/eznest-downloads/releases/download/v2.0.0/' + ASSET
            release = {'tag_name': 'v2.0.0', 'assets': [
                {'name': ASSET, 'browser_download_url': url},
                {'name': ASSET + '.sha256', 'browser_download_url': url + '.sha256'}]}
            payload = b'synthetic ZIP download'
            pages = {shop_deploy.release_api(): json.dumps([release]).encode(), url: payload,
                     url + '.sha256': (hashlib.sha256(payload).hexdigest() + '  ' + ASSET).encode()}
            self.assertTrue(shop_deploy.peek_latest(temp, '1.0.0', ScriptedOpener(dict(pages)))['updateAvailable'])
            self.assertFalse((Path(temp)/'updates').exists())
            result = shop_deploy.pull_latest(temp, '1.0.0', opener=ScriptedOpener(dict(pages)))
            self.assertTrue(result['staged'])
            self.assertFalse(installer_update.pending_state(temp)['applyOnRestart'])
            pages[url] = b'corrupt download'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                shop_deploy.pull_latest(temp, '1.0.0', opener=ScriptedOpener(pages))
            self.assertEqual(Path(result['path']).read_bytes(), payload)

    def test_restart_preserves_port_lan_and_tls_paths(self):
        with patch.dict(os.environ, {'EZ_NEST_PORT': '8766', 'EZ_NEST_LAN': '1', 'EZ_NEST_TLS_CERT': 'cert-path', 'EZ_NEST_TLS_KEY': 'key-path'}):
            command = installer_update.command_for(Path('eznest.exe'), Path('isolated-data'), True)
        self.assertIn('--lan', command)
        self.assertEqual(command[command.index('--port') + 1], '8766')
        self.assertEqual(command[command.index('--data-dir') + 1], 'isolated-data')
        self.assertEqual(command[command.index('--tls-key') + 1], 'key-path')

    def test_reject_data_layout_that_could_replace_shop_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'app'
            for data in (root, root/'ShopData', root.parent):
                with self.assertRaises(ValueError):
                    installer_update.validate_data_location(root, data)
            installer_update.validate_data_location(root, root/'Data')
            installer_update.validate_data_location(root, root.parent/'separate-data')

    def test_packager_contains_app_only_and_refuses_shop_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root/'app'; app.mkdir(); (app/'_internal').mkdir()
            (app/'eznest.exe').write_bytes(b'MZ synthetic')
            (app/'version.json').write_text('{"version":"2.0.0"}')
            (app/'BUILD.json').write_text('{"app":{"version":"2.0.0"}}')
            (app/'install-shop.ps1').write_text('# not distributed in this edition')
            archive = package(app, root/'download')
            with ZipFile(archive) as zipped:
                self.assertEqual(json.loads(zipped.read('portable-update.json')), MARKER)
                self.assertNotIn('install-shop.ps1', zipped.namelist())
                self.assertIn('Start EZ Nest.cmd', zipped.namelist())
            self.assertTrue(archive.with_suffix('.zip.sha256').read_text().startswith(hashlib.sha256(archive.read_bytes()).hexdigest()))
            (app/'data').mkdir(); (app/'data'/'shop.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Unexpected file'):
                package(app, root/'another-download')

    def test_real_zip_update_keeps_inventory_and_restart_address(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(shop_deploy, 'portable_edition', return_value=True), \
             patch.dict(os.environ, {'EZ_NEST_PORT': '8766', 'EZ_NEST_LAN': '1'}):
            root = Path(temp); app = root/'app'; app.mkdir(); data = root/'data'; data.mkdir()
            (app/'version.json').write_text('{"version":"1.0.0"}')
            (app/'eznest.py').write_text('raise SystemExit(0)\n')
            (data/'inventory.sqlite').write_bytes(b'synthetic stock unchanged')
            (data/'shop.json').write_text('{"updates":true,"outputNetwork":false}')
            payload = io.BytesIO()
            with ZipFile(payload, 'w') as archive:
                archive.writestr('version.json', '{"version":"2.0.0"}')
                archive.writestr('portable-update.json', json.dumps(MARKER))
                archive.writestr('eznest.py', 'import sys, json\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("--data-dir")+1], "restart-args.json").write_text(json.dumps(sys.argv))\n' + OK)
            body = payload.getvalue()
            installer_update.stage_file(data, '2.0.0', hashlib.sha256(body).hexdigest(), body, ASSET)
            try:
                self.assertTrue(installer_update.apply_and_confirm(app, data, timeout=5)['ok'])
                args = json.loads((data/'restart-args.json').read_text())
                self.assertEqual(args[args.index('--port')+1], '8766')
                self.assertIn('--lan', args)
                self.assertEqual((data/'inventory.sqlite').read_bytes(), b'synthetic stock unchanged')
                self.assertFalse(json.loads((data/'shop.json').read_text())['outputNetwork'])
            finally:
                installer_update.reap_left_running()

    def test_only_host_can_update_and_unsaved_job_blocks_restart(self):
        fixture = test_web_mvp.WebMvpTests(); fixture.setUp()
        try:
            with patch.object(server, 'UPDATE_QUEUE', UpdateQueue()), patch.object(shop_deploy, 'portable_edition', return_value=True), \
                 patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), patch.object(installer_update, 'apply_supported', return_value=True), \
                 patch.object(installer_update, 'begin_apply', return_value={'ok': True, 'restarting': True}) as apply, \
                 patch.object(fixture.service, 'shutdown'):
                shop_deploy.save_shop(server.WORK, False, False, updates=True)
                installer_update.stage_file(server.WORK, '2.0.0', hashlib.sha256(b'zip').hexdigest(), b'zip', ASSET)
                def post(path):
                    return json.load(urlopen(Request(fixture.url()+path, data=b'{}', headers={'X-EZ-Token': server.TOKEN}), timeout=5))
                with patch.object(server.Handler, 'loopback_client', return_value=False):
                    for path in ('/api/update', '/api/update/install'):
                        with self.assertRaises(HTTPError) as error: post(path)
                        self.assertEqual(error.exception.code, 403)
                server.STATE.update(status='ready', deliveryCompleted=False)
                with self.assertRaises(HTTPError): post('/api/update/install')
                apply.assert_not_called()
                server.STATE['deliveryCompleted'] = True
                self.assertTrue(post('/api/update/install')['restarting'])
                self.assertTrue(server.UPDATE_QUEUE.stopping)
                apply.assert_called_once()
        finally:
            fixture.tearDown()

    def test_host_and_designer_notices_keep_edits_until_refresh(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests(); fixture.setUp()
        try:
            with sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    host, designer = browser.new_page(), browser.new_page()
                    for page in (host, designer):
                        page.goto(fixture.url()+'/web'); fixture.wait_ready(page)
                    info = {'current':'1.0.0','latest':'2.0.0','updateAvailable':True,'portableSupported':True,'localPC':True}
                    host.evaluate('info => showUpdate(info)', info)
                    self.assertTrue(host.locator('#shop-update-action').is_visible())
                    self.assertEqual(host.locator('#shop-update-action').inner_text(), 'View update')
                    host.evaluate("() => { window.updatePosts=0; window.updateChecks=0; api=async()=>{window.updatePosts++;return {};}; refreshUpdate=async remote=>{window.updateChecks+=Number(remote);}; showUpdate({current:'1.0.0',portableSupported:true,localPC:true}); $('update').click(); }")
                    host.wait_for_function('() => !updateInFlight')
                    self.assertEqual(host.evaluate('window.updatePosts'), 0)
                    self.assertEqual(host.evaluate('window.updateChecks'), 1)
                    host.evaluate('info => showUpdate(info)', info)
                    designer.evaluate('info => showUpdate(info)', {**info, 'localPC':False})
                    self.assertTrue(designer.locator('#shop-update-action').is_hidden())
                    self.assertIn('host PC', designer.locator('#shop-update-message').inner_text())
                    designer.evaluate("() => { updateVersion='1.0.0'; $('settings').showModal(); $('printer').value='Unsaved label'; receiveUpdate({current:'2.0.0',localPC:false}); }")
                    self.assertEqual(designer.locator('#printer').input_value(), 'Unsaved label')
                    self.assertEqual(designer.locator('#shop-update-action').inner_text(), 'Refresh app')
                    shots = Path(__file__).resolve().parents[1]/'.local'/'screenshots'; shots.mkdir(exist_ok=True)
                    host.screenshot(path=str(shots/'shop-host-update.png'), full_page=True)
                finally:
                    browser.close()
        finally:
            fixture.tearDown()
