"""LAN PIN, host-only shop controls, and source-folder confinement."""
import opt_out
import hashlib
import io
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

import launcher
import server
import shop_auth
import shop_deploy
from folder_queue import FolderQueue


class ShopAuthTests(unittest.TestCase):
    def setUp(self):
        tls = patch.multiple(server, TLS=False, TLS_CONTEXT=None)
        tls.start()
        self.addCleanup(tls.stop)
        self.old = (server.WORK, server.HOST, server.PORT, server.LAN)
        self.tmp = tempfile.TemporaryDirectory()
        server.WORK = Path(self.tmp.name)
        server.HOST = '0.0.0.0'
        server.PORT = 8765
        server.LAN = True
        shop_auth.reset_for_tests()
        shop_deploy.clear_name_cache()

    def tearDown(self):
        server.WORK, server.HOST, server.PORT, server.LAN = self.old
        shop_auth.reset_for_tests()
        shop_deploy.clear_name_cache()
        self.tmp.cleanup()

    def handler(self, path, body=b'{}', ip='192.168.1.50', host='192.168.1.50:8765', headers=None):
        item = server.Handler.__new__(server.Handler)
        item.path = path
        item.client_address = (ip, 41000)
        item.rfile = io.BytesIO(body)
        base = {
            'Host': host,
            'Content-Length': str(len(body)),
            'Content-Type': 'application/json',
            'Origin': 'http://' + host,
        }
        if headers:
            base.update(headers)
        item.headers = base
        item.sent = []

        def send(status, data, mime='application/json', filename=None, extra_headers=None):
            item.sent.append((status, data, extra_headers))

        item.send = send
        return item

    def test_unauthenticated_lan_cannot_read_the_token_or_write(self):
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            session = self.handler('/api/session')
            session.do_GET()
            self.assertEqual(session.sent[0][0], 200)
            self.assertNotIn('token', session.sent[0][1])
            self.assertFalse(session.sent[0][1]['authenticated'])
            stolen = self.handler('/api/materials/save', headers={'X-EZ-Token': server.TOKEN})
            stolen.handle_post()
            self.assertEqual(stolen.sent[0][0], 403)
            self.assertNotIn(server.TOKEN, json.dumps(stolen.sent[0][1]))
            bare = self.handler('/api/solve', body=b'{}')
            bare.handle_post()
            self.assertEqual(bare.sent[0][0], 403)

    def test_lan_session_requires_a_same_origin_signal(self):
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            missing = self.handler('/api/session', headers={'Origin': None})
            missing.do_GET()
            self.assertEqual(missing.sent[0][0], 403)
            cross = self.handler('/api/session', headers={'Sec-Fetch-Site': 'cross-site', 'Origin': 'https://evil.example'})
            cross.do_GET()
            self.assertEqual(cross.sent[0][0], 403)
            posted = self.handler('/api/login', body=b'{"pin":"123456"}', headers={'Origin': None, 'Sec-Fetch-Site': None})
            posted.handle_post()
            self.assertEqual(posted.sent[0][0], 403)

    def test_host_header_rejects_other_private_addresses(self):
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            foreign = self.handler('/api/session', ip='10.9.8.7', host='10.9.8.7:8765')
            foreign.do_GET()
            self.assertEqual(foreign.sent[0][0], 403)
            self.assertNotIn('token', json.dumps(foreign.sent[0][1]))

    def test_loopback_session_still_returns_the_token(self):
        item = self.handler('/api/session', ip='127.0.0.1', host='127.0.0.1:8765', headers={'Origin': None})
        item.do_GET()
        self.assertEqual(item.sent[0][1]['token'], server.TOKEN)
        self.assertTrue(item.sent[0][1]['localPC'])

    def test_pin_is_hashed_and_lockout_blocks_the_right_pin(self):
        shop_auth.set_pin(server.WORK, '12345678')
        stored = (server.WORK / 'shop-pin.json').read_text(encoding='utf-8')
        self.assertNotIn('12345678', stored)
        if os.name != 'nt':
            self.assertEqual((server.WORK / 'shop-pin.json').stat().st_mode & 0o777, 0o600)
        for attempt in range(shop_auth.LOCK_AFTER):
            self.assertEqual(shop_auth.login_attempt(server.WORK, '10.0.0.9', '000000', now=attempt), 'denied')
        self.assertEqual(shop_auth.login_attempt(server.WORK, '10.0.0.9', '12345678', now=shop_auth.LOCK_AFTER), 'locked')
        self.assertEqual(
            shop_auth.login_attempt(server.WORK, '10.0.0.9', '12345678', now=shop_auth.LOCK_AFTER + shop_auth.LOCK_SECONDS),
            'ok')
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            shop_auth.reset_for_tests()
            shop_auth.set_pin(server.WORK, '12345678')
            for _ in range(shop_auth.LOCK_AFTER):
                wrong = self.handler('/api/login', body=b'{"pin":"00000000"}')
                wrong.handle_post()
                self.assertEqual(wrong.sent[0][0], 401)
            blocked = self.handler('/api/login', body=b'{"pin":"12345678"}')
            blocked.handle_post()
            self.assertEqual(blocked.sent[0][0], 429)

    def test_login_sets_a_strict_cookie_and_host_settings_stay_on_the_host(self):
        shop_auth.set_pin(server.WORK, '12345678')
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            login = self.handler('/api/login', body=b'{"pin":"12345678"}')
            login.handle_post()
            self.assertEqual(login.sent[0][0], 200)
            self.assertNotIn('token', login.sent[0][1])
            cookie = login.sent[0][2][0][1]
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Strict', cookie)
            self.assertNotIn('Secure', cookie)
            self.assertIn(f'Max-Age={shop_auth.ABSOLUTE_SECONDS}', cookie)
            sid = cookie.split(';', 1)[0].split('=', 1)[1]
            headers = {'Cookie': 'eznest_session=' + sid}
            stock = self.handler('/api/materials', headers=headers)
            stock.do_GET()
            self.assertEqual(stock.sent[0][0], 200)
            for path in ('/api/shop', '/api/setup', '/api/folder/connect', '/api/output/connect'):
                item = self.handler(path, body=b'{}', headers=headers)
                item.handle_post()
                self.assertEqual(item.sent[0][0], 403, path)
            folder = self.handler('/api/folder/file?id=abc&revision=def', headers=headers)
            folder.do_GET()
            self.assertEqual(folder.sent[0][0], 403)

    def test_lan_bind_requires_a_saved_pin(self):
        with self.assertRaisesRegex(RuntimeError, 'shop PIN'):
            server.serve()
        argv = ['eznest', '--lan', '--no-browser', '--data-dir', str(server.WORK), '--port', '18765']
        # Without a PIN, --lan starts on loopback only and waits for the PIN.
        with patch('sys.argv', argv), patch('launcher.urlopen', side_effect=OSError('down')), patch('server.serve') as serve:
            try:
                self.assertEqual(launcher.main(), 0)
                serve.assert_called_once()
                self.assertEqual(os.environ['EZ_NEST_HOST'], '127.0.0.1')
                self.assertEqual(os.environ['EZ_NEST_LAN'], '0')
                self.assertEqual(os.environ.get('EZ_NEST_LAN_WAITING'), 'pin')
            finally:
                os.environ.pop('EZ_NEST_LAN_WAITING', None)
        shop_auth.set_pin(server.WORK, '12345678')
        self.assertTrue(shop_auth.pin_configured(server.WORK))

    def test_folder_prompt_is_not_pasted_into_powershell(self):
        captured = {}

        class Result:
            stdout = b''

        def run(args, **kwargs):
            captured['args'] = args
            captured['env'] = kwargs.get('env')
            return Result()

        with patch('server.os.name', 'nt'), patch('server.subprocess.run', side_effect=run):
            server.powershell_folder_picker("Select'; whoami", show_new=True)
        script = captured['args'][-1]
        self.assertNotIn('whoami', script)
        self.assertNotIn("';", script)
        self.assertEqual(captured['env']['EZ_NEST_FOLDER_PROMPT'], "Select'; whoami")
        self.assertIn('$env:EZ_NEST_FOLDER_PROMPT', script)

    def test_output_key_is_not_machine_scoped(self):
        text = Path(__file__).resolve().parents[1].joinpath('output_credential.py').read_text(encoding='utf-8')
        self.assertNotIn('_LOCAL_MACHINE', text)
        self.assertNotIn('CRYPTPROTECT_LOCAL_MACHINE', text)
        self.assertIn('_UI_FORBIDDEN', text)
        self.assertIn('eznest-svc', text)


    def test_backoff_grows_and_rotating_addresses_only_raise_a_host_alert(self):
        shop_auth.set_pin(server.WORK, '12345678')
        address = '10.2.2.2'
        for step in range(shop_auth.LOCK_AFTER):
            self.assertEqual(shop_auth.login_attempt(server.WORK, address, '00000000', now=step), 'denied')
        self.assertEqual(shop_auth.login_attempt(server.WORK, address, '12345678', now=shop_auth.LOCK_AFTER), 'locked')
        start = (shop_auth.LOCK_AFTER - 1) + shop_auth.backoff_seconds(1)
        for step in range(shop_auth.LOCK_AFTER):
            self.assertEqual(shop_auth.login_attempt(server.WORK, address, '00000000', now=start + step), 'denied')
        second = start + shop_auth.LOCK_AFTER - 1
        self.assertGreater(shop_auth.backoff_seconds(2), shop_auth.backoff_seconds(1))
        self.assertEqual(shop_auth.login_attempt(server.WORK, address, '12345678', now=second + shop_auth.backoff_seconds(1)), 'locked')
        self.assertEqual(shop_auth.login_attempt(server.WORK, address, '12345678', now=second + shop_auth.backoff_seconds(2)), 'ok')
        shop_auth.reset_for_tests()
        shop_auth.set_pin(server.WORK, '12345678')
        with self.assertLogs('eznest.pin', level='WARNING') as caught:
            for index in range(shop_auth.GLOBAL_ALERT_AFTER):
                self.assertEqual(
                    shop_auth.login_attempt(server.WORK, f'10.8.0.{index}', '00000000', now=index), 'denied')
        self.assertTrue(shop_auth.alert_status()['active'])
        self.assertIn('rotating addresses', caught.output[0])
        self.assertEqual(shop_auth.login_attempt(server.WORK, '10.9.9.9', '12345678', now=1000), 'ok')
        self.assertTrue(shop_auth.alert_status()['active'])
        noticed = self.handler('/api/session', ip='127.0.0.1', host='127.0.0.1:8765', headers={'Origin': None})
        noticed.do_GET()
        self.assertTrue(noticed.sent[0][1]['pinAlert']['active'])
        shop_auth.acknowledge_alert()
        self.assertFalse(shop_auth.alert_status()['active'])

    def test_old_short_pin_still_works_and_new_pins_must_be_stronger(self):
        salt = b'\x11' * 16
        digest = hashlib.scrypt(b'123456', salt=salt, n=shop_auth.SCRYPT_N, r=shop_auth.SCRYPT_R, p=shop_auth.SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
        (server.WORK / 'shop-pin.json').write_text(json.dumps({
            'v': 1, 'salt': salt.hex(), 'hash': digest.hex(), 'n': shop_auth.SCRYPT_N, 'r': shop_auth.SCRYPT_R, 'p': shop_auth.SCRYPT_P,
        }), encoding='utf-8')
        self.assertTrue(shop_auth.pin_is_weak(server.WORK))
        self.assertEqual(shop_auth.login_attempt(server.WORK, '10.0.0.4', '123456', now=1), 'ok')
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            host = self.handler('/api/session', ip='127.0.0.1', host='127.0.0.1:8765', headers={'Origin': None})
            host.do_GET()
            self.assertTrue(host.sent[0][1]['pinWeak'])
            designer = self.handler('/api/session')
            designer.do_GET()
            self.assertTrue(designer.sent[0][1]['pinWeak'])
            self.assertNotIn('pinAlert', designer.sent[0][1])
            self.assertNotIn('token', designer.sent[0][1])
        with self.assertRaisesRegex(ValueError, '8 to 12'):
            shop_auth.set_pin(server.WORK, '123456')
        shop_auth.set_pin(server.WORK, 'correct-horse')
        self.assertFalse(shop_auth.pin_is_weak(server.WORK))

    def test_session_is_bound_to_ip_and_expires_on_idle_absolute_and_logout(self):
        sid = shop_auth.issue_session('::ffff:192.168.1.50', now=0)
        self.assertTrue(shop_auth.session_valid(sid, '192.168.1.50', now=10))
        self.assertFalse(shop_auth.session_valid(sid, '192.168.1.51', now=11))
        again = shop_auth.issue_session('10.0.0.8', now=0)
        self.assertTrue(shop_auth.session_valid(again, '10.0.0.8', now=shop_auth.IDLE_SECONDS))
        self.assertFalse(shop_auth.session_valid(again, '10.0.0.8', now=shop_auth.IDLE_SECONDS + shop_auth.IDLE_SECONDS + 1))
        limited = shop_auth.issue_session('10.0.0.8', now=0)
        self.assertTrue(shop_auth.session_valid(limited, '10.0.0.8', now=shop_auth.IDLE_SECONDS - 1))
        self.assertFalse(shop_auth.session_valid(limited, '10.0.0.8', now=shop_auth.ABSOLUTE_SECONDS + 1))
        self.assertEqual(shop_auth.normalize_ip('::ffff:127.0.0.1'), '127.0.0.1')
        mapped = server.Handler.__new__(server.Handler)
        mapped.client_address = ('::ffff:127.0.0.1', 9)
        self.assertTrue(mapped.loopback_client())
        shop_auth.set_pin(server.WORK, '12345678')
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            login = self.handler('/api/login', body=b'{"pin":"12345678"}')
            login.handle_post()
            cookie = login.sent[0][2][0][1]
            headers = {'Cookie': cookie.split(';', 1)[0]}
            out = self.handler('/api/logout', body=b'{}', headers=headers)
            out.handle_post()
            self.assertEqual(out.sent[0][0], 200)
            self.assertIn('Max-Age=0', out.sent[0][2][0][1])
            stock = self.handler('/api/materials', headers=headers)
            stock.do_GET()
            self.assertEqual(stock.sent[0][0], 403)

    @unittest.skipUnless(shutil.which('openssl'), 'openssl is required to mint a local test certificate')
    def test_tls_sets_the_secure_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = Path(directory) / 'cert.pem', Path(directory) / 'key.pem'
            subprocess.run([
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', str(key), '-out', str(cert),
                '-days', '1', '-nodes', '-subj', '/CN=localhost',
            ], check=True, capture_output=True)
            if os.name != 'nt':
                os.chmod(key, 0o644)
                with self.assertRaisesRegex(ValueError, 'chmod 600'):
                    server.configure_tls(str(cert), str(key))
                self.assertFalse(server.TLS)
            os.chmod(key, 0o600)
            service = thread = None
            server.configure_tls(str(cert), str(key))
            try:
                service = server.LocalServer(('127.0.0.1', 0), server.Handler)
                server.PORT = service.server_port
                thread = threading.Thread(target=service.serve_forever, daemon=True)
                thread.start()
                shop_auth.set_pin(server.WORK, '12345678')
                context = ssl._create_unverified_context()
                base = f'https://127.0.0.1:{server.PORT}'
                with urlopen(base + '/api/session', timeout=3, context=context) as response:
                    self.assertTrue(json.load(response)['tls'])
                body = json.dumps({'pin': '12345678'}).encode()
                request_headers = {
                    'Content-Type': 'application/json',
                    'Origin': f'https://127.0.0.1:{server.PORT}',
                }
                from urllib.request import Request
                with urlopen(Request(base + '/api/login', data=body, headers=request_headers), timeout=3, context=context) as response:
                    cookie = response.headers.get('Set-Cookie')
                self.assertIn('Secure', cookie)
                self.assertIn('HttpOnly', cookie)
            finally:
                if service is not None:
                    service.shutdown()
                    service.server_close()
                if thread is not None:
                    thread.join(timeout=3)
                server.configure_tls(None, None)
                server.PORT = self.old[2]


class SourceFolderTests(unittest.TestCase):
    def test_connect_and_read_stay_inside_approved_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ready = root / 'ready'
            outside = root / 'outside'
            ready.mkdir()
            outside.mkdir()
            (outside / 'secret.svg').write_text('secret', encoding='utf-8')
            (ready / 'piece.svg').write_text('<svg/>', encoding='utf-8')
            linked = root / 'linked'
            linked.symlink_to(outside, target_is_directory=True)
            queue = FolderQueue(root / 'folder.json')
            with self.assertRaisesRegex(ValueError, 'link'):
                queue.connect(str(linked))
            with self.assertRaisesRegex(ValueError, 'upward'):
                queue.connect(str(ready / '..' / 'outside'))
            approved = []
            guarded = FolderQueue(root / 'guard.json', approved=lambda: list(approved))
            with self.assertRaisesRegex(ValueError, 'approved'):
                guarded.connect(str(ready))
            approved.append(str(ready))
            guarded.connect(str(ready))
            leak = ready / 'leak.svg'
            leak.symlink_to(outside / 'secret.svg')
            guarded.entries['evil'] = leak
            with self.assertRaisesRegex(ValueError, 'connected folder'):
                guarded.read('evil', 'x')
            guarded.entries['outside'] = outside / 'secret.svg'
            with self.assertRaisesRegex(ValueError, 'connected folder'):
                guarded.read('outside', 'x')
            (root / 'guard.json').write_text(json.dumps({'path': str(outside)}), encoding='utf-8')
            reloaded = FolderQueue(root / 'guard.json', approved=lambda: [str(ready)])
            self.assertIsNone(reloaded.root)
            self.assertFalse(reloaded.scan()['connected'])


if __name__ == '__main__':
    unittest.main()
