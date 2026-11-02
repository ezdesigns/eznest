"""First-use OUTPUT computer authorization. No live Privy/OUTPUT mutation."""
import opt_out
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import build_windows
import output_credential
import output_gate
import output_pairing
import server
import test_output_gate

TOKEN = 'osa_' + 'C' * 43


class AccountEntryTests(unittest.TestCase):
    def setUp(self):
        previous = dict(server.STATE)
        self.addCleanup(lambda: (server.STATE.clear(), server.STATE.update(previous)))
        self.helper = test_output_gate.GateTests(); self.helper.setUp()
        self.addCleanup(self.helper.tearDown)

    def request(self, path, body=None, headers=None, ip='127.0.0.1'):
        handler = self.helper.handler(path, json.dumps(body or {}).encode(), headers=headers, ip=ip)
        handler.handle_post() if body is not None else handler.do_GET()
        return handler.sent[0][:2]

    def test_unpaired_is_not_authorized_and_local_reads_are_preserved(self):
        status, session = self.request('/api/session')
        self.assertEqual(status, 200)
        self.assertFalse(session['account']['ready'])
        self.assertEqual(session['account']['connectUrl'], 'https://output.jeezlabs.io/workspace?tools=eznest')
        self.assertEqual(self.request('/api/materials')[0], 200)
        for route in ['/api/solve', '/api/document/import', '/api/materials/save', '/api/release', '/api/setup']:
            status, body = self.request(route, {})
            self.assertEqual(status, 403, route)
            self.assertEqual(body['code'], 'sign_in_required')

    def test_only_successful_code_redemption_unlocks_local_work(self):
        with patch('output_pairing._post', return_value=(401, b'{"error":{"code":"expired"}}')):
            self.assertEqual(self.request('/api/telemetry/output/pair', {'code': 'ABCDE-FGHJK'})[0], 400)
        self.assertFalse(output_gate.account_status(server.WORK, True)['ready'])
        payload = {'outcome': 'created', 'result': {'token': TOKEN, 'outpostId': 'fixture-shop'}}
        with patch('output_pairing._post', return_value=(200, json.dumps(payload).encode())), patch('output_gate.check_in'):
            self.assertEqual(self.request('/api/telemetry/output/pair', {'code': 'ABCDE-FGHJK'})[0], 200)
        status, session = self.request('/api/session')
        self.assertTrue(session['account']['ready'])
        self.assertNotIn(TOKEN, json.dumps(session))
        status, _body = self.request('/api/setup', {'printer': 'Fixture printer', 'units': 'mm', 'thru': 'Thru', 'kiss': 'Kiss', 'hotFolder': ''})
        self.assertEqual(status, 200)
        self.assertTrue(server.load_shop(server.WORK)['setupComplete'])
        self.assertFalse(server.load_shop(server.WORK)['outputNetwork'])
        self.assertFalse(server.telemetry_sender.status(server.WORK)['enabled'])

    def test_replay_without_credential_does_not_unlock(self):
        with patch('output_pairing._post', return_value=(200, b'{"outcome":"replay","result":{}}')):
            status, _body = self.request('/api/telemetry/output/pair', {'code': 'ABCDE-FGHJK'})
        self.assertEqual(status, 400)
        self.assertFalse(output_gate.account_status(server.WORK, True)['ready'])

    def test_offline_receipt_survives_restart_and_has_no_local_age_limit(self):
        self.helper.pair(age_seconds=120 * 86400)
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertTrue(output_gate.account_status(server.WORK, True)['ready'])
        # A second status read reconstructs authorization only from protected disk state.
        self.assertTrue(output_gate.account_status(Path(str(server.WORK)), True)['ready'])
        self.assertEqual(self.request('/api/solve', {})[0], 400)  # body validated, not account-blocked

    def test_tamper_future_and_disconnect_require_authorization_again(self):
        self.helper.pair()
        state = output_gate._read_state(server.WORK)
        state['lastOkAt'] += 1
        output_gate._state_path(server.WORK).write_text(json.dumps(state))
        self.assertFalse(output_gate.account_status(server.WORK, True)['ready'])
        # Use a fresh directory: tampering permanently revokes that credential.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); output_credential.save(directory, TOKEN)
            output_gate.note_paired(directory, now=int(time.time()) + 3600)
            self.assertFalse(output_gate.account_status(directory, True)['ready'])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); output_credential.save(directory, TOKEN); output_gate.note_paired(directory)
            output_pairing.disconnect(directory)
            self.assertFalse(output_gate.account_status(directory, True)['ready'])

    def test_known_revocation_blocks_mutations_but_keeps_job_and_stock(self):
        self.helper.pair(); server.STATE.update(status='ready', id='fixture-kept')
        material = server.WORK / 'fixture-artwork.svg'; material.write_bytes(b'fixture-preserved')
        digest = hashlib.sha256(material.read_bytes()).hexdigest()
        output_gate._mark_revoked(server.WORK, TOKEN, int(time.time()))
        self.assertEqual(self.request('/api/materials/save', {})[0], 403)
        self.assertEqual(server.STATE['id'], 'fixture-kept')
        self.assertEqual(hashlib.sha256(material.read_bytes()).hexdigest(), digest)
        self.assertEqual(self.request('/api/state')[0], 200)

    def test_unpaired_and_revoked_illustrator_apply_cannot_write_output(self):
        server.STATE.update(status='ready', id='a' * 32, job={'captureId': 'fixture-capture'}, result={'placements': []})
        for revoked in [False, True]:
            if revoked:
                self.helper.pair(); output_gate._mark_revoked(server.WORK, TOKEN, int(time.time()))
            status, body = self.request('/api/prepare-apply', {'id': 'a' * 32})
            self.assertEqual(status, 403)
            self.assertEqual(body['code'], 'sign_in_required')
            self.assertFalse((server.WORK / 'apply.json').exists())

    def test_origin_token_and_host_only_pairing_still_apply(self):
        for headers in [{'Origin': 'https://evil.example'}, {'X-EZ-Token': 'wrong'}, {'Host': 'evil.example'}]:
            self.assertEqual(self.request('/api/telemetry/output/pair', {'code': 'ABCDE-FGHJK'}, headers=headers)[0], 403)
        self.assertFalse(output_gate.account_status(server.WORK, False)['canConnect'])
        self.assertEqual(self.request('/api/telemetry/output/pair', {'code': 'ABCDE-FGHJK'}, ip='192.168.1.7')[0], 403)

    def test_installed_build_ignores_source_development_opt_out(self):
        with patch.dict(os.environ, {'EZ_NEST_DEV': '1', 'EZ_NEST_OUTPUT_GATE_OPEN': '1'}):
            self.assertTrue(output_gate.account_status(server.WORK, True)['devMode'])
            with patch('sys.frozen', True, create=True):
                self.assertFalse(output_gate.account_status(server.WORK, True)['ready'])

    def test_both_packaged_workspaces_load_shared_entry(self):
        for name in ['production.html', 'web.html']:
            html = (server.ROOT / name).read_text(encoding='utf-8')
            self.assertIn('/account-entry.js', html)
            self.assertIn('/account-entry.css', html)
        for name in ['account-entry.js', 'account-entry.css']:
            self.assertIn(name, build_windows.STATIC)
            self.assertEqual(self.request('/' + name)[0], 200)
