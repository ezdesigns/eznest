"""Browser approval uses fake OUTPUT responses; no live shop or credentials."""
import opt_out
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import output_credential
import output_link as link
import output_pairing
import server
import test_output_gate

LINK = '12345678-1234-4234-8234-123456789abc'
TOKEN = 'osa_' + 'B' * 43

def response(state='pending', **extra):
    result = dict(linkId=LINK, state=state, userCode='ABCD-2345',
                  expiresAt=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
    result.update(extra)
    return 200, json.dumps({'outcome': 'ok', 'result': result}).encode()

class LinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        link.ATTEMPTS.clear()
        self.addCleanup(link.ATTEMPTS.clear)

    def start(self):
        return link.start(self.root, transport=lambda _: response(), host='TEST-PC')

    def poll(self, attempt, state='pending', **kwargs):
        link.ATTEMPTS[link._key(self.root)]['nextPoll'] = 0
        return link.status(self.root, attempt['attemptId'], transport=lambda _: response(state), **kwargs)

    def test_start_sends_hash_only_and_exposes_no_redeem_secret(self):
        seen = []
        result = link.start(self.root, transport=lambda raw: (seen.append(json.loads(raw)) or response()), host='TEST-PC')
        stored = link.ATTEMPTS[link._key(self.root)]
        self.assertEqual(set(seen[0]), {'op', 'requestId', 'codeHash', 'hostLabel'})
        self.assertNotIn(stored['code'], json.dumps(result) + json.dumps(seen))
        self.assertEqual(result['approvalUrl'], 'https://output.jeezlabs.io/outpost/ez-nest/approve?link=' + LINK)
        self.assertEqual(list(self.root.iterdir()), [])
        again = link.start(self.root, transport=Mock(side_effect=AssertionError('duplicate request')))
        self.assertEqual(again['attemptId'], result['attemptId'])

    def test_failed_start_reuses_request_and_hash(self):
        seen = []
        def offline(raw):
            seen.append(json.loads(raw))
            raise output_pairing.PairingError('offline', 'offline')
        with self.assertRaises(output_pairing.PairingError):
            link.start(self.root, transport=offline, host='TEST-PC')
        link.start(self.root, transport=lambda raw: (seen.append(json.loads(raw)) or response()), host='TEST-PC')
        self.assertEqual(seen[0], seen[1])

    def test_pending_and_denied_never_pair(self):
        attempt = self.start()
        with patch.object(output_pairing, 'connect') as pair:
            self.assertEqual(self.poll(attempt)['state'], 'pending')
            self.assertEqual(self.poll(attempt, 'denied')['state'], 'denied')
            self.assertEqual(self.poll(attempt, 'approved')['state'], 'denied')
            pair.assert_not_called()
        self.assertIsNone(link.ATTEMPTS[link._key(self.root)]['code'])
        self.assertFalse(output_credential.path(self.root).exists())

    def test_approval_redeems_once_then_waits_for_verified_check_in(self):
        attempt = self.start()
        def pair(raw):
            body = json.loads(raw)
            self.assertEqual(body['code'].replace('-', ''), held)
            return 200, json.dumps({'outcome': 'created', 'result': {'token': TOKEN, 'shopName': 'Test Shop'}}).encode()
        held = link.ATTEMPTS[link._key(self.root)]['code']
        # Mock only OS credential persistence; the actual exchange + connect run.
        with patch.object(output_credential, 'save') as save, patch('output_gate.note_paired'), patch('output_gate.check_in') as check:
            check.return_value = {'ok': False}
            self.assertEqual(self.poll(attempt, 'approved', pair_transport=pair, check_in_transport=Mock())['state'], 'connecting')
            self.assertNotIn('code', link.ATTEMPTS[link._key(self.root)])
            save.assert_called_once_with(self.root, TOKEN, 'Test Shop')
            self.assertEqual(self.poll(attempt, 'approved')['state'], 'connecting')
            self.assertEqual(self.poll(attempt, 'connected')['state'], 'connected')
            self.assertEqual(self.poll(attempt, 'connected')['state'], 'connected')
            save.assert_called_once()
        self.assertFalse((self.root / 'output-consent.json').exists())

    def test_expiry_cancel_and_unknown_attempt_cannot_redeem(self):
        attempt = self.start()
        self.assertEqual(link.status(self.root, 'other')['state'], 'expired')
        link.cancel(self.root, attempt['attemptId'])
        self.assertEqual(self.poll_unknown(attempt)['state'], 'expired')
        attempt = self.start()
        link.ATTEMPTS[link._key(self.root)]['deadline'] = 0
        with patch.object(output_pairing, 'connect') as pair:
            self.assertEqual(self.poll(attempt, 'approved')['state'], 'expired')
            pair.assert_not_called()

    def poll_unknown(self, attempt):
        return link.status(self.root, attempt['attemptId'], transport=Mock(side_effect=AssertionError()))

    def test_failed_redemption_does_not_repeat(self):
        attempt = self.start()
        with patch.object(output_pairing, 'connect', side_effect=output_pairing.PairingError('offline', 'offline')) as pair:
            with self.assertRaises(output_pairing.PairingError):
                self.poll(attempt, 'approved')
            self.assertEqual(self.poll(attempt, 'approved')['state'], 'failed')
            pair.assert_called_once()
        self.assertNotIn('code', link.ATTEMPTS[link._key(self.root)])

    def test_poll_rate_limit_and_response_binding(self):
        attempt = self.start()
        transport = Mock(return_value=response())
        link.status(self.root, attempt['attemptId'], transport=transport)
        link.status(self.root, attempt['attemptId'], transport=transport)
        transport.assert_called_once()
        link.ATTEMPTS[link._key(self.root)]['nextPoll'] = 0
        with self.assertRaises(output_pairing.PairingError):
            link.status(self.root, attempt['attemptId'], transport=lambda _: response('approved', userCode='WXYZ-6789'))

    def test_malformed_response_never_echoes_remote_error(self):
        for result in ((503, b'private'), (429, b'private'), (200, b'private'), response(linkId=None), response(expiresAt='bad'), response(userCode=12), (200, b' '*16385)):
            with self.subTest(result=result[0]):
                with self.assertRaises(output_pairing.PairingError) as caught:
                    link.start(self.root, transport=lambda _, r=result: r)
                self.assertNotIn('private', str(caught.exception))

    def test_disabled_and_paused_never_contact_output(self):
        transport = Mock()
        for uploads in ('0', '1'):
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': uploads}):
                with self.assertRaises(output_pairing.PairingError):
                    link.start(self.root, transport=transport)
        with self.assertRaises(output_pairing.PairingError):
            link.start(self.root, paused=True, transport=transport)
        transport.assert_not_called()

class LinkHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_output_gate.GateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_remote_and_wrong_origin_cannot_start(self):
        with patch.object(link, 'start') as start:
            for ip, headers in [('192.168.1.25', {}), ('127.0.0.1', {'Origin':'https://evil.example'})]:
                handler = self.fixture.handler('/api/telemetry/output/link/start', ip=ip, headers=headers)
                handler.handle_post()
                self.assertEqual(handler.sent[0][0], 403)
            start.assert_not_called()

    def test_payload_validation_and_host_route(self):
        with patch.object(link, 'start', return_value={'state':'pending'}) as start:
            handler = self.fixture.handler('/api/telemetry/output/link/start')
            handler.handle_post()
            self.assertEqual(handler.sent[0][0], 200)
            start.assert_called_once()
        for action, data in [('start', {'host':'untrusted'}), ('status', {}), ('cancel', {'attemptId':42})]:
            handler = self.fixture.handler('/api/telemetry/output/link/' + action, body=json.dumps(data).encode())
            handler.handle_post()
            self.assertEqual(handler.sent[0][0], 400)

if __name__ == '__main__':
    unittest.main()

