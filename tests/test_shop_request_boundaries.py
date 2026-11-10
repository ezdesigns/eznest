"""Exercise the shop HTTP handlers with dummy data and no listening socket."""
import opt_out
import hashlib
import io
import json
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import server
import shop_auth
import shop_members
from output_folder import FILES, OutputFolder
import test_shop_auth
from update_queue import UpdateQueue


class ShopRequestBoundaries(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = OutputFolder(self.root / 'output-folder.json')
        for context in (
            patch.multiple(server, WORK=self.root, PORT=8765, LAN=True, TLS=False, OUTPUT=self.output,
                           STATE={'status': 'idle'}, UPDATE_QUEUE=UpdateQueue()),
            patch.object(server, 'shop_name_allowed', side_effect=lambda host: host == '192.168.1.50'),
            patch.object(server.macos_service_runtime, 'active', return_value=False),
            patch.object(server.macos_service_runtime, 'maintenance', return_value=False),
            patch.object(server, 'record_workload'),
        ):
            context.start()
            self.addCleanup(context.stop)
        shop_auth.reset_for_tests()
        self.addCleanup(shop_auth.reset_for_tests)

    def request(self, path, data=None, local=False, headers=None):
        options = {'ip': '127.0.0.1', 'host': '127.0.0.1:8765'} if local else {}
        handler = test_shop_auth.ShopAuthTests.handler(self, path, json.dumps(data or {}).encode(), headers=headers, **options)
        http_headers = Message()
        for name, value in handler.headers.items():
            if value is not None:
                http_headers[name] = value
        handler.headers = http_headers
        return handler

    def member_cookie(self):
        shop_members.create(self.root, 'Fixture shop')
        joined = shop_members.join(self.root, shop_members.invite(self.root)['code'], 'Designer', '192.168.1.50')
        return shop_members.cookie(joined['token']).split(';')[0]

    def test_tunnel_headers_do_not_admit_a_loopback_request(self):
        direct = self.request('/api/session', local=True, headers={'Origin': None})
        direct.do_GET()
        self.assertEqual(direct.sent[0][0], 200)
        self.assertIn('token', direct.sent[0][1])
        for name in ('cF-rAy', 'CF-Connecting-IP', 'Forwarded', 'X-Forwarded-For', 'Via'):
            with self.subTest(header=name):
                proxied = self.request('/api/session', local=True, headers={'Origin': None, name: 'fixture'})
                proxied.close_connection = False
                proxied.do_GET()
                self.assertEqual((proxied.sent[0][0], 'token' in proxied.sent[0][1], proxied.close_connection),
                                 (403, False, True))
        proxied = self.request('/api/shop', {'printer': 'Fixture printer'}, local=True,
                               headers={'Origin': None, 'CF-Ray': 'fixture', 'X-EZ-Token': server.TOKEN})
        with patch.object(server, 'save_shop', wraps=server.save_shop) as save:
            proxied.do_POST()
            self.assertEqual((proxied.sent[0][0], save.called), (403, False))

    def test_only_host_token_can_stop_the_shop(self):
        shop_auth.set_pin(self.root, '48151623')
        def pin_cookie():
            return shop_auth.cookie_header(shop_auth.issue_session('192.168.1.50')).split(';')[0]

        for session in (pin_cookie, self.member_cookie):
            with self.subTest(session=session.__name__):
                cookie = session()
                stopped = threading.Event()
                handler = self.request('/api/shutdown', headers={'Cookie': cookie})
                handler.server = SimpleNamespace(shutdown=stopped.set)
                handler.do_POST()
                status = handler.sent[0][0]
                called = stopped.wait(1) if status == 200 else stopped.is_set()
                self.assertEqual((status, called), (403, False))
        local = self.request('/api/shutdown', local=True, headers={'X-EZ-Token': server.TOKEN})
        stopped = threading.Event()
        local.server = SimpleNamespace(shutdown=stopped.set)
        local.do_POST()
        self.assertEqual(local.sent[0][0], 200)
        self.assertTrue(stopped.wait(1))

    def test_anonymous_access_body_does_not_hold_operations(self):
        for path in ('/api/login', '/api/shop-members/join'):
            with self.subTest(path=path):
                reading = threading.Event()
                release = threading.Event()
                finished = threading.Event()

                def read(size):
                    reading.set()
                    release.wait(3)
                    return b'{}'

                public = self.request(path)
                public.rfile = SimpleNamespace(read=read)
                owner = self.request('/api/export/folders', {'path': str(self.root)}, local=True,
                                     headers={'X-EZ-Token': server.TOKEN})

                def owner_post():
                    owner.do_POST()
                    finished.set()

                first = threading.Thread(target=public.do_POST, daemon=True)
                second = threading.Thread(target=owner_post, daemon=True)
                first.start()
                try:
                    self.assertTrue(reading.wait(1))
                    second.start()
                    self.assertTrue(finished.wait(1), 'A body read held shared POST admission')
                    self.assertEqual(owner.sent[0][0], 200)
                finally:
                    release.set()
                    first.join(3)
                    if second.ident:
                        second.join(3)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())

    def test_public_access_checks_maintenance_again_after_reading(self):
        shop_members.create(self.root, 'Fixture shop')
        invitation = {'code': shop_members.invite(self.root)['code'], 'name': 'Designer'}
        join = self.request('/api/shop-members/join', invitation)

        def read(size):
            server.UPDATE_QUEUE.stopping = True
            return json.dumps(invitation).encode()

        join.rfile = SimpleNamespace(read=read)
        join.do_POST()
        self.assertEqual(join.sent[0][0], 503)
        self.assertEqual(shop_members.status(self.root, admin=True)['members'], [])

    def test_only_host_can_choose_a_staging_destination(self):
        cookie = self.member_cookie()
        batch = 'a' * 32
        primary = self.root / 'primary'
        staging = self.root / 'staging'
        primary.mkdir()
        staging.mkdir()
        self.output.root = primary
        content = io.BytesIO()
        with ZipFile(content, 'w') as pack:
            for name in sorted(FILES):
                pack.writestr(name, 'fixture')
        payload = content.getvalue()
        (self.root / 'batches').mkdir()
        (self.root / 'batches' / (batch + '.zip')).write_bytes(payload)
        server.STATE.update(status='ready', released=True, id=batch, job={})
        for path, data in (
            ('/api/release', {'id': batch}),
            ('/api/export/save', {'id': batch, 'name': 'test.zip', 'format': 'pack', 'destination': 'folder',
                                  'sha256': hashlib.sha256(payload).hexdigest()}),
        ):
            with self.subTest(path=path):
                data['stagingFolder'] = str(staging)
                designer = self.request(path, data, headers={'Cookie': cookie})
                designer.do_POST()
                self.assertEqual((designer.sent[0][0], (staging / ('eznest-' + batch)).exists()), (403, False))
                self.assertEqual(list(staging.iterdir()), [])
                self.assertEqual(list(primary.iterdir()), [])
        local = self.request('/api/release', {'id': batch, 'stagingFolder': str(staging)}, local=True,
                             headers={'X-EZ-Token': server.TOKEN})
        local.do_POST()
        self.assertEqual(local.sent[0][0], 200)
        self.assertTrue((staging / ('eznest-' + batch) / 'batch.json').is_file())
        # Designers deliver their own prepared batch, never the host's active job.
        import job_workspaces
        with job_workspaces.select(self.root, designer.workspace_owner(), server.restore_state):
            own_batches = server.job_root() / 'batches'
            own_batches.mkdir(exist_ok=True)
            (own_batches / (batch + '.zip')).write_bytes(payload)
            server.job_state().update(status='ready', released=True, id=batch, job={})
        for path, data in (
            ('/api/release', {'id': batch}),
            ('/api/export/save', {'id': batch, 'name': 'test.zip', 'format': 'pack', 'destination': 'folder',
                                  'sha256': hashlib.sha256(payload).hexdigest()}),
        ):
            with self.subTest(normal_delivery=path):
                designer = self.request(path, data, headers={'Cookie': cookie})
                designer.do_POST()
                self.assertEqual(designer.sent[0][0], 200)
