"""Pairing stores a host credential and never returns it. No live OUTPUT call."""
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import app_info

import output_credential
import output_pairing
import server
import telemetry
import telemetry_sender as sender

TOKEN = 'osa_' + 'B' * 43
CODE = 'ABCD-1234'
ROOT = Path(__file__).resolve().parents[1]


class FlipCodec:
    def protect(self, data):
        return bytes(byte ^ 0x5A for byte in data)

    def unprotect(self, data):
        return bytes(byte ^ 0x5A for byte in data)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_private_file_round_trip_and_corrupt_file_is_not_connected(self):
        output_credential.save(self.root, TOKEN, 'North Shop')
        target = output_credential.path(self.root)
        self.assertEqual(target.stat().st_mode & 0o077, 0)
        self.assertEqual(output_credential.load(self.root), TOKEN)
        self.assertEqual(output_credential.describe(self.root)['shopName'], 'North Shop')
        target.write_bytes(b'not-a-credential')
        self.assertIsNone(output_credential.load(self.root))
        output_credential.clear(self.root)
        self.assertFalse(target.exists())

    def test_protecting_codec_hides_the_credential(self):
        output_credential.save(self.root, TOKEN, 'North Shop', codec=FlipCodec())
        blob = output_credential.path(self.root).read_bytes()
        self.assertNotIn(TOKEN.encode(), blob)
        self.assertNotIn(b'North Shop', blob)
        self.assertEqual(output_credential.load(self.root, codec=FlipCodec()), TOKEN)

    def test_shop_name_and_token_are_rejected_before_a_file_exists(self):
        for name in ('', 'bad\nname', 'x' * 81):
            with self.assertRaises(ValueError):
                output_credential.save(self.root, TOKEN, name)
        with self.assertRaises(ValueError):
            output_credential.save(self.root, 'osa_short', 'North Shop')
        self.assertFalse(output_credential.path(self.root).exists())


class ExchangeTests(unittest.TestCase):
    def test_success_shape_and_secret_free_errors(self):
        secret_body = json.dumps({'code': 'expired', 'detail': CODE, 'credential': TOKEN}).encode()
        with self.assertRaises(output_pairing.PairingError) as caught:
            output_pairing.interpret(410, secret_body)
        self.assertEqual(caught.exception.reason, 'rejected')
        self.assertNotIn(CODE, str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        disabled = output_pairing.classify(404, {'code': 'api_route_not_found', 'detail': CODE})
        self.assertEqual(disabled, 'disabled')
        self.assertEqual(output_pairing.classify(404, None), 'disabled')
        self.assertEqual(output_pairing.classify(503, {'code': 'temporarily_unavailable'}), 'unavailable')
        result = output_pairing.interpret(200, json.dumps({'result': {'credential': TOKEN, 'shop_name': 'North Shop'}, 'extra': CODE}).encode())
        self.assertEqual(result, {'credential': TOKEN, 'shopName': 'North Shop'})
        with self.assertRaises(output_pairing.PairingError) as bad:
            output_pairing.interpret(200, json.dumps({'credential': 'not-a-token', 'shopName': 'North Shop'}).encode())
        self.assertNotIn('not-a-token', str(bad.exception))

    def test_transport_posts_the_assumed_contract_and_does_not_follow_redirects(self):
        seen = {}

        def transport(raw):
            seen['body'] = json.loads(raw)
            return 200, json.dumps({'credential': TOKEN, 'shopName': 'North Shop'}).encode()

        result = output_pairing.exchange(CODE, 'SHOP PC', '1.0.0-rc.5', transport=transport)
        self.assertEqual(seen['body'], {'code': CODE, 'hostName': 'SHOP PC', 'version': '1.0.0-rc.5'})
        self.assertEqual(result['shopName'], 'North Shop')
        with patch.object(output_pairing, 'build_opener') as opener:
            opener.return_value.open.side_effect = URLError('timed out')
            with self.assertRaises(output_pairing.PairingError) as offline:
                output_pairing.exchange(CODE, 'HOST', '1.0.0-rc.5')
            self.assertEqual(offline.exception.reason, 'offline')
            self.assertNotIn('timed out', str(offline.exception))
            self.assertIsInstance(opener.call_args.args[0], output_pairing.NoRedirect)
        with patch.object(output_pairing, 'build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError(output_pairing.ENDPOINT, 302, 'Found', hdrs={}, fp=io.BytesIO(b'{"credential":"' + TOKEN.encode() + b'"}'))
            with self.assertRaises(output_pairing.PairingError) as redirected:
                output_pairing.exchange(CODE, 'HOST', '1.0.0-rc.5')
            self.assertNotIn(TOKEN, str(redirected.exception))
            self.assertIsInstance(opener.call_args.args[0], sender.NoRedirect)


class ConnectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = json.loads((ROOT / 'sample.json').read_text())
        self.env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def transport(self, raw):
        self.sent = json.loads(raw)
        return 200, json.dumps({'credential': TOKEN, 'shopName': 'North Shop'}).encode()

    def test_connect_stores_credential_and_consent_sends_it_without_env(self):
        info = output_pairing.connect(self.root, '  ' + CODE + '  ', transport=self.transport, host='HOST', version='1.0.0-rc.5')
        self.assertEqual(self.sent['code'], CODE)
        self.assertEqual(info['connection'], 'paired')
        self.assertEqual(info['shopName'], 'North Shop')
        self.assertTrue(info['requiresConsent'])
        self.assertNotIn(TOKEN, json.dumps(info))
        self.assertNotIn(CODE, json.dumps(info))
        self.assertNotIn(TOKEN.encode(), (self.root / 'telemetry.sqlite3').read_bytes())
        agreed = sender.consent(self.root, revision=info['revision'], version=info['consentVersion'], configurationId=info['configurationId'], confirmed=True)
        self.assertTrue(agreed['enabled'])
        telemetry.observe(self.root, 'c' * 32, self.job, {'width': 180, 'usedLength': 100, 'area': 10000, 'placements': [{}], 'elapsed': 5})
        with patch.object(sender, 'emit', return_value=True) as emit:
            self.assertGreater(sender.tick(self.root), 0)
            self.assertTrue(emit.call_args_list)
            self.assertTrue(all(call.args[1] == TOKEN for call in emit.call_args_list))
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '1', 'EZ_NEST_OUTPUT_TOKEN': 'osa_' + 'C' * 43}):
            self.assertEqual(sender.connection(self.root)['source'], 'environment')
            self.assertIsNone(sender.connection(self.root)['shopName'])
            self.assertFalse(sender.status(self.root)['enabled'])
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '0'}):
            self.assertEqual(sender.connection(self.root)['source'], 'disabled')
            self.assertIsNone(sender.configuration(self.root))

    def test_environment_and_shop_test_do_not_spend_a_code(self):
        def explode(_raw):
            raise AssertionError('pairing code was sent')
        for uploads in ('0', '1'):
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': uploads, 'EZ_NEST_OUTPUT_TOKEN': 'osa_' + 'C' * 43}):
                with self.assertRaises(output_pairing.PairingError):
                    output_pairing.connect(self.root, CODE, transport=explode)
        self.assertFalse(output_credential.path(self.root).exists())

    def test_disconnect_removes_the_file_and_stops_sharing(self):
        output_pairing.connect(self.root, CODE, transport=self.transport, host='HOST', version='1.0.0-rc.5')
        info = sender.status(self.root)
        sender.consent(self.root, revision=info['revision'], version=info['consentVersion'], configurationId=info['configurationId'], confirmed=True)
        disconnected = output_pairing.disconnect(self.root)
        self.assertFalse(disconnected['configured'])
        self.assertFalse(output_credential.path(self.root).exists())
        with self.assertRaises(output_pairing.PairingError):
            output_pairing.disconnect(self.root)
        output_credential.save(self.root, TOKEN, 'North Shop')
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '1', 'EZ_NEST_OUTPUT_TOKEN': 'osa_' + 'C' * 43}):
            with self.assertRaises(output_pairing.PairingError):
                output_pairing.disconnect(self.root)
        self.assertTrue(output_credential.path(self.root).exists())


class PairApiTests(unittest.TestCase):
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
        self.env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def stop(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join()
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

    def test_host_pair_and_disconnect_hide_the_credential(self):
        seen = {}

        def exchange(code, host, version, *, transport=None):
            seen.update(code=code, host=host, version=version)
            return {'credential': TOKEN, 'shopName': 'North Shop'}

        with patch.object(output_pairing, 'exchange', side_effect=exchange):
            status, body = self.request('/api/telemetry/output/pair', {'code': CODE})
        self.assertEqual(seen['code'], CODE)
        self.assertEqual(seen['version'], app_info.VERSION)
        self.assertTrue(seen['host'])
        self.assertEqual(status, 200)
        self.assertEqual(body['shopName'], 'North Shop')
        self.assertEqual(body['connection'], 'paired')
        self.assertTrue(body['requiresConsent'])
        self.assertNotIn(TOKEN, json.dumps(body))
        self.assertNotIn('credential', body)
        status, denied = self.request('/api/telemetry/output/pair', {'code': CODE}, token=False)
        self.assertEqual(status, 403)
        self.assertNotIn(TOKEN, json.dumps(denied))
        status, body = self.request('/api/telemetry/output/disconnect', {})
        self.assertEqual(status, 200)
        self.assertFalse(body['configured'])
        self.assertNotIn(TOKEN, json.dumps(body))

    def test_lan_client_cannot_pair(self):
        handler = object.__new__(server.Handler)
        handler.client_address = ('192.168.1.50', 1234)
        handler.headers = {'X-EZ-Token': server.TOKEN, 'Content-Length': '2'}
        handler.allowed = lambda: True
        handler.send = Mock()
        handler.path = '/api/telemetry/output/pair'
        handler.rfile = io.BytesIO(b'{}')
        with patch.object(output_pairing, 'exchange', side_effect=AssertionError('lan client paired')):
            handler.handle_post()
        self.assertEqual(handler.send.call_args.args[0], 403)


class DialogCopyTests(unittest.TestCase):
    def test_popup_copy_links_and_colors(self):
        html = (ROOT / 'web.html').read_text(encoding='utf-8')
        css = (ROOT / 'web.css').read_text(encoding='utf-8')
        script = (ROOT / 'web.js').read_text(encoding='utf-8')
        dialog = html.split('id="max-output-dialog"', 1)[1].split('</dialog>', 1)[0]
        self.assertIn("Don't print it. Let another shop do it.", dialog)
        self.assertIn('OUTPUT routes the job to the best-fit nearby shop. You still get paid.', dialog)
        self.assertIn('The queue is backed up and this job would miss its date', dialog)
        self.assertIn('The material is not in stock', dialog)
        self.assertIn('The job is outside what your machines can run', dialog)
        self.assertIn('href="https://output.jeezlabs.io/waitlist"', dialog)
        self.assertIn('href="https://output.jeezlabs.io/"', dialog)
        self.assertEqual(dialog.count('class="primary-link"'), 2)
        self.assertNotIn('class="output-learn"', dialog)
        self.assertIn('id="max-output-learn"', dialog)
        for banned in ('$', 'fee', '%', 'How it works', 'What is OUTPUT?', 'customer is too far'):
            self.assertNotIn(banned, dialog)
        self.assertIn('#max-output { position: relative; background: #f3fbf6;', css)
        self.assertIn('.paid-badge { position: absolute; right: -6px; bottom: -11px; z-index: 1; padding: 3px 8px; border-radius: 999px; background: #15803D;', css)
        self.assertIn('#output-connect-status.error { color: #D92F00; }', css)
        self.assertIn("const OUTPUT_WAITLIST_URL = new URL('waitlist', OUTPUT_WEBSITE_URL).href;", script)
        self.assertIn('https://output.jeezlabs.io/', script)
        self.assertIn('id="output-pair"', html)
        self.assertIn('id="output-disconnect"', html)


class OutputScreenTests(unittest.TestCase):
    """Browser check for the popup and the host connect control."""

    def test_popup_and_connect_failure_are_visible(self):
        import test_web_mvp
        from playwright.sync_api import expect, sync_playwright
        helper = test_web_mvp.WebMvpTests(methodName='runTest')
        helper.setUp()
        shots = Path('/opt/cursor/artifacts/screenshots')
        shots.mkdir(parents=True, exist_ok=True)
        try:
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''}), sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    page.goto(helper.url() + '/web')
                    helper.wait_ready(page)
                    expect(page.locator('#max-output')).to_be_visible()
                    self.assertEqual(page.locator('#max-output').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(243, 251, 246)')
                    self.assertEqual(page.locator('#max-output .paid-badge').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(21, 128, 61)')
                    page.click('#max-output')
                    expect(page.locator('#max-output-title')).to_have_text("Don't print it. Let another shop do it.")
                    expect(page.locator('#max-output-waitlist')).to_have_attribute('href', 'https://output.jeezlabs.io/waitlist')
                    expect(page.locator('#max-output-learn')).to_have_attribute('href', 'https://output.jeezlabs.io/')
                    self.assertEqual(page.locator('#max-output-learn').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(17, 17, 17)')
                    self.assertEqual(page.locator('.output-points li').count(), 3)
                    page.screenshot(path=str(shots / 'output-popup-desktop.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    box = page.locator('#max-output-dialog').bounding_box()
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertLessEqual(box['x'] + box['width'], 390)
                    page.screenshot(path=str(shots / 'output-popup-mobile.png'))
                    page.keyboard.press('Escape')
                    page.set_viewport_size({'width': 1280, 'height': 900})
                    page.click('#settings-open')
                    page.locator('#settings-telemetry').evaluate('node => node.open = true')
                    page.wait_for_function("() => !document.querySelector('#output-pair').disabled")
                    expect(page.locator('#output-pair-form')).to_be_visible()
                    page.fill('#output-pair-code', 'NOPE-0000')

                    def disabled(code, host, version, *, transport=None):
                        self.assertEqual(code, 'NOPE-0000')
                        raise output_pairing.PairingError('disabled', output_pairing.DISABLED)

                    with patch.object(output_pairing, 'exchange', side_effect=disabled):
                        page.click('#output-pair')
                        page.wait_for_function("() => document.querySelector('#output-connect-status').classList.contains('error')")
                    message = page.locator('#output-connect-status').inner_text()
                    self.assertEqual(message, output_pairing.DISABLED)
                    self.assertEqual(page.input_value('#output-pair-code'), 'NOPE-0000')
                    self.assertNotIn('osa_', page.locator('#settings-telemetry').inner_text())
                    self.assertEqual(page.locator('#output-connect-status').evaluate('n => getComputedStyle(n).color'), 'rgb(217, 47, 0)')
                    page.screenshot(path=str(shots / 'output-connect-error-desktop.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.locator('#output-connect').scroll_into_view_if_needed()
                    page.screenshot(path=str(shots / 'output-connect-error-mobile.png'))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                finally:
                    browser.close()
        finally:
            helper.tearDown()


if __name__ == '__main__':
    unittest.main()
