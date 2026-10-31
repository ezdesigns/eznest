"""Set up your shop: browser approval. No live OUTPUT call."""
import opt_out
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import output_credential
import output_link
import output_pairing
import server

TOKEN = 'osa_' + 'C' * 43
LINK = '2f6c1a40-7b1e-4d2a-9c31-0a6e5b7c8d90'
ROOT = Path(__file__).resolve().parents[1]


def reply(result, status=200):
    return status, json.dumps({'outcome': 'ok', 'result': result}).encode()


class LinkFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(output_link.cancel, self.root)
        self.sent = []

    def start(self):
        def transport(payload):
            self.sent.append(payload)
            return reply({'linkId': LINK, 'state': 'pending', 'userCode': 'ABCD-2345'})
        return output_link.start(self.root, transport=transport, host='Front PC')

    def test_start_sends_only_a_hash_and_returns_no_secret(self):
        body = self.start()
        sent = self.sent[0]
        self.assertEqual(set(sent), {'op', 'requestId', 'codeHash', 'hostLabel'})
        self.assertRegex(sent['codeHash'], r'^[0-9a-f]{64}$')
        code = output_link._PENDING[str(self.root)]['code']
        self.assertEqual(hashlib.sha256(code.encode()).hexdigest(), sent['codeHash'])
        self.assertNotIn(code, json.dumps(sent))
        self.assertEqual(body['userCode'], 'ABCD-2345')
        self.assertTrue(body['approveUrl'].endswith('/outpost/ez-nest/approve?link=' + LINK))
        self.assertTrue(body['approveUrl'].startswith('https://output.jeezlabs.io/'))
        self.assertNotIn(code, json.dumps(body))
        self.assertNotIn(sent['codeHash'], json.dumps(body))

    def test_pending_then_approved_redeems_own_code_and_stores_key(self):
        self.start()
        code = output_link._PENDING[str(self.root)]['code']
        pending = output_link.check(self.root, transport=lambda p: reply({'state': 'pending'}))
        self.assertEqual(pending['state'], 'pending')
        redeemed = {}

        def pair(raw):
            redeemed.update(json.loads(raw))
            return 200, json.dumps({'outcome': 'created', 'result': {'token': TOKEN}}).encode()

        done = output_link.check(self.root, transport=lambda p: reply({'state': 'approved'}), pair_transport=pair)
        self.assertEqual(done['state'], 'connected')
        self.assertEqual(redeemed['code'].replace('-', ''), code)
        self.assertTrue(output_credential.path(self.root).is_file())
        self.assertNotIn(TOKEN, json.dumps(done))
        self.assertEqual(output_link._PENDING, {})

    def test_expired_denied_and_not_started(self):
        with self.assertRaises(output_link.LinkError):
            output_link.check(self.root, transport=lambda p: reply({'state': 'pending'}))
        self.start()
        self.assertEqual(output_link.check(self.root, transport=lambda p: reply({'state': 'denied'}))['state'], 'denied')
        self.start()
        self.assertEqual(output_link.check(self.root, transport=lambda p: (404, b'{}'))['state'], 'expired')
        self.start()
        far = output_link._PENDING[str(self.root)]['expires'] + 1
        self.assertEqual(output_link.check(self.root, transport=None, now=lambda: far)['state'], 'expired')

    def test_disabled_and_bad_replies_fail_closed(self):
        with self.assertRaises(output_link.LinkError) as off:
            output_link.start(self.root, transport=lambda p: (503, b'{}'))
        self.assertEqual(off.exception.reason, 'disabled')
        with self.assertRaises(output_link.LinkError):
            output_link.start(self.root, transport=lambda p: reply({'linkId': 'x', 'userCode': 'ABCD-2345'}))
        with self.assertRaises(output_link.LinkError):
            output_link.start(self.root, transport=lambda p: reply({'linkId': LINK, 'userCode': '<script>'}))
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '0'}):
            with self.assertRaises(output_link.LinkError):
                output_link.start(self.root, transport=lambda p: reply({}))

    def test_link_stays_on_the_allowlisted_origin(self):
        (self.root / 'shop.json').write_text(json.dumps({'outputUrl': 'https://evil.example'}), encoding='utf-8')
        self.assertTrue(output_link.link_endpoint(self.root).startswith('https://output.jeezlabs.io/'))


class LinkApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.old = (server.WORK, server.PORT)
        server.WORK = Path(self.folder.name)
        self.service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = self.service.server_port
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join()
        output_link.cancel(server.WORK)
        server.WORK, server.PORT = self.old

    def request(self, path, data, token=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-EZ-Token'] = server.TOKEN
        req = Request(f'http://127.0.0.1:{server.PORT}' + path, data=json.dumps(data).encode(), headers=headers)
        try:
            with urlopen(req) as response:
                return response.status, json.load(response)
        except Exception as error:
            if not hasattr(error, 'read'):
                raise
            return error.code, json.loads(error.read().decode())

    def test_setup_routes_need_a_session_and_are_not_gate_exemptions(self):
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn('reject_output_gate', source)
        self.assertNotIn("'/api/telemetry/output/link/start', '/api/telemetry/output/link/check'", source)
        with patch.object(output_link, '_post', return_value=reply({'linkId': LINK, 'state': 'pending', 'userCode': 'ABCD-2345'})):
            status, body = self.request('/api/telemetry/output/link/start', {})
            self.assertEqual(status, 200, body)
            self.assertEqual(body['userCode'], 'ABCD-2345')
            self.assertNotIn('code', body)
            status, body = self.request('/api/telemetry/output/link/check', {})
            self.assertEqual((status, body['state']), (200, 'pending'))
            status, _ = self.request('/api/telemetry/output/link/start', {}, token=False)
            self.assertEqual(status, 403)
            status, _ = self.request('/api/telemetry/output/link/start', {'code': 'X'})
            self.assertEqual(status, 400)
        status, body = self.request('/api/telemetry/output/link/cancel', {})
        self.assertEqual((status, body['state']), (200, 'cancelled'))


class ApproveEndpointGateTests(unittest.TestCase):
    """EZ46-7: browser approval stays closed until OUTPUT's endpoint is live."""

    def test_flag_defaults_off_and_blocks_link_start(self):
        js = (ROOT / 'web.js').read_text(encoding='utf-8')
        self.assertIn('const OUTPUT_APPROVE_ENDPOINT_READY = false;', js)
        handler = js.split('button.onclick = async () => {', 1)[1].split('const cancel', 1)[0]
        guard = handler.index('if (!OUTPUT_APPROVE_ENDPOINT_READY) return;')
        call = handler.index("OUTPUT_APPROVE_ENDPOINT_READY ? '/api/telemetry/output/link/start'")
        self.assertLess(guard, call)
        self.assertNotIn("api('/api/telemetry/output/link/start'", js)

    def test_skip_is_stored_outside_session_storage(self):
        js = (ROOT / 'web.js').read_text(encoding='utf-8')
        self.assertIn("localStorage.getItem('eznest-setup-skipped')", js)
        self.assertIn("localStorage.setItem('eznest-setup-skipped', '1')", js)
        self.assertNotIn("sessionStorage.getItem('eznest-setup-skipped')", js)
        self.assertNotIn("sessionStorage.setItem('eznest-setup-skipped'", js)


class SetupCardCopyTests(unittest.TestCase):
    def test_card_wording_is_plain(self):
        html = (ROOT / 'web.html').read_text(encoding='utf-8')
        self.assertIn('>Set up your shop</strong>', html)
        self.assertIn('Connects to OUTPUT', html)
        self.assertIn('id="output-required-skip"', html)
        self.assertIn('Have a pairing code?', html)
        self.assertIn('id="output-setup-settings"', html)
        self.assertRegex(html, r'<button id="output-required-connect"[^>]*\bhidden\b[^>]*>Set up your shop</button>')
        self.assertRegex(html, r'<button id="output-setup-settings"[^>]*\bhidden\b[^>]*>Set up your shop</button>')
        self.assertLess(html.index('output-required-connect'), html.index('output-required-code'))
        script = (ROOT / 'web.js').read_text(encoding='utf-8')
        self.assertIn("'/api/telemetry/output/link/start'", script)
        self.assertIn('popup.opener = null', script)
        self.assertIn("parsed.protocol !== 'https:'", script)
        self.assertIn('parsed.host !== allowed.host', script)
        self.assertIn('const OUTPUT_APPROVE_ENDPOINT_READY = false;', script)
        self.assertIn("localStorage.getItem('eznest-setup-skipped')", script)
        self.assertNotIn("sessionStorage.getItem('eznest-setup-skipped')", script)


if __name__ == '__main__':
    unittest.main()
