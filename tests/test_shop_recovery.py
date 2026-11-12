"""A missing browser sign-in can recover an existing private job with host approval."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shop_members as members
import server
import test_shop_auth


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        members.create(self.root, 'Shop')
        self.person = members.join(self.root, members.invite(self.root, now=100)['code'], 'Alex', 'first', now=101)['member']

    def pending(self, name='Alex', source='192.0.2.50'):
        response = members.request_recovery(self.root, name, source, now=200)
        with members.database(self.root) as db:
            request_id = db.execute('SELECT id FROM recovery WHERE hash=?', (members.digest(response['proof']),)).fetchone()[0]
        return response['proof'], request_id

    def test_host_approval_restores_same_identity_without_an_invite_or_new_member(self):
        proof, request_id = self.pending()
        self.assertEqual(members.finish_recovery(self.root, proof, now=201), {'state':'pending'})
        self.assertNotIn(proof.encode(), (self.root / members.DB).read_bytes())
        members.decide_recovery(self.root, request_id, self.person['id'], now=202)
        result = members.finish_recovery(self.root, proof, now=203)
        self.assertEqual(result['member'], self.person)
        self.assertEqual(members.member(self.root, result['token'], now=204), self.person)
        self.assertEqual(len(members.status(self.root, admin=True)['members']), 1)
        self.assertEqual(members.finish_recovery(self.root, proof, now=204), {'state':'expired'})

    def test_claimed_name_never_authenticates_or_discloses_existing_people(self):
        for name in ('Alex', 'Unknown person'):
            response = members.request_recovery(self.root, name, name, now=200)
            self.assertEqual(set(response), {'proof','state'})
            self.assertEqual(response['state'], 'pending')
            self.assertEqual(members.finish_recovery(self.root, response['proof'], now=201), {'state':'pending'})
        self.assertIsNone(members.recovery_state(self.root, 'invalid', now=201))
        self.assertNotIn('accessRequests', members.status(self.root))
        self.assertNotIn('accessRequests', members.status(self.root, include_members=True))

    def test_wrong_proof_denial_expiry_and_revocation_cannot_restore_access(self):
        proof, request_id = self.pending()
        self.assertEqual(members.finish_recovery(self.root, 'x'*43, now=201), {'state':'expired'})
        members.decide_recovery(self.root, request_id, now=202)
        self.assertEqual(members.finish_recovery(self.root, proof, now=203), {'state':'denied'})
        with self.assertRaises(ValueError): members.decide_recovery(self.root, request_id, self.person['id'], now=204)
        proof, request_id = self.pending(source='next')
        members.decide_recovery(self.root, request_id, self.person['id'], now=202)
        self.assertEqual(members.finish_recovery(self.root, proof, now=1100), {'state':'expired'})
        members.revoke(self.root, self.person['id'])
        self.assertEqual(members.finish_recovery(self.root, proof, now=203), {'state':'expired'})

    def test_request_is_bounded_idempotent_and_rejects_nonexistent_member(self):
        proof, request_id = self.pending()
        again = members.request_recovery(self.root, 'Alex', '192.0.2.50', proof, now=201)
        self.assertEqual(again['proof'], proof)
        with self.assertRaises(ValueError): members.decide_recovery(self.root, request_id, 'a'*32, now=202)
        for _ in range(2): self.pending()
        self.assertEqual(members.request_recovery(self.root, 'Alex', '192.0.2.50', now=203)['status'], 429)
        self.assertIn('proof', members.request_recovery(self.root, 'Alex', '192.0.2.50', now=1101))

    def test_global_limit_and_concurrent_claim_are_atomic(self):
        proof, request_id = self.pending()
        for i in range(19): self.pending(source=str(i))
        self.assertEqual(members.request_recovery(self.root, 'Name', 'extra', now=201)['status'], 429)
        members.decide_recovery(self.root, request_id, self.person['id'], now=202)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:members.finish_recovery(self.root, proof, now=203), range(2)))
        self.assertEqual(sum(r['state']=='restored' for r in results), 1)
        self.assertEqual(sum(r['state']=='expired' for r in results), 1)

    def test_cancelled_request_cannot_restore_approved_access(self):
        proof, request_id = self.pending()
        members.decide_recovery(self.root, request_id, self.person['id'], now=202)
        members.cancel_recovery(self.root, proof)
        self.assertEqual(members.finish_recovery(self.root, proof, now=203), {'state':'expired'})


class RecoveryHTTPTests(unittest.TestCase):
    handler = test_shop_auth.ShopAuthTests.handler

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for item in (patch.multiple(server, WORK=self.root, LAN=True, TLS=False),
                     patch.object(server.Handler, 'allowed', return_value=True),
                     patch.object(server.Handler, 'origin_ok', return_value=True)):
            item.start(); self.addCleanup(item.stop)
        members.create(self.root, 'Test shop')
        self.person = members.join(self.root, members.invite(self.root)['code'], 'Alex', 'old-browser')['member']

    def post(self, path, data, *, local=False, cookie='', headers=None):
        fields = {'Cookie':cookie, **(headers or {})}
        if local: fields['X-EZ-Token'] = server.TOKEN
        handler = self.handler('/api/shop-members/' + path, json.dumps(data).encode(), ip='127.0.0.1' if local else '192.0.2.50', headers=fields)
        handler.handle_post()
        return handler.sent[0]

    def test_remote_request_host_approval_and_cookie_only_claim_restore_private_workspace(self):
        response = self.post('recover', {'name':'Alex'}, headers={'X-Forwarded-For':'127.0.0.1'})
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1], {'state':'pending'})
        cookie = response[2][0][1].split(';')[0]
        for flag in ('HttpOnly','SameSite=Strict','Max-Age=900'): self.assertIn(flag, response[2][0][1])
        access = members.status(self.root, admin=True)['accessRequests'][0]
        self.assertEqual(access['source'], '192.0.2.50')
        for action in ('approve-recovery', 'deny-recovery'):
            self.assertEqual(self.post(action, {'id':access['id'],'member':self.person['id']}, cookie=cookie, headers={'X-EZ-Token':server.TOKEN})[0],403)
        self.assertEqual(self.post('approve-recovery', {'id':access['id'],'member':self.person['id']}, local=True)[0],200)
        self.assertEqual(self.post('recovery-status', {})[1], {'state':'expired'})
        claimed = self.post('recovery-status', {}, cookie=cookie)
        self.assertEqual(claimed[1], {'state':'restored'})
        member_cookie = claimed[2][0][1].split(';')[0]
        handler = self.handler('/api/session', headers={'Cookie':member_cookie})
        handler.do_GET()
        self.assertTrue(handler.sent[0][1]['authenticated'])
        self.assertEqual(handler.workspace_owner(), 'member-' + self.person['id'])
        self.assertEqual(self.post('recovery-status', {}, cookie=member_cookie)[1], {'state':'restored'})
        self.assertEqual(len(members.status(self.root, admin=True)['members']), 1)

    def test_recovery_requires_same_origin_and_lan_and_host_validates_requests(self):
        with patch.object(server.Handler, 'browser_site_ok', return_value=False):
            self.assertEqual(self.post('recover', {'name':'Alex'})[0],403)
            self.assertEqual(self.post('recovery-status', {})[0],403)
        with patch.object(server, 'LAN', False):
            self.assertEqual(self.post('recover', {'name':'Alex'})[0],409)
        self.assertEqual(self.post('recover', {'name':'x'*5000})[0],400)
        self.assertEqual(self.post('approve-recovery', {'id':'x','member':{}}, local=True)[0],400)

    def test_logout_cancels_pending_browser_recovery(self):
        response = self.post('recover', {'name':'Alex'})
        cookie = response[2][0][1].split(';')[0]
        handler = self.handler('/api/logout', headers={'Cookie':cookie})
        handler.handle_post()
        self.assertEqual(handler.sent[0][0], 200)
        self.assertTrue(any(members.RECOVERY_COOKIE+'=;' in value and 'Max-Age=0' in value for _,value in handler.sent[0][2]))
        self.assertEqual(self.post('recovery-status', {}, cookie=cookie)[1], {'state':'expired'})


if __name__ == '__main__': unittest.main()
