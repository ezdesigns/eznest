import opt_out
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import launcher
import server


class LauncherTests(unittest.TestCase):
    def test_isolated_test_cannot_attach_to_same_version_server(self):
        response=io.BytesIO(json.dumps({'app':'eznest','version':launcher.VERSION}).encode())
        with patch.object(sys,'argv',['eznest','--isolated','--data-dir','test-only']), \
             patch.object(launcher,'urlopen',return_value=response), patch('webbrowser.open') as browser, patch('server.serve') as serve:
            with self.assertRaisesRegex(RuntimeError,'will not open or change'):launcher.main()
            browser.assert_not_called()
            serve.assert_not_called()

    def test_isolated_test_requires_explicit_data_and_loopback(self):
        for args in (['--isolated'], ['--isolated','--data-dir','test-only','--lan']):
            with patch.object(sys,'argv',['eznest',*args]),patch.object(launcher,'urlopen') as lookup:
                with self.assertRaisesRegex(ValueError,'isolated test'):launcher.main()
                lookup.assert_not_called()

    def test_existing_same_version_reused(self):
        response=io.BytesIO(json.dumps({'app':'eznest','version':launcher.VERSION}).encode())
        with patch.object(sys,'argv',['eznest','--no-browser']),patch.object(launcher,'urlopen',return_value=response),patch('webbrowser.open') as browser:
            self.assertEqual(launcher.main(),0)
            browser.assert_not_called()

    def test_wrong_version_not_reused(self):
        response=io.BytesIO(b'{"app":"eznest","version":"old"}')
        with patch.object(sys,'argv',['eznest','--no-browser']),patch.object(launcher,'urlopen',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'using port 8765'):launcher.main()

    def test_frozen_worker_dispatch(self):
        with patch.object(sys,'argv',['eznest','--nest-worker','request path.json','result path.json']),patch('nesting.worker') as worker:
            self.assertEqual(launcher.main(),0)
            worker.assert_called_once_with('request path.json','result path.json')

    def test_telemetry_worker_dispatches_without_starting_server(self):
        with patch.object(sys,'argv',['eznest','--telemetry-worker']),patch('telemetry_sender.worker') as worker,patch('server.serve') as serve:
            self.assertEqual(launcher.main(),0)
            worker.assert_called_once_with()
            serve.assert_not_called()

    def test_public_host_rejected_before_network(self):
        with patch.object(sys,'argv',['eznest','--host','8.8.8.8','--no-browser']),patch.object(launcher,'urlopen') as lookup:
            with self.assertRaisesRegex(ValueError,'127.0.0.1'):launcher.main()
            lookup.assert_not_called()

    def test_invalid_port_rejected_before_network(self):
        with patch.object(sys,'argv',['eznest','--port','80']),patch.object(launcher,'urlopen') as lookup:
            with self.assertRaises(ValueError):launcher.main()
            lookup.assert_not_called()

    def _launch(self, argv, shop=None, pin=None):
        previous = {key: os.environ.get(key) for key in ('EZ_NEST_HOST', 'EZ_NEST_LAN', 'EZ_NEST_DATA', 'EZ_NEST_PORT')}
        saved = (server.HOST, server.LAN, server.PORT)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                if shop is not None:
                    Path(tmp, 'shop.json').write_text(json.dumps(shop), encoding='utf-8')
                if pin is not None:
                    import shop_auth
                    shop_auth.set_pin(tmp, pin)
                with patch.object(sys, 'argv', ['eznest', *argv, '--data-dir', tmp]), \
                     patch.object(launcher, 'urlopen', side_effect=URLError('down')), \
                     patch('server.serve') as serve:
                    self.assertEqual(launcher.main(), 0)
                    serve.assert_called_once()
                    return os.environ['EZ_NEST_HOST'], os.environ['EZ_NEST_LAN']
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            server.HOST, server.LAN, server.PORT = saved

    def test_shop_test_disables_inherited_output_upload_gate(self):
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '1'}), patch('shop_test.prepare'):
            self._launch(['--shop-test', '--no-browser'])
            self.assertEqual(os.environ['EZ_NEST_OUTPUT_UPLOADS'], '0')

    def test_lan_flag_opens_the_shop_network(self):
        host, lan = self._launch(['--lan', '--no-browser'], pin='12345678')
        self.assertEqual(host, '0.0.0.0')
        self.assertEqual(lan, '1')

    def test_lan_flag_without_a_pin_stays_on_loopback_and_waits(self):
        try:
            host, lan = self._launch(['--lan', '--no-browser'])
            self.assertEqual(host, '127.0.0.1')
            self.assertEqual(lan, '0')
            self.assertEqual(os.environ.get('EZ_NEST_LAN_WAITING'), 'pin')
        finally:
            os.environ.pop('EZ_NEST_LAN_WAITING', None)

    def test_lan_flag_with_a_pin_clears_waiting(self):
        os.environ['EZ_NEST_LAN_WAITING'] = 'pin'
        host, lan = self._launch(['--lan', '--no-browser'], pin='12345678')
        self.assertEqual(host, '0.0.0.0')
        self.assertNotIn('EZ_NEST_LAN_WAITING', os.environ)

    def test_saved_shop_network_cannot_open_without_lan_flag(self):
        host, lan = self._launch(['--no-browser'], {'onyxPc': False, 'lan': True})
        self.assertEqual(host, '127.0.0.1')
        self.assertEqual(lan, '0')

    def test_default_start_stays_on_loopback(self):
        host, lan = self._launch(['--no-browser'])
        self.assertEqual(host, '127.0.0.1')
        self.assertEqual(lan, '0')

    def test_container_host_does_not_enable_shop_names(self):
        with self.assertRaisesRegex(ValueError, '--lan'):
            self._launch(['--host', '0.0.0.0', '--no-browser'], {'lan': True})
