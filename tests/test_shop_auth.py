"""LAN PIN, host-only shop controls, and source-folder confinement."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher
import server
import shop_auth
import shop_deploy
from folder_queue import FolderQueue


class ShopAuthTests(unittest.TestCase):
    def setUp(self):
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
        shop_auth.set_pin(server.WORK, '123456')
        stored = (server.WORK / 'shop-pin.json').read_text(encoding='utf-8')
        self.assertNotIn('123456', stored)
        self.assertEqual((server.WORK / 'shop-pin.json').stat().st_mode & 0o777, 0o600)
        for attempt in range(shop_auth.LOCK_AFTER):
            self.assertEqual(shop_auth.login_attempt(server.WORK, '10.0.0.9', '000000', now=attempt), 'denied')
        self.assertEqual(shop_auth.login_attempt(server.WORK, '10.0.0.9', '123456', now=shop_auth.LOCK_AFTER), 'locked')
        self.assertEqual(
            shop_auth.login_attempt(server.WORK, '10.0.0.9', '123456', now=shop_auth.LOCK_AFTER + shop_auth.LOCK_SECONDS),
            'ok')
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            shop_auth.reset_for_tests()
            shop_auth.set_pin(server.WORK, '123456')
            for _ in range(shop_auth.LOCK_AFTER):
                wrong = self.handler('/api/login', body=b'{"pin":"000000"}')
                wrong.handle_post()
                self.assertEqual(wrong.sent[0][0], 401)
            blocked = self.handler('/api/login', body=b'{"pin":"123456"}')
            blocked.handle_post()
            self.assertEqual(blocked.sent[0][0], 429)

    def test_login_sets_a_strict_cookie_and_host_settings_stay_on_the_host(self):
        shop_auth.set_pin(server.WORK, '123456')
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            login = self.handler('/api/login', body=b'{"pin":"123456"}')
            login.handle_post()
            self.assertEqual(login.sent[0][0], 200)
            self.assertNotIn('token', login.sent[0][1])
            cookie = login.sent[0][2][0][1]
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Strict', cookie)
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
        with patch('sys.argv', argv):
            with self.assertRaisesRegex(ValueError, 'shop PIN'):
                launcher.main()
        shop_auth.set_pin(server.WORK, '123456')
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


class SourceFolderTests(unittest.TestCase):
    def test_connect_and_read_stay_inside_approved_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
