"""Stock summary projection and delivery. Transport is injected; no live network."""
import hashlib
import io
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import opt_out  # noqa: F401
import material_inventory as inventory
import output_credential
import shop_auth
import shop_deploy
import stock_output
import telemetry_sender
import server

TOKEN = 'osa_' + 'A' * 43


def profile(**overrides):
    values = {
        'preset-name': 'Gloss white', 'unit': 'in', 'width': '50', 'roll': '54',
        'available-length': '1446', 'roll-length': '1500', 'gap': '0', 'margin': '0',
        'mark-margin': '0', 'sheet': '', 'rotations': 'free', 'auto-bleed': '0',
        'bleed': '0', 'cost': '19.99', 'roll-cost': '250', 'low-stock': '100',
        'print-layout': 'continuous',
    }
    values.update(overrides)
    return values


def material(identity, name, **overrides):
    values = profile(**{'preset-name': name, **overrides})
    on_hand = Decimal('1446') * Decimal('25.4')
    if values['available-length'] == '':
        on_hand = None
    return {
        'id': identity,
        'profile': values,
        'onHandMm': on_hand,
        'reservedMm': overrides.get('reservedMm', 0),
        'customer': 'SECRET-CUSTOMER',
        'file': 'customer-art.pdf',
        'supplier': 'SECRET-SUPPLIER',
    }


class ProjectionTests(unittest.TestCase):
    def project(self, materials, show_names=True):
        snapshot = {
            'materials': materials,
            'reservations': [{
                'id': 'EZ-4242', 'fingerprint': 'SECRET-FINGERPRINT', 'status': 'reserved',
                'length': 12, 'material': 'roll-a',
            }],
        }
        payload, fingerprint = stock_output.project_snapshot(
            snapshot, show_names=show_names, instance_id='instance', snapshot_at='2026-01-01T00:00:00.000000Z')
        return payload, fingerprint

    def test_payload_is_the_allowlisted_summary(self):
        payload, _fingerprint = self.project([material('roll-a', 'Gloss white')])
        self.assertEqual(set(payload), set(stock_output.PAYLOAD_KEYS))
        self.assertEqual(payload['schema'], 'eznest-stock/1')
        self.assertEqual(payload['unit'], 'ft')
        self.assertEqual(payload['snapshotAt'], '2026-01-01T00:00:00.000000Z')
        self.assertEqual(payload['appVersion'], '1.0.0-rc.5')
        self.assertEqual(uuid.UUID(payload['requestId']).version, 5)
        roll = payload['rolls'][0]
        self.assertEqual(set(roll), set(stock_output.ROLL_KEYS))
        self.assertEqual(roll['key'], hashlib.sha256(b'roll-a').hexdigest()[:32])
        self.assertEqual(roll['name'], 'Gloss white')
        self.assertEqual(roll['widthIn'], 54)
        self.assertEqual(roll['leftFt'], 120.5)
        self.assertEqual(roll['reservedFt'], 0)
        self.assertIs(roll['low'], False)
        again, _ = self.project([material('roll-a', 'Gloss white')])
        self.assertEqual(again['requestId'], payload['requestId'])

    def test_omissions_unknown_stock_and_rejected_names(self):
        unknown = material('roll-b', 'Empty', **{'available-length': '', 'low-stock': '10'})
        unknown['onHandMm'] = None
        unknown['reservedMm'] = 304.8
        low = material('roll-c', 'Short', **{'available-length': '10', 'low-stock': '20', 'roll': '30'})
        low['onHandMm'] = Decimal('10') * Decimal('25.4')
        rejected = [
            material('roll-d', 'EZ-1000'),
            material('roll-e', r'C:\rolls\white'),
            material('roll-f', 'buyer@shop.example'),
            material('roll-g', 'https://example.test/roll'),
            material('roll-h', 'a' * 61),
            material('roll-i', 'www.shop.example'),
        ]
        payload, _fingerprint = self.project([unknown, low, *rejected, material('roll-a', 'Gloss white')])
        raw = json.dumps(payload)
        for secret in ('SECRET-CUSTOMER', 'SECRET-SUPPLIER', 'SECRET-FINGERPRINT', 'customer-art.pdf',
                       'EZ-4242', '19.99', 'EZ-1000', 'buyer@shop.example', 'example.test', r'C:\rolls'):
            self.assertNotIn(secret, raw)
        rolls = {roll['key']: roll for roll in payload['rolls']}
        empty = rolls[hashlib.sha256(b'roll-b').hexdigest()[:32]]
        self.assertIsNone(empty['leftFt'])
        self.assertIs(empty['low'], False)
        self.assertEqual(empty['reservedFt'], 1)
        short = rolls[hashlib.sha256(b'roll-c').hexdigest()[:32]]
        self.assertIs(short['low'], True)
        self.assertEqual(short['widthIn'], 30)
        for identity in ('roll-d', 'roll-e', 'roll-f', 'roll-g', 'roll-h', 'roll-i'):
            roll = rolls[hashlib.sha256(identity.encode()).hexdigest()[:32]]
            self.assertIsNone(roll['name'])
        hidden, _fingerprint = self.project([material('roll-a', 'Gloss white')], show_names=False)
        self.assertIsNone(hidden['rolls'][0]['name'])
        self.assertNotEqual(hidden['requestId'], payload['requestId'])

    def test_caps_drop_extra_rolls_and_keep_the_request_small(self):
        rolls = [material(f'roll-{index:03d}', 'N' * 60) for index in range(201)]
        payload, _fingerprint = self.project(rolls)
        self.assertLessEqual(len(payload['rolls']), 200)
        self.assertLessEqual(len(json.dumps(payload, separators=(',', ':')).encode()), 32768)
        self.assertNotIn(hashlib.sha256(b'roll-200').hexdigest()[:32], [roll['key'] for roll in payload['rolls']])
        with patch.object(stock_output, 'MAX_BYTES', 420):
            small, _fingerprint = self.project(rolls[:20])
        self.assertLessEqual(len(json.dumps(small, separators=(',', ':')).encode()), 420)
        self.assertLess(len(small['rolls']), 20)
        self.assertGreater(len(small['rolls']), 0)

    def test_each_roll_drops_extra_source_fields(self):
        extras = {
            'customer': 'PRIVATE-CUSTOMER', 'phone': '0912-345-678',
            'jobCode': 'EZ-9876', 'email': 'private@example.test',
            'address': 'PRIVATE-ADDRESS', 'gps': 'PRIVATE-GPS',
            'ip': '192.0.2.123', 'payment': 'PRIVATE-PAYMENT',
            'account': 'PRIVATE-ACCOUNT', 'cost': 'PRIVATE-COST',
            'supplier': 'PRIVATE-SUPPLIER', 'file': 'private-file.pdf',
            'profileText': 'PRIVATE-PROFILE', 'credential': TOKEN,
        }
        sources = [material('roll-a', 'Gloss white'), material('roll-b', 'Matte white')]
        for source in sources:
            source.update(extras)
            source['profile'].update(extras)
        payload, _ = self.project(sources)
        self.assertEqual(len(payload['rolls']), 2)
        for roll in payload['rolls']:
            self.assertEqual(set(roll), set(stock_output.ROLL_KEYS))
        raw = json.dumps(payload)
        for key, value in extras.items():
            self.assertNotIn('"' + key + '"', raw)
            self.assertNotIn(value, raw)

    def test_roll_whitelist_is_enforced_after_projection(self):
        roll = stock_output._roll(material('roll-a', 'Gloss white'), True)
        with patch.object(stock_output, '_roll', return_value={**roll, 'customer': 'PRIVATE-CUSTOMER'}):
            payload, _ = self.project([{}])
        self.assertEqual(set(payload['rolls'][0]), set(stock_output.ROLL_KEYS))
        self.assertNotIn('PRIVATE-CUSTOMER', json.dumps(payload))
        del roll['low']
        with patch.object(stock_output, '_roll', return_value=roll):
            with self.assertRaises(ValueError):
                self.project([{}])

    def test_plain_name_rejects_email_and_phone_patterns(self):
        for name in ('a@b.com', 'Call 0912-345-678', '+886 912 345 678', '(02)2345-6789'):
            with self.subTest(name=name):
                self.assertIsNone(stock_output.plain_name(name, True))
                payload, _ = self.project([material('roll-a', name)])
                self.assertIsNone(payload['rolls'][0]['name'])
                self.assertNotIn(name, json.dumps(payload))

    def test_plain_name_keeps_roll_widths(self):
        for name in ('Gloss vinyl 54 in', '3M IJ180Cv3 60in'):
            with self.subTest(name=name):
                self.assertEqual(stock_output.plain_name(name, True), name)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sent = []
        self.results = []
        self.env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

        def deliver(method, url, payload, token):
            self.sent.append({'method': method, 'url': url, 'payload': payload, 'token': token})
            if self.results:
                return self.results.pop(0)
            return True

        self.deliver = patch.object(stock_output, 'deliver', side_effect=deliver)
        self.deliver.start()
        self.addCleanup(self.deliver.stop)
        inventory.save(self.root, 'roll-a', profile(), 0)
        output_credential.save(self.root, TOKEN)
        shop_deploy.save_shop(self.root, False, False, shareStockSummary=True, showRollNames=True)

    def test_defaults_are_off(self):
        directory = self.root / 'empty'
        bare = shop_deploy.load_shop(directory)
        self.assertIs(bare['shareStockSummary'], False)
        self.assertIs(bare['showRollNames'], False)
        output_credential.save(directory, TOKEN)
        stock_output.tick(directory, now=0)
        self.assertEqual(self.sent, [])

    def test_sharing_on_but_unpaired_sends_nothing(self):
        output_credential.clear(self.root)
        stock_output.tick(self.root, now=0)
        self.assertEqual(self.sent, [])

    def test_sharing_on_and_paired_sends(self):
        stock_output.tick(self.root, now=0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['method'], 'PUT')

    def test_send_path_rechecks_consent_and_pairing(self):
        payload, _ = stock_output.build_payload(self.root)
        shop_deploy.save_shop(self.root, False, False, shareStockSummary=False)
        self.assertFalse(stock_output._send(self.root, 'PUT', payload, TOKEN))
        shop_deploy.save_shop(self.root, False, False, shareStockSummary=True)
        output_credential.clear(self.root)
        self.assertFalse(stock_output._send(self.root, 'PUT', payload, TOKEN))
        self.assertEqual(self.sent, [])
        output_credential.save(self.root, TOKEN)
        self.assertTrue(stock_output._send(self.root, 'PUT', payload, TOKEN))
        self.assertEqual(len(self.sent), 1)

    def test_unpairing_during_projection_prevents_upload(self):
        build = stock_output.build_payload

        def unpair(directory):
            payload = build(directory)
            output_credential.clear(directory)
            return payload

        with patch.object(stock_output, 'build_payload', side_effect=unpair):
            stock_output.tick(self.root, now=0)
        self.assertEqual(self.sent, [])

    def test_maintenance_pauses_upload_and_pending_delete(self):
        stock_output.tick(self.root, now=0, paused=lambda: True)
        self.assertEqual(self.sent, [])
        stock_output.tick(self.root, now=0)
        self.assertEqual(len(self.sent), 1)
        before = shop_deploy.load_shop(self.root)
        after = shop_deploy.save_shop(self.root, False, False, shareStockSummary=False)
        stock_output.apply_settings(self.root, before, after)
        stock_output.tick(self.root, now=1, paused=lambda: True)
        self.assertEqual(len(self.sent), 1)
        stock_output.tick(self.root, now=2)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[-1]['method'], 'DELETE')

    def test_maintenance_starting_during_projection_prevents_upload(self):
        build = stock_output.build_payload
        maintenance = {'paused': False}

        def pause(directory):
            payload = build(directory)
            maintenance['paused'] = True
            return payload

        with patch.object(stock_output, 'build_payload', side_effect=pause):
            stock_output.tick(self.root, now=0, paused=lambda: maintenance['paused'])
        self.assertEqual(self.sent, [])

    def test_consent_off_and_shop_test_send_nothing(self):
        shop_deploy.save_shop(self.root, False, False, shareStockSummary=False)
        stock_output.tick(self.root, now=0)
        self.assertEqual(self.sent, [])
        shop_deploy.save_shop(self.root, False, False, shareStockSummary=True)
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '0'}):
            stock_output.tick(self.root, now=0)
            before = shop_deploy.load_shop(self.root)
            after = shop_deploy.save_shop(self.root, False, False, shareStockSummary=False)
            stock_output.apply_settings(self.root, before, after)
            stock_output.tick(self.root, now=1)
        self.assertEqual(self.sent, [])

    def test_debounce_heartbeat_backoff_and_delete(self):
        stock_output.tick(self.root, now=0)
        self.assertEqual(self.sent[0]['method'], 'PUT')
        self.assertTrue(self.sent[0]['url'].endswith('/api/shop/agent/stock'))
        self.assertEqual(self.sent[0]['token'], TOKEN)
        self.assertNotIn(TOKEN, json.dumps(stock_output.public_status(self.root)))
        first = self.sent[0]['payload']['requestId']
        stock_output.note_change(self.root, now=10)
        inventory.save(self.root, 'roll-a', profile(**{'available-length': '1200'}), 1)
        stock_output.tick(self.root, now=39)
        self.assertEqual(len(self.sent), 1)
        stock_output.tick(self.root, now=40)
        self.assertEqual(len(self.sent), 2)
        self.assertNotEqual(self.sent[1]['payload']['requestId'], first)
        stock_output.tick(self.root, now=3600)
        self.assertEqual(len(self.sent), 2)
        stock_output.tick(self.root, now=3640)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.sent[2]['payload']['requestId'], self.sent[1]['payload']['requestId'])
        self.assertNotIn('19.99', json.dumps(self.sent[0]['payload']))
        before = shop_deploy.load_shop(self.root)
        after = shop_deploy.save_shop(self.root, False, False, shareStockSummary=False)
        stock_output.apply_settings(self.root, before, after)
        count = len(self.sent)
        stock_output.tick(self.root, now=3640)
        self.assertEqual(self.sent[-1]['method'], 'DELETE')
        self.assertIsNone(self.sent[-1]['payload'])
        stock_output.tick(self.root, now=3641)
        self.assertEqual(len(self.sent), count + 1)

    def test_backoff_grows_from_30_seconds_to_15_minutes(self):
        self.results[:] = [False] * 12
        now = 0
        wait = 30
        for _ in range(8):
            count = len(self.sent)
            stock_output.tick(self.root, now=now)
            self.assertEqual(len(self.sent), count + 1)
            stock_output.tick(self.root, now=now + wait - 1)
            self.assertEqual(len(self.sent), count + 1)
            now += wait
            wait = min(max(wait * 2, 30), 900)
        self.assertEqual(wait, 900)

    def test_name_toggle_sends_null_after_the_debounce(self):
        times = {'now': 0}
        with patch.object(stock_output, 'clock', lambda: times['now']):
            stock_output.tick(self.root)
            self.assertEqual(self.sent[-1]['payload']['rolls'][0]['name'], 'Gloss white')
            times['now'] = 5
            before = shop_deploy.load_shop(self.root)
            after = shop_deploy.save_shop(self.root, False, False, shareStockSummary=True, showRollNames=False)
            stock_output.apply_settings(self.root, before, after)
            times['now'] = 34
            stock_output.tick(self.root)
            self.assertEqual(len(self.sent), 1)
            times['now'] = 35
            stock_output.tick(self.root)
        self.assertIsNone(self.sent[-1]['payload']['rolls'][0]['name'])
        self.assertNotIn('Gloss white', json.dumps(self.sent[-1]['payload']))

    def test_token_is_not_logged_when_delivery_fails(self):
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        logging.getLogger().addHandler(handler)
        try:
            with patch.object(stock_output, 'deliver', side_effect=RuntimeError('bearer ' + TOKEN)):
                stock_output.tick(self.root, now=0)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertNotIn(TOKEN, buffer.getvalue())

    def test_sender_checks_at_start_and_stops(self):
        calls = []
        stop = threading.Event()
        with patch.object(stock_output, 'tick', side_effect=lambda directory, **kwargs: calls.append(directory) or 30):
            thread = threading.Thread(target=stock_output.run, args=(self.root, stop))
            thread.start()
            for _ in range(100):
                if calls:
                    break
                time.sleep(0.01)
            stop.set()
            stock_output.WAKE.set()
            thread.join(2)
        self.assertTrue(calls)
        self.assertFalse(thread.is_alive())


class TransportTests(unittest.TestCase):
    def test_put_and_delete_use_the_isolated_https_transport(self):
        url = 'https://output.jeezlabs.io/api/shop/agent/stock'
        with patch.object(telemetry_sender.subprocess, 'run') as run:
            self.assertFalse(telemetry_sender.emit({'schema': 'eznest-stock/1'}, TOKEN, method='PUT', url='http://output.jeezlabs.io/api/shop/agent/stock'))
            self.assertFalse(telemetry_sender.emit({'schema': 'eznest-stock/1'}, TOKEN, method='PUT', url='https://evil.example/api/shop/agent/stock'))
            run.assert_not_called()
            run.return_value = subprocess.CompletedProcess([], 0, b'true', b'')
            self.assertTrue(telemetry_sender.emit({'schema': 'eznest-stock/1'}, TOKEN, method='PUT', url=url))
            _args, kwargs = run.call_args
            self.assertEqual(kwargs['timeout'], 10)
            self.assertNotIn(TOKEN, repr(kwargs['env']))
            self.assertNotIn(TOKEN, repr(run.call_args.args))
            message = json.loads(kwargs['input'])
            self.assertEqual(message['method'], 'PUT')
            self.assertEqual(message['url'], url)
            self.assertEqual(message['token'], TOKEN)
        seen = []

        class Response:
            status = 204
            def read(self, _n):
                return b''
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, request, timeout):
                seen.append((request.get_method(), request.full_url, timeout, request.data))
                return Response()

        with patch.object(telemetry_sender, 'build_opener', return_value=Opener()) as build:
            self.assertTrue(telemetry_sender._emit_stock(url, {'schema': 'eznest-stock/1'}, TOKEN, 'PUT'))
            self.assertIsInstance(build.call_args.args[0], telemetry_sender.NoRedirect)
            self.assertEqual(seen[0][0], 'PUT')
            self.assertEqual(seen[0][1], url)
            self.assertEqual(seen[0][2], 10)
            self.assertTrue(telemetry_sender._emit_stock(url, None, TOKEN, 'DELETE'))
            self.assertEqual(seen[1][0], 'DELETE')
            self.assertIsNone(seen[1][3])
        self.assertFalse(telemetry_sender._emit_stock('http://127.0.0.1/api/shop/agent/stock', None, TOKEN, 'DELETE'))
        self.assertFalse(telemetry_sender._emit_stock('https://output.jeezlabs.io/api/shop/telemetry', {'schema': 'eznest-stock/1'}, TOKEN, 'PUT'))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.old = (server.WORK, server.HOST, server.PORT, server.LAN)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        server.WORK = Path(self.tmp.name)
        server.HOST = '127.0.0.1'
        server.PORT = 8765
        server.LAN = False
        shop_auth.reset_for_tests()
        shop_deploy.clear_name_cache()
        self.addCleanup(self.restore)
        inventory.save(server.WORK, 'roll-a', profile(), 0)

    def restore(self):
        server.WORK, server.HOST, server.PORT, server.LAN = self.old
        shop_auth.reset_for_tests()
        shop_deploy.clear_name_cache()

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

    def test_lan_client_cannot_toggle_and_preview_matches_the_payload(self):
        shop_deploy.clear_name_cache()
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.50']):
            shop_deploy.clear_name_cache()
            server.HOST = '0.0.0.0'
            server.LAN = True
            sid = shop_auth.issue_session('192.168.1.50')
            headers = {'Cookie': 'eznest_session=' + sid, 'X-EZ-Token': 'nope'}
            body = json.dumps({'onyxPc': False, 'lan': True, 'shareStockSummary': True, 'showRollNames': False}).encode()
            denied = self.handler('/api/shop', body=body, ip='192.168.1.50', headers=headers)
            denied.handle_post()
            self.assertEqual(denied.sent[0][0], 403)
            self.assertIs(shop_deploy.load_shop(server.WORK)['shareStockSummary'], False)
            self.assertIs(shop_deploy.load_shop(server.WORK)['showRollNames'], False)
            preview = self.handler('/api/stock/output', ip='192.168.1.50', headers=headers)
            preview.do_GET()
            self.assertEqual(preview.sent[0][0], 403)
        server.HOST = '127.0.0.1'
        server.LAN = False
        host_preview = self.handler('/api/stock/output')
        host_preview.do_GET()
        self.assertEqual(host_preview.sent[0][0], 200)
        body = host_preview.sent[0][1]
        self.assertNotIn(TOKEN, json.dumps(body))
        self.assertEqual(body['preview'], stock_output.build_payload(server.WORK)[0])
        self.assertIsNone(body['preview']['rolls'][0]['name'])
        shown = self.handler('/api/stock/output?names=1')
        shown.do_GET()
        self.assertEqual(shown.sent[0][1]['preview']['rolls'][0]['name'], 'Gloss white')
        hidden = self.handler('/api/stock/output?names=0')
        hidden.do_GET()
        self.assertIsNone(hidden.sent[0][1]['preview']['rolls'][0]['name'])
        self.assertIs(shop_deploy.load_shop(server.WORK)['showRollNames'], False)
        turned = self.handler('/api/shop', body=json.dumps({'onyxPc': False, 'lan': False, 'shareStockSummary': True, 'showRollNames': False}).encode())
        turned.handle_post()
        self.assertEqual(turned.sent[0][0], 200)
        self.assertIs(turned.sent[0][1]['shareStockSummary'], True)
        self.assertIs(turned.sent[0][1]['showRollNames'], False)
        self.assertIs(shop_deploy.load_shop(server.WORK)['shareStockSummary'], True)


class ScreenTests(unittest.TestCase):
    def test_settings_show_the_toggles_and_the_preview(self):
        from playwright.sync_api import sync_playwright
        import test_web_mvp
        helper = test_web_mvp.WebMvpTests(methodName='runTest')
        helper.setUp()
        try:
            inventory.save(server.WORK, 'roll-a', profile(), 0)
            folder = Path('/opt/cursor/artifacts/screenshots')
            folder.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page(viewport={'width': 1366, 'height': 768})
                    page.goto(helper.url() + '/web')
                    helper.wait_ready(page)
                    page.click('#settings-open')
                    self.assertTrue(page.locator('#settings-stock-share').is_hidden())
                    page.wait_for_function("() => document.querySelector('#stock-output-preview').textContent.includes('\"name\": null')")
                    self.assertFalse(page.locator('#share-stock-summary').is_checked())
                    self.assertFalse(page.locator('#show-roll-names').is_checked())
                    section = page.locator('#settings-stock-share').text_content()
                    self.assertIn('Share stock summary with OUTPUT', section)
                    self.assertIn('Show roll names in OUTPUT', section)
                    preview = json.loads(page.locator('#stock-output-preview').text_content())
                    self.assertEqual(set(preview), set(stock_output.PAYLOAD_KEYS))
                    self.assertIsNone(preview['rolls'][0]['name'])
                    self.assertNotIn(TOKEN, page.locator('#stock-output-preview').text_content())
                    self.assertNotIn('Gloss white', page.locator('#stock-output-preview').text_content())
                    # EZ39-9: OUTPUT has no receiving endpoint, so the share control cannot be turned on.
                    self.assertTrue(page.locator('#share-stock-summary').is_disabled())
                    self.assertIn('OUTPUT cannot receive stock summaries yet', section)
                    page.click('#save-settings')
                    page.wait_for_function("() => document.querySelector('#settings-saved').textContent === 'Saved.'")
                    saved = json.loads((server.WORK / 'shop.json').read_text(encoding='utf-8'))
                    self.assertIs(saved['shareStockSummary'], False)
                    self.assertIs(saved['showRollNames'], False)
                    note = page.locator('#stock-output-note').text_content().casefold()
                    self.assertIn('nothing is sent', note)
                    self.assertIn('paired', note)
                finally:
                    browser.close()
        finally:
            helper.tearDown()


if __name__ == '__main__':
    unittest.main()
