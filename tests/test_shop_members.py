import opt_out
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import material_inventory
import server
import shop_auth
import shop_members as members
from test_material_inventory import values
import test_shop_auth


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        members.create(self.root, 'Test shop')

    def test_create_preserves_existing_inventory_and_cannot_replace_shop(self):
        material_inventory.save(self.root, 'roll', values(), 0)
        before = material_inventory.read(self.root)
        with self.assertRaises(ValueError): members.create(self.root, 'Another shop')
        self.assertEqual(material_inventory.read(self.root), before)
        self.assertEqual(members.status(self.root)['name'], 'Test shop')

    def test_one_invitation_can_only_be_used_once_concurrently(self):
        code = members.invite(self.root, now=100)['code']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda name: members.join(self.root, code, name, name, now=101), ['A', 'B']))
        self.assertEqual(sum('token' in r for r in results), 1)
        self.assertEqual(len(members.status(self.root, admin=True)['members']), 1)

    def test_expiry_cancellation_and_rate_limit(self):
        code = members.invite(self.root, now=100)['code']
        self.assertEqual(members.join(self.root, code, 'A', 'one', now=1000)['status'], 401)
        code = members.invite(self.root, now=1001)['code']
        members.cancel_invites(self.root)
        self.assertEqual(members.join(self.root, code, 'A', 'one', now=1002)['status'], 401)
        for _ in range(10): members.join(self.root, 'bad', 'A', 'blocked', now=1100)
        code = members.invite(self.root, now=1101)['code']
        self.assertEqual(members.join(self.root, code, 'A', 'blocked', now=1102)['status'], 429)
        self.assertIn('token', members.join(self.root, code, 'B', 'other', now=1103))

    def test_only_hashes_persist_and_member_can_be_revoked(self):
        code = members.invite(self.root, now=100)['code']
        result = members.join(self.root, code, 'Alex', 'one', now=101)
        token = result['token']
        raw = (self.root / members.DB).read_bytes()
        self.assertNotIn(token.encode(), raw)
        self.assertNotIn(code.replace('-', '').encode(), raw)
        self.assertEqual(members.member(self.root, token, now=102)['name'], 'Alex')
        self.assertIsNone(members.member(self.root, token, now=101 + members.SESSION_SECONDS))
        members.revoke(self.root, result['member']['id'])
        self.assertIsNone(members.member(self.root, token, now=103))

    def test_logout_and_cookie_security(self):
        result = members.join(self.root, members.invite(self.root)['code'], 'Alex', 'one')
        cookie = members.cookie(result['token'], secure=True)
        for flag in ('HttpOnly', 'SameSite=Strict', 'Secure', 'Path=/'): self.assertIn(flag, cookie)
        members.logout(self.root, result['token'])
        self.assertIsNone(members.member(self.root, result['token']))

    def test_invalid_names_and_cross_shop_invitation_fail(self):
        for name in ('', '\u202ehidden', 'a' * 81, None):
            with self.assertRaises(ValueError): members.clean_name(name)
        other = self.root / 'other'
        members.create(other, 'Other shop')
        code = members.invite(self.root)['code']
        self.assertEqual(members.join(other, code, 'A', 'one')['status'], 401)
        self.assertNotIn('members', members.status(self.root))


class MembershipHTTPTests(unittest.TestCase):
    handler = test_shop_auth.ShopAuthTests.handler

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patches = [patch.multiple(server, WORK=self.root, PORT=8765, LAN=True, HOST='0.0.0.0', TLS=False),
                        patch.object(server.Handler, 'allowed', return_value=True),
                        patch.object(server.Handler, 'origin_ok', return_value=True)]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        members.create(self.root, 'Test shop')

    def post(self, action, data, local=False, cookie=''):
        headers = {'Cookie': cookie}
        if local: headers['X-EZ-Token'] = server.TOKEN
        handler = self.handler('/api/shop-members/' + action, json.dumps(data).encode(), ip='127.0.0.1' if local else '192.168.1.50', headers=headers)
        handler.handle_post()
        return handler.sent[0]

    def join(self, name):
        result = self.post('join', {'code': members.invite(self.root)['code'], 'name': name})
        self.assertEqual(result[0], 200)
        self.assertNotIn('token', result[1])
        return result[2][0][1].split(';')[0]

    def test_members_share_the_same_inventory_and_stale_edit_is_rejected(self):
        cookies = [self.join('Alex'), self.join('Sam')]
        material_inventory.save(self.root, 'roll', values(), 0)
        for cookie in cookies:
            handler = self.handler('/api/materials', headers={'Cookie': cookie})
            handler.do_GET()
            self.assertEqual(handler.sent[0][0], 200)
            self.assertEqual(handler.sent[0][1]['materials'][0]['onHandMm'], 1000)
        material_inventory.reserve(self.root, 'roll', 'job', 200, 500, 'hash')
        material_inventory.transition(self.root, 'job', 'use')
        for cookie in cookies:
            handler = self.handler('/api/materials', headers={'Cookie': cookie})
            handler.do_GET()
            self.assertEqual(handler.sent[0][1]['materials'][0]['onHandMm'], 800)
        request = self.handler('/api/materials/save', json.dumps({'id': 'roll', 'profile': values(), 'revision': 1}).encode(), headers={'Cookie': cookies[0]})
        request.handle_post()
        self.assertNotEqual(request.sent[0][0], 200)

    def test_only_host_can_manage_members_and_revocation_blocks_reads(self):
        cookie = self.join('Alex')
        for action in ('invite', 'create', 'revoke', 'cancel-invites'):
            self.assertEqual(self.post(action, {'name': 'bad'}, cookie=cookie)[0], 403)
        member = members.status(self.root, admin=True)['members'][0]
        self.assertEqual(self.post('revoke', {'id': member['id']}, local=True)[0], 200)
        handler = self.handler('/api/materials', headers={'Cookie': cookie})
        handler.do_GET()
        self.assertEqual(handler.sent[0][0], 403)

    def test_join_requires_same_origin_and_local_only_cannot_invite(self):
        code = members.invite(self.root)['code']
        with patch.object(server.Handler, 'browser_site_ok', return_value=False):
            self.assertEqual(self.post('join', {'name': 'Alex', 'code': code})[0], 403)
        with patch.object(server, 'LAN', False):
            self.assertEqual(self.post('invite', {}, local=True)[0], 409)

    def test_legacy_pin_cannot_bypass_removed_member(self):
        shop_auth.set_pin(self.root, '12345678')
        sid = shop_auth.issue_session('192.168.1.50')
        handler = self.handler('/api/materials', headers={'Cookie': shop_auth.cookie_header(sid)})
        handler.do_GET()
        self.assertEqual(handler.sent[0][0], 403)


if __name__ == '__main__':
    unittest.main()
