import io
import json
import sys
import unittest
from unittest.mock import patch
import launcher


class LauncherTests(unittest.TestCase):
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

    def test_public_host_rejected_before_network(self):
        with patch.object(sys,'argv',['eznest','--host','8.8.8.8','--no-browser']),patch.object(launcher,'urlopen') as lookup:
            with self.assertRaisesRegex(ValueError,'127.0.0.1'):launcher.main()
            lookup.assert_not_called()

    def test_invalid_port_rejected_before_network(self):
        with patch.object(sys,'argv',['eznest','--port','80']),patch.object(launcher,'urlopen') as lookup:
            with self.assertRaises(ValueError):launcher.main()
            lookup.assert_not_called()
