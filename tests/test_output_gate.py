"""The shop host must be connected to OUTPUT before nesting, sending, or stock."""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import output_credential
import output_gate
import output_pairing
import server
import shop_deploy
from app_info import VERSION

TOKEN = 'osa_' + 'C' * 43
ENV_KEYS = ('EZ_NEST_OUTPUT_GATE_ENFORCE', 'EZ_NEST_DEV', 'EZ_NEST_DEV_NO_OUTPUT', 'EZ_NEST_OUTPUT_UPLOADS', 'EZ_NEST_OUTPUT_TOKEN')


class GateTests(unittest.TestCase):
    def setUp(self):
        self.old = (server.WORK, server.HOST, server.PORT, server.LAN)
        self.old_env = {key: os.environ.get(key) for key in ENV_KEYS}
        self.tmp = tempfile.TemporaryDirectory()
        server.WORK = Path(self.tmp.name)
        server.HOST = '127.0.0.1'
        server.PORT = 8765
        server.LAN = False
        os.environ['EZ_NEST_OUTPUT_GATE_ENFORCE'] = '1'
        for key in ENV_KEYS:
            if key != 'EZ_NEST_OUTPUT_GATE_ENFORCE':
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

    def assert_blocked(self, sent, message):
        status, body, _headers = sent
        self.assertEqual(status, 403)
        self.assertEqual(body.get('code'), 'connect_required')
        self.assertEqual(body.get('error'), message)
        self.assertNotIn(TOKEN, json.dumps(body))

    def test_constants_are_named_days(self):
        self.assertEqual(output_gate.CHECK_IN_MAX_AGE_DAYS, 14)
        self.assertEqual(output_gate.CHECK_IN_MAX_AGE, 14 * 24 * 60 * 60)
        self.assertEqual(output_gate.OFFLINE_BANNER_AFTER_DAYS, 3)

    def test_unpaired_host_blocks_stock_and_nesting_but_keeps_gate_endpoints(self):
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_blocked(stock.sent[0], output_gate.HOST_UNPAIRED)
        solve = self.handler('/api/solve', body=b'{}')
        solve.handle_post()
        self.assert_blocked(solve.sent[0], output_gate.HOST_UNPAIRED)
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

    def test_designer_lan_client_is_told_to_ask_the_shop_computer(self):
        server.HOST = '0.0.0.0'
        server.LAN = True
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            stock = self.handler('/api/materials', ip='192.168.1.50')
            stock.do_GET()
            self.assert_blocked(stock.sent[0], output_gate.LAN_MESSAGE)
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

    def test_past_fourteen_days_blocks(self):
        self.pair(output_gate.CHECK_IN_MAX_AGE + 30)
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_blocked(stock.sent[0], output_gate.HOST_RECONNECT)
        self.assertTrue(output_credential.path(server.WORK).is_file())

    def test_revoked_credential_regates_and_check_in_sends_only_the_app_version(self):
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
        self.assert_blocked(stock.sent[0], output_gate.HOST_REVOKED)

    def test_a_successful_check_in_lifts_the_fourteen_day_gate(self):
        self.pair(output_gate.CHECK_IN_MAX_AGE + 30)
        blocked = self.handler('/api/materials')
        blocked.do_GET()
        self.assert_blocked(blocked.sent[0], output_gate.HOST_RECONNECT)

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
        self.assert_blocked(stock.sent[0], output_gate.HOST_UNPAIRED)
        os.environ['EZ_NEST_DEV'] = '1'
        with patch.object(sys_module(), 'frozen', True, create=True):
            self.assertFalse(output_gate.dev_escape())
            frozen = self.handler('/api/materials')
            frozen.do_GET()
            self.assert_blocked(frozen.sent[0], output_gate.HOST_UNPAIRED)

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

    def test_disconnect_returns_the_host_to_the_gate(self):
        self.pair()
        output_pairing.disconnect(server.WORK)
        stock = self.handler('/api/materials')
        stock.do_GET()
        self.assert_blocked(stock.sent[0], output_gate.HOST_DISCONNECTED)
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
                    shots = Path('/opt/cursor/artifacts/screenshots')
                    shots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / 'output-connect-gate.png'))
                finally:
                    browser.close()
        finally:
            helper.tearDown()

    def test_unittest_harness_does_not_open_a_normal_launch(self):
        os.environ.pop('EZ_NEST_OUTPUT_GATE_ENFORCE', None)
        with patch('sys.argv', ['launcher.py']):
            self.assertFalse(output_gate.test_harness_open())
            stock = self.handler('/api/materials')
            stock.do_GET()
            self.assert_blocked(stock.sent[0], output_gate.HOST_UNPAIRED)


def _state_text():
    path = output_gate._state_path(server.WORK)
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def sys_module():
    import sys
    return sys


if __name__ == '__main__':
    unittest.main()
