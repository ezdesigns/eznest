import hashlib
import json
import threading
import tempfile
import sys
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

import server
import installer_update
import shop_deploy
from update_queue import UpdateQueue
import test_web_mvp
import managed_update
import launcher


class UpdateQueueTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows install policy')
    def test_unsigned_and_unprotected_installs_remain_manual(self):
        with tempfile.TemporaryDirectory() as temp:
            programs = (Path(temp)/'Program Files').resolve()
            root = programs/'eznest'
            root.mkdir(parents=True)
            (root/'eznest.exe').write_bytes(b'MZ synthetic')
            (root/'update-shop.ps1').write_text('# synthetic')
            with patch.object(managed_update, 'program_directories', return_value=[programs]):
                self.assertFalse(managed_update.supported(root))
                (root/'update-publisher.txt').write_text('A'*40)
                self.assertTrue(managed_update.supported(root))
                self.assertFalse(managed_update.supported(Path(temp)))
                (root/'update-publisher.txt').write_text('not a publisher')
                self.assertFalse(managed_update.supported(root))

    def test_update_launcher_never_runs_server_or_uses_url_arguments(self):
        with patch.object(sys, 'argv', ['eznest', '--request-shop-update', 'untrusted://anything']), patch.object(managed_update, 'request', return_value=0) as request, patch.object(server, 'serve') as serve:
            self.assertEqual(launcher.main(), 0)
            request.assert_called_once_with()
            serve.assert_not_called()

    def test_busy_unsent_cancel_and_expiry(self):
        now = [10]
        queue = UpdateQueue(lambda: now[0])
        ticket = 'a' * 32
        queue.queue(ticket)
        self.assertFalse(queue.claim(ticket, {'status': 'running'}))
        self.assertFalse(queue.claim(ticket, {'status': 'ready', 'released': True}))
        with self.assertRaises(ValueError):
            queue.queue('b' * 32)
        queue.cancel()
        with self.assertRaises(ValueError):
            queue.claim(ticket, {'status': 'idle'})
        queue.queue(ticket)
        now[0] += 301
        self.assertFalse(queue.status()['queued'])
        queue.queue(ticket)
        self.assertTrue(queue.claim(ticket, {'status': 'ready', 'deliveryCompleted': True}))
        with self.assertRaises(ValueError):
            queue.cancel()

    def test_local_api_queue_wait_discard_claim_and_admission(self):
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            with patch.object(server, 'UPDATE_QUEUE', UpdateQueue()), patch.object(fixture.service, 'shutdown'):
                payload = b'MZ synthetic installer'
                pending = installer_update.stage_file(server.WORK, '99.0.0', hashlib.sha256(payload).hexdigest(), payload, 'eznest-setup.exe')
                request = {'ticket': 'a'*32, 'sha256': pending['sha256']}
                def post(path, data, token=True):
                    headers = {'Content-Type': 'application/json'}
                    if token:
                        headers['X-EZ-Token'] = server.TOKEN
                    return json.load(urlopen(Request(fixture.url()+path, data=json.dumps(data).encode(), headers=headers), timeout=5))
                with self.assertRaises(HTTPError) as denied:
                    post('/api/update/queue', request, False)
                self.assertEqual(denied.exception.code, 403)
                post('/api/update/queue', request)
                server.STATE.update(status='running')
                self.assertFalse(post('/api/update/claim', request)['ready'])
                server.STATE.update(status='ready', released=True, deliveryCompleted=False)
                self.assertFalse(post('/api/update/claim', request)['ready'])
                post('/api/update/cancel', {})
                with self.assertRaises(HTTPError):
                    post('/api/update/claim', request)
                # An explicit Start over clears unsent state and its restore file.
                (server.WORK/'session.json').write_text('{}')
                post('/api/work/discard', {})
                self.assertFalse((server.WORK/'session.json').exists())
                post('/api/update/queue', request)
                # An in-flight POST holds admission through the entire operation.
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with server.OPERATIONS:
                        future = pool.submit(post, '/api/update/claim', request)
                        with self.assertRaises(TimeoutError):
                            future.result(timeout=0.15)
                    self.assertTrue(future.result(timeout=5)['ready'])
                with self.assertRaises(HTTPError) as stopped:
                    post('/api/solve', {})
                self.assertEqual(stopped.exception.code, 503)
        finally:
            fixture.tearDown()

    def test_channel_change_and_updates_off_cancel_waiting(self):
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            with patch.object(server, 'UPDATE_QUEUE', UpdateQueue()):
                pending = installer_update.stage_file(server.WORK, '99.0.0', hashlib.sha256(b'MZ').hexdigest(), b'MZ', 'eznest-setup.exe')
                data = {'ticket':'a'*32, 'sha256':pending['sha256']}
                def post(path):
                    return json.load(urlopen(Request(fixture.url()+path, data=json.dumps(data).encode(), headers={'X-EZ-Token':server.TOKEN})))
                post('/api/update/queue')
                shop_deploy.save_shop(server.WORK, False, False, True, channel='test')
                with self.assertRaises(HTTPError):
                    post('/api/update/claim')
                self.assertFalse(server.UPDATE_QUEUE.status()['queued'])
                shop_deploy.save_shop(server.WORK, False, False, True, channel='stable')
                post('/api/update/queue')
                shop_deploy.save_shop(server.WORK, False, False, False)
                with self.assertRaises(HTTPError):
                    post('/api/update/claim')
                self.assertFalse(server.UPDATE_QUEUE.status()['queued'])
        finally:
            fixture.tearDown()

    def test_update_ui_waiting_and_remote_pc(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            with sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page()
                    page.goto(fixture.url()+'/web')
                    fixture.wait_ready(page)
                    info = {'current':'1.0.0', 'managedSupported':True, 'staged':True, 'localPC':True, 'message':'Update ready.'}
                    def render(value):
                        return page.evaluate('''info => { showUpdate(info); return {
                            label: document.querySelector('#update').textContent,
                            disabled: document.querySelector('#update').disabled,
                            cancelHidden: document.querySelector('#update-cancel').hidden,
                            note: document.querySelector('#update-note').textContent
                        }; }''', value)
                    shown = render(info)
                    self.assertEqual(shown['label'], 'Install when finished')
                    self.assertFalse(shown['disabled'])
                    shown = render({**info, 'queued':True})
                    self.assertTrue(shown['disabled'])
                    self.assertFalse(shown['cancelHidden'])
                    shown = render({**info, 'localPC':False})
                    self.assertTrue(shown['disabled'])
                    self.assertIn('PC running eznest', shown['note'])
                    hot = server.WORK/'update-preview-hot'
                    hot.mkdir()
                    page.fill('#setup-hot', str(hot))
                    page.fill('#setup-printer', 'Test printer')
                    page.click('#setup-save')
                    page.wait_for_function("() => document.querySelector('#setup').hidden")
                    page.click('#settings-open')
                    render({**info, 'message':'Update ready. Choose Install when finished and approve the Windows prompt.'})
                    panel = page.locator('#settings .panel')
                    panel.evaluate("node => { node.style.maxHeight='none'; node.style.overflow='visible'; }")
                    shots = Path(__file__).resolve().parents[1]/'.local'/'screenshots'
                    shots.mkdir(parents=True, exist_ok=True)
                    panel.screenshot(path=str(shots/'update-ready-desktop.png'))
                    page.set_viewport_size({'width':390, 'height':900})
                    panel.screenshot(path=str(shots/'update-ready-mobile.png'))
                finally:
                    browser.close()
        finally:
            fixture.tearDown()
