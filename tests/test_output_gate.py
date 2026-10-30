"""OUTPUT connection status and browser gating do not block the shop API."""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import opt_out  # noqa: F401
import output_credential
import output_gate
import output_pairing
import server
import shop_deploy
from app_info import VERSION

TOKEN = 'osa_' + 'C' * 43
ENV_KEYS = (
    'EZ_NEST_OUTPUT_GATE_OPEN', 'EZ_NEST_DEV', 'EZ_NEST_DEV_NO_OUTPUT',
    'EZ_NEST_OUTPUT_UPLOADS', 'EZ_NEST_OUTPUT_TOKEN', 'EZ_NEST_OUTPUT_URL',
)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.old = (server.WORK, server.HOST, server.PORT, server.LAN)
        self.old_env = {key: os.environ.get(key) for key in ENV_KEYS}
        self.tmp = tempfile.TemporaryDirectory()
        server.WORK = Path(self.tmp.name)
        server.HOST = '127.0.0.1'
        server.PORT = 8765
        server.LAN = False
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        shop_deploy.clear_name_cache()

    def tearDown(self):
        server.WORK, server.HOST, server.PORT, server.LAN = self.old
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shop_deploy.clear_name_cache()
        self.tmp.cleanup()

    def handler(self, path, body=b'{}', ip='127.0.0.1', host=None, headers=None):
        item = server.Handler.__new__(server.Handler)
        item.path = path
        item.client_address = (ip, 41000)
        item.rfile = io.BytesIO(body)
        host = host or ('127.0.0.1:8765' if ip in ('127.0.0.1', '::1') else '192.168.1.50:8765')
        base = {
            'Host': host,
            'Content-Length': str(len(body)),
            'Content-Type': 'application/json',
            'Origin': 'http://' + host,
            'X-EZ-Token': server.TOKEN,
        }
        if headers:
            base.update(headers)
        item.headers = base
        item.sent = []

        def send(status, data, mime='application/json', filename=None, extra_headers=None):
            item.sent.append((status, data, extra_headers))

        item.send = send
        return item

    def pair(self, age_seconds=0):
        output_credential.save(server.WORK, TOKEN)
        stamp = int(time.time()) - age_seconds
        output_gate.note_paired(server.WORK, now=stamp)

    def assert_api_open(self, sent, message, expected_status=200):
        status, body, _headers = sent
        self.assertEqual(status, expected_status)
        self.assertNotEqual(body.get('code'), 'connect_required')
        self.assertNotIn(TOKEN, json.dumps(body))
        session = self.handler('/api/session')
        session.do_GET()
        self.assertEqual(session.sent[0][0], 200)
        connection = session.sent[0][1]['outputConnection']
        self.assertFalse(connection['ok'])
        self.assertEqual(connection['code'], 'connect_required')
        self.assertEqual(connection['message'], message)
        self.assertNotIn(TOKEN, json.dumps(session.sent[0][1]))

    def test_constants_are_named_days(self):
        self.assertEqual(output_gate.CHECK_IN_MAX_AGE_DAYS, 14)
        self.assertEqual(output_gate.CHECK_IN_MAX_AGE, 14 * 24 * 60 * 60)
        self.assertEqual(output_gate.OFFLINE_BANNER_AFTER_DAYS, 3)

    def test_unpaired_host_allows_stock_and_validates_nesting_and_pairing(self):
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_UNPAIRED)
        solve = self.handler('/api/solve', body=b'{}')
        solve.handle_post()
        self.assert_api_open(solve.sent[0], output_gate.HOST_UNPAIRED, expected_status=400)
        health = self.handler('/api/health')
        health.do_GET()
        self.assertEqual(health.sent[0][0], 200)
        self.assertEqual(health.sent[0][1]['ok'], True)
        style = self.handler('/web.css', body=b'')
        style.do_GET()
        self.assertEqual(style.sent[0][0], 200)
        pair = self.handler('/api/telemetry/output/pair', body=b'{"code":"not-a-code"}')
        pair.handle_post()
        self.assertEqual(pair.sent[0][0], 400)
        self.assertNotEqual(pair.sent[0][1].get('code'), 'connect_required')
        self.assertNotIn('not-a-code', json.dumps(pair.sent[0][1]))

    def test_unpaired_lan_client_still_needs_pin_and_sees_connection_message(self):
        server.HOST = '0.0.0.0'
        server.LAN = True
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            stock = self.handler('/api/materials', ip='192.168.1.50')
            stock.do_GET()
            self.assertEqual(stock.sent[0][0], 403)
            self.assertEqual(stock.sent[0][1]['error'], 'Enter the shop PIN on this computer.')
            self.assertNotEqual(stock.sent[0][1].get('code'), 'connect_required')
            with patch.object(server.Handler, 'authenticated', return_value=True):
                authenticated = self.handler('/api/materials', ip='192.168.1.50')
                authenticated.do_GET()
            self.assertEqual(authenticated.sent[0][0], 200)
            session = self.handler('/api/session', ip='192.168.1.50')
            session.do_GET()
            self.assertEqual(session.sent[0][0], 200)
            self.assertEqual(session.sent[0][1]['outputConnection']['message'], output_gate.LAN_MESSAGE)
            self.assertNotIn('token', session.sent[0][1])

    def test_paired_host_can_read_stock(self):
        self.pair()
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assertEqual(stock.sent[0][0], 200)
        self.assertNotIn('code', stock.sent[0][1])
        session = self.handler('/api/session')
        session.do_GET()
        self.assertTrue(session.sent[0][1]['outputConnection']['ok'])
        self.assertIsNone(session.sent[0][1]['outputConnection']['banner'])

    def test_paired_host_can_read_stock_when_service_account_is_unmapped(self):
        calls = []

        class Result:
            def __init__(self, code, stdout=b'', stderr=b''):
                self.returncode = code
                self.stdout = stdout
                self.stderr = stderr

        def run(args, **kwargs):
            calls.append(list(args))
            self.assertIsNot(kwargs.get('shell'), True)
            if args[2] == '/inheritance:r':
                return Result(0)
            if 'eznest-svc:(M)' in args:
                return Result(1332, stderr=b'No mapping between account names and security IDs was done.')
            return Result(0)

        with patch.object(output_credential, '_use_windows_acl', return_value=True), \
             patch.object(output_credential, '_account_exists', return_value=None), \
             patch.object(output_credential.subprocess, 'run', side_effect=run), \
             patch.dict(os.environ, {'USERNAME': 'shop-user'}):
            self.pair()
            stock = self.handler('/api/materials')
            stock.do_GET()
        self.assertEqual(stock.sent[0][0], 200)
        self.assertNotIn('code', stock.sent[0][1])
        self.assertTrue(output_credential.path(server.WORK).is_file())
        self.assertEqual(output_credential.load(server.WORK), TOKEN)
        self.assertTrue(any(call[2] == '/inheritance:r' for call in calls))
        self.assertTrue(any('eznest-svc:(M)' in call for call in calls))
        applied = [call for call in calls if call[2] == '/grant:r' and 'eznest-svc:(M)' not in call]
        self.assertTrue(applied)
        for call in applied:
            self.assertIn('*S-1-5-18:(M)', call)
            self.assertIn('*S-1-5-32-544:(M)', call)
            self.assertIn('shop-user:(M)', call)
            self.assertNotIn('Everyone', call)
            self.assertNotIn('BUILTIN\\Users', call)

    def test_offline_within_grace_still_works_and_shows_a_banner_after_three_days(self):
        self.pair(output_gate.OFFLINE_BANNER_AFTER + 24 * 60 * 60)
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assertEqual(stock.sent[0][0], 200)
        session = self.handler('/api/session')
        session.do_GET()
        banner = session.sent[0][1]['outputConnection']['banner']
        self.assertIn('unreachable', banner)
        self.assertIn('14 days', banner)
        fresh = self.handler('/api/session')
        self.pair(60)
        fresh.do_GET()
        self.assertIsNone(fresh.sent[0][1]['outputConnection']['banner'])

    def test_past_fourteen_days_reports_reconnect_but_allows_stock(self):
        self.pair(output_gate.CHECK_IN_MAX_AGE + 30)
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_RECONNECT)
        self.assertTrue(output_credential.path(server.WORK).is_file())

    def test_revoked_credential_allows_stock_and_check_in_sends_only_the_app_version(self):
        self.pair()
        seen = {}

        def transport(raw, token):
            seen['body'] = json.loads(raw)
            seen['token'] = token
            return 401, b'{"error":{"code":"revoked","message":"secret-detail"}}'

        status = output_gate.check_in(server.WORK, transport=transport)
        self.assertEqual(seen['body'], {'appVersion': VERSION})
        self.assertEqual(set(seen['body']), {'appVersion'})
        self.assertNotIn('hostLabel', seen['body'])
        self.assertNotIn('hostRef', seen['body'])
        self.assertEqual(seen['token'], TOKEN)
        self.assertFalse(status['ok'])
        self.assertEqual(status['code'], 'connect_required')
        self.assertNotIn('secret-detail', json.dumps(status))
        self.assertFalse(output_credential.path(server.WORK).is_file())
        self.assertNotIn(TOKEN, _state_text())
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_REVOKED)

    def test_a_successful_check_in_restores_status_while_stock_stays_accessible(self):
        self.pair(output_gate.CHECK_IN_MAX_AGE + 30)
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_RECONNECT)

        def transport(raw, _token):
            self.assertEqual(json.loads(raw), {'appVersion': VERSION})
            return 200, b'{"outcome":"ok"}'

        status = output_gate.check_in(server.WORK, transport=transport)
        self.assertTrue(status['ok'])
        opened = self.handler('/api/materials')
        opened.do_GET()
        self.assertEqual(opened.sent[0][0], 200)

    def test_missing_check_in_route_is_offline_not_revoked(self):
        self.pair(60)

        def transport(_raw, _token):
            return 404, b'{"code":"api_route_not_found"}'

        status = output_gate.check_in(server.WORK, transport=transport)
        self.assertTrue(status['ok'])
        self.assertEqual(output_credential.load(server.WORK), TOKEN)

    def test_offline_check_in_keeps_the_credential(self):
        self.pair(60)

        def transport(_raw, _token):
            raise output_gate.Offline()

        status = output_gate.check_in(server.WORK, transport=transport)
        self.assertTrue(status['ok'])
        self.assertEqual(output_credential.load(server.WORK), TOKEN)

    def test_dev_escape_is_ignored_without_dev_mode_and_on_a_frozen_build(self):
        os.environ['EZ_NEST_DEV_NO_OUTPUT'] = '1'
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_UNPAIRED)
        os.environ['EZ_NEST_DEV'] = '1'
        with patch.object(sys_module(), 'frozen', True, create=True):
            self.assertFalse(output_gate.dev_escape())
            frozen = self.handler('/api/materials')
            frozen.do_GET()
            self.assert_api_open(frozen.sent[0], output_gate.HOST_UNPAIRED)

    def test_dev_escape_opens_the_gate_and_sets_the_banner(self):
        os.environ['EZ_NEST_DEV'] = '1'
        os.environ['EZ_NEST_DEV_NO_OUTPUT'] = '1'
        self.assertTrue(output_gate.source_checkout())
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assertEqual(stock.sent[0][0], 200)
        session = self.handler('/api/session')
        session.do_GET()
        connection = session.sent[0][1]['outputConnection']
        self.assertTrue(connection['ok'])
        self.assertTrue(connection['devMode'])
        self.assertEqual(connection['banner'], 'DEV MODE: not connected to OUTPUT')

    def test_disconnect_updates_status_but_allows_stock(self):
        self.pair()
        output_pairing.disconnect(server.WORK)
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_DISCONNECTED)
        self.assertFalse(output_credential.path(server.WORK).is_file())

    def test_host_page_shows_only_the_connect_screen_until_paired(self):
        try:
            from playwright.sync_api import expect, sync_playwright
            import test_web_mvp
        except ImportError:
            self.skipTest('playwright is not installed')
        helper = test_web_mvp.WebMvpTests(methodName='runTest')
        helper.setUp()
        try:
            with sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 800})
                    page.goto(helper.url() + '/web')
                    expect(page.locator('#output-gate')).to_be_visible()
                    expect(page.locator('#output-gate-title')).to_have_text('Connect to OUTPUT')
                    expect(page.locator('#output-gate-note')).to_contain_text('Connect this computer to OUTPUT')
                    expect(page.locator('#output-gate a')).to_have_attribute('href', 'https://output.jeezlabs.io/outpost/ez-nest')
                    self.assertTrue(page.locator('#output-gate').evaluate("n => n.matches(':modal')"))
                    self.assertEqual(page.locator('#output-gate-code').input_value(), '')
                    shots = Path(__file__).resolve().parents[1] / '.local' / 'test-screenshots'
                    shots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / 'output-connect-gate.png'))
                finally:
                    browser.close()
        finally:
            helper.tearDown()

    def test_opt_out_requires_dev_mode_on_a_source_checkout(self):
        os.environ['EZ_NEST_OUTPUT_GATE_OPEN'] = '1'
        with patch('sys.argv', ['python', '-m', 'unittest', 'discover']):
            self.assertFalse(output_gate.gate_opt_out())
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_UNPAIRED)
        os.environ['EZ_NEST_DEV'] = '1'
        self.assertTrue(output_gate.source_checkout())
        self.assertTrue(output_gate.gate_opt_out())
        opened = self.handler('/api/materials')
        opened.do_GET()
        self.assertEqual(opened.sent[0][0], 200)
        with patch.object(sys_module(), 'frozen', True, create=True):
            self.assertFalse(output_gate.source_checkout())
            self.assertFalse(output_gate.gate_opt_out())
            frozen = self.handler('/api/materials')
            frozen.do_GET()
            self.assert_api_open(frozen.sent[0], output_gate.HOST_UNPAIRED)

    def test_release_marker_ignores_the_dev_opt_out(self):
        marker = Path(output_gate.__file__).resolve().parent / output_gate.RELEASE_MARKER
        self.assertFalse(marker.exists())
        marker.write_text('release\n', encoding='utf-8')
        try:
            os.environ['EZ_NEST_DEV'] = '1'
            os.environ['EZ_NEST_DEV_NO_OUTPUT'] = '1'
            os.environ['EZ_NEST_OUTPUT_GATE_OPEN'] = '1'
            self.assertFalse(output_gate.source_checkout())
            self.assertFalse(output_gate.dev_escape())
            self.assertFalse(output_gate.gate_opt_out())
            text = (marker.parent / 'Dockerfile').read_text(encoding='utf-8')
            self.assertIn(output_gate.RELEASE_MARKER, text)
            self.assertIn('eznest_build.py', text)
            self.assertIn('INSTALLED = True', text)
            import launcher
            with patch('sys.argv', ['eznest', '--dev', '--no-browser']):
                with self.assertRaisesRegex(ValueError, 'source checkout'):
                    launcher.main()
        finally:
            marker.unlink(missing_ok=True)

    def test_missing_or_unreadable_check_in_stays_closed(self):
        output_credential.save(server.WORK, TOKEN)
        status = output_gate.public_status(server.WORK, True)
        self.assertFalse(status['ok'])
        self.assertEqual(status['message'], output_gate.HOST_CHECKIN)
        self.assertFalse(output_gate._state_path(server.WORK).is_file())
        output_gate._state_path(server.WORK).write_text('not-json\n', encoding='utf-8')
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.pair()
        self.assertTrue(output_gate.public_status(server.WORK, True)['ok'])
        state_path = output_gate._state_path(server.WORK)
        payload = json.loads(state_path.read_text(encoding='utf-8'))
        payload['lastOkAt'] = int(payload['lastOkAt']) - 50
        state_path.write_text(json.dumps(payload), encoding='utf-8')
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertNotIn(TOKEN, state_path.read_text(encoding='utf-8'))

    def _write_legacy(self, last_ok):
        output_credential.save(server.WORK, TOKEN)
        payload = {'v': 1, 'lastOkAt': last_ok, 'lastAttemptAt': last_ok, 'reason': ''}
        output_gate._state_path(server.WORK).write_text(json.dumps(payload) + '\n', encoding='utf-8')

    def test_unsigned_current_record_is_signed_on_first_load(self):
        last_ok = int(time.time()) - (4 * output_gate.DAY_SECONDS)
        self._write_legacy(last_ok)
        status = output_gate.public_status(server.WORK, True)
        self.assertTrue(status['ok'])
        self.assertIn('unreachable', status['banner'])
        raw = json.loads(output_gate._state_path(server.WORK).read_text(encoding='utf-8'))
        self.assertTrue(output_gate._mac_ok(TOKEN, raw))
        self.assertEqual(raw['lastOkAt'], last_ok)
        again = output_gate.public_status(server.WORK, True)
        self.assertTrue(again['ok'])
        self.assertEqual(again['banner'], status['banner'])

    def test_unsigned_old_future_or_missing_record_stays_closed(self):
        self._write_legacy(int(time.time()) - output_gate.CHECK_IN_MAX_AGE - 30)
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertNotIn('mac', output_gate._state_path(server.WORK).read_text(encoding='utf-8'))
        self._write_legacy(int(time.time()) + output_gate.DAY_SECONDS)
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertNotIn('mac', output_gate._state_path(server.WORK).read_text(encoding='utf-8'))
        output_gate._state_path(server.WORK).unlink()
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertFalse(output_gate._state_path(server.WORK).is_file())

    def test_revocation_stays_in_the_signed_record_without_the_side_file(self):
        self.pair()

        def deny(_raw, token):
            self.assertEqual(token, TOKEN)
            return 401, b'{"error":{"code":"revoked"}}'

        self.assertFalse(output_gate.check_in(server.WORK, transport=deny)['ok'])
        output_gate._revocation_path(server.WORK).unlink()
        os.environ['EZ_NEST_OUTPUT_UPLOADS'] = '1'
        os.environ['EZ_NEST_OUTPUT_TOKEN'] = TOKEN
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        calls = {'n': 0}

        def allow(raw, token):
            calls['n'] += 1
            calls['token'] = token
            self.assertEqual(json.loads(raw), {'appVersion': VERSION})
            return 200, b'{"outcome":"ok"}'

        self.assertFalse(output_gate.check_in(server.WORK, transport=allow)['ok'])
        self.assertEqual(calls['n'], 0)
        other = 'osa_' + 'D' * 43
        os.environ['EZ_NEST_OUTPUT_TOKEN'] = other
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertTrue(output_gate.check_in(server.WORK, transport=allow)['ok'])
        self.assertEqual(calls['token'], other)
        output_gate._revocation_path(server.WORK).unlink(missing_ok=True)
        os.environ['EZ_NEST_OUTPUT_TOKEN'] = TOKEN
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])

    def test_installed_module_stays_installed_without_the_release_marker(self):
        import eznest_build
        previous = eznest_build.INSTALLED
        eznest_build.INSTALLED = True
        try:
            marker = Path(output_gate.__file__).resolve().parent / output_gate.RELEASE_MARKER
            self.assertFalse(marker.exists())
            os.environ['EZ_NEST_DEV'] = '1'
            os.environ['EZ_NEST_DEV_NO_OUTPUT'] = '1'
            os.environ['EZ_NEST_OUTPUT_GATE_OPEN'] = '1'
            self.assertFalse(output_gate.source_checkout())
            self.assertFalse(output_gate.dev_escape())
            self.assertFalse(output_gate.gate_opt_out())
        finally:
            eznest_build.INSTALLED = previous

    def test_future_check_in_time_stays_closed_until_a_live_check_in(self):
        output_credential.save(server.WORK, TOKEN)
        output_gate.note_paired(server.WORK, now=int(time.time()) + 24 * 60 * 60)
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_RECONNECT)

        def transport(raw, token):
            self.assertEqual(json.loads(raw), {'appVersion': VERSION})
            self.assertEqual(token, TOKEN)
            return 200, b'{"outcome":"ok"}'

        status = output_gate.check_in(server.WORK, transport=transport)
        self.assertTrue(status['ok'])

    def test_environment_token_needs_a_live_check_in_and_a_revoked_token_stays_closed(self):
        os.environ['EZ_NEST_OUTPUT_UPLOADS'] = '1'
        os.environ['EZ_NEST_OUTPUT_TOKEN'] = TOKEN
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        calls = {'n': 0}

        def transport(raw, token):
            calls['n'] += 1
            self.assertEqual(token, TOKEN)
            self.assertEqual(json.loads(raw), {'appVersion': VERSION})
            return 200, b'{"outcome":"ok"}'

        self.assertTrue(output_gate.check_in(server.WORK, transport=transport)['ok'])
        self.assertEqual(calls['n'], 1)
        output_gate._remember_revoked(server.WORK, TOKEN)
        self.assertFalse(output_gate.public_status(server.WORK, True)['ok'])
        self.assertFalse(output_gate.check_in(server.WORK, transport=transport)['ok'])
        self.assertEqual(calls['n'], 1)
        self.assertNotIn(TOKEN, output_gate._revocation_path(server.WORK).read_text(encoding='utf-8'))
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_REVOKED)
        os.environ['EZ_NEST_OUTPUT_TOKEN'] = 'osa_' + 'D' * 43

        def other(raw, token):
            self.assertEqual(token, 'osa_' + 'D' * 43)
            return 200, b'{"outcome":"ok"}'

        self.assertTrue(output_gate.check_in(server.WORK, transport=other)['ok'])

    def test_check_in_posts_only_to_the_allowlisted_origin(self):
        self.pair()
        seen = {}

        class Response:
            status = 200

            def read(self, _size):
                return b'{"outcome":"ok"}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def open_request(request, timeout=10):
            seen['url'] = request.full_url
            seen['authorization'] = request.get_header('Authorization')
            return Response()

        opener = type('Opener', (), {'open': staticmethod(open_request)})()
        (server.WORK / 'shop.json').write_text(json.dumps({'outputUrl': 'https://evil.example'}), encoding='utf-8')
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_URL': 'https://evil.example/steal'}):
            with patch('output_gate.build_opener', return_value=opener):
                output_gate.check_in(server.WORK)
        self.assertEqual(seen['url'], 'https://output.jeezlabs.io/api/shop/agent/check-in')
        self.assertTrue(seen['authorization'].startswith('Bearer '))
        self.assertNotIn('evil.example', seen['url'])
        seen.clear()
        (server.WORK / 'shop.json').write_text(json.dumps({'outputUrl': 'https://other.example'}), encoding='utf-8')
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_URL': 'https://lab.example'}):
            with patch('output_gate.build_opener', return_value=opener):
                output_gate.check_in(server.WORK)
        self.assertEqual(seen['url'], 'https://lab.example/api/shop/agent/check-in')
        self.assertNotIn('other.example', seen['url'])

    def test_query_strings_allow_stock_and_validate_save_without_pairing(self):
        stock = self.handler('/api/materials?refresh=1')
        stock.do_GET()
        self.assert_api_open(stock.sent[0], output_gate.HOST_UNPAIRED)
        save = self.handler('/api/materials/save?x=1', body=b'{}')
        save.handle_post()
        self.assert_api_open(save.sent[0], output_gate.HOST_UNPAIRED, expected_status=400)
        check = self.handler('/api/telemetry/output/check-in?unused=1', body=b'{}')
        check.handle_post()
        self.assertEqual(check.sent[0][0], 200)
        self.assertFalse(check.sent[0][1]['ok'])
        self.pair()
        solve = self.handler('/api/solve?x=1', body=b'{}')
        solve.handle_post()
        self.assertNotEqual(solve.sent[0][0], 404)
        self.assertNotEqual(solve.sent[0][1].get('code'), 'connect_required')

    def test_loopback_helper_accepts_ipv6_loopback(self):
        self.pair()
        local = self.handler('/api/illustrator/' + 'ab' * 16, ip='::1')
        self.assertTrue(local.loopback_client())
        local.do_GET()
        self.assertEqual(local.sent[0][0], 404)
        mapped = self.handler('/api/illustrator/' + 'ab' * 16, ip='::ffff:127.0.0.1')
        self.assertTrue(mapped.loopback_client())
        remote = self.handler('/api/illustrator/' + 'ab' * 16, ip='10.0.0.9', host='127.0.0.1:8765')
        self.assertFalse(remote.loopback_client())
        remote.do_GET()
        self.assertEqual(remote.sent[0][0], 403)
        self.assertNotIn('handoff', remote.sent[0][1].get('error', ''))


def _state_text():
    path = output_gate._state_path(server.WORK)
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def sys_module():
    import sys
    return sys


if __name__ == '__main__':
    unittest.main()
