"""Privileged QA verifier failure boundaries, without installing or compiling."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import verify_rc7_upgrade as q


class UpgradeVerifierTests(unittest.TestCase):
    def test_local_execution_cannot_start_work(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(q, 'run') as run, \
                patch.object(q.sys, 'argv', ['verify_rc7_upgrade.py', 'Run']):
            self.assertEqual(q.main(), 1)
            run.assert_not_called()

    def test_foreign_owned_installation_cannot_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'eznest-macos-owned.json').write_text(json.dumps({'runId':'other','installerSettled':True}))
            with patch.dict(os.environ, {'GITHUB_RUN_ID':'12'}), patch.object(q.a, 'verify_package'), \
                    patch.object(q.subprocess, 'Popen') as start:
                with self.assertRaises(q.a.AcceptanceError): q.upgrade(root, 'a' * 64)
                start.assert_not_called()

    def test_timed_out_upgrade_never_authorizes_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); marker = root / 'eznest-macos-owned.json'
            marker.write_text(json.dumps({'runId':'12','installerSettled':True}))
            process = Mock(pid=123)
            process.wait.side_effect = [subprocess.TimeoutExpired('installer', 240), 0]
            with patch.dict(os.environ, {'GITHUB_RUN_ID':'12'}), patch.object(q.a, 'verify_package'), \
                    patch.object(q.subprocess, 'Popen', return_value=process), \
                    patch.object(q.a, 'command'), patch.object(q.a, 'sudo_python') as cleanup:
                with self.assertRaisesRegex(q.a.AcceptanceError, 'timed out'): q.upgrade(root, 'a' * 64)
                self.assertFalse(json.loads(marker.read_text())['installerSettled'])
                with self.assertRaises(q.a.AcceptanceError): q.a.cleanup(root)
                cleanup.assert_not_called()

    def test_cross_host_or_insecure_redirect_is_rejected(self):
        for url in ['https://attacker.example/pkg', 'http://release-assets.githubusercontent.com/pkg',
                    'https://user@release-assets.githubusercontent.com/pkg']:
            with self.assertRaises(q.a.AcceptanceError):
                q.ReleaseRedirect().redirect_request(None, None, 302, '', {}, url)


if __name__ == '__main__': unittest.main()
