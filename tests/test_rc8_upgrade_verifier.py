"""Privileged QA verifier failure boundaries, without installing or compiling."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import verify_rc8_upgrade as q


class UpgradeVerifierTests(unittest.TestCase):
    def receipt(self, root):
        folder = root / 'rc7-baseline'; folder.mkdir()
        value = {'version':q.BASELINE, 'commit':q.BASELINE_SOURCE, 'sha256':q.BASELINE_HASH,
            'teamId':q.a.TEAM, 'architecture':'arm64'}
        value.update({key:True for key in ('applicationNotarized','packageNotarized','packageSigned',
            'installed','offlineFileFlows','restartPersistence','cleanup')})
        (folder / 'MACOS-RELEASE.json').write_text(json.dumps(value))
        return folder, value

    def test_other_rc7_source_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, value = self.receipt(root)
            value['commit'] = '0' * 40
            (source / 'MACOS-RELEASE.json').write_text(json.dumps(value))
            with self.assertRaisesRegex(q.a.AcceptanceError, 'reviewed signed test build'):
                q.baseline(root)
            self.assertFalse((root / f'eznest-shop-arm64-{q.BASELINE}.pkg').exists())

    def test_changed_baseline_bytes_cannot_count_as_reviewed_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, _ = self.receipt(root)
            (source / f'eznest-shop-arm64-{q.BASELINE}.pkg').write_bytes(b'changed signed package')
            with self.assertRaisesRegex(q.a.AcceptanceError, 'checksum mismatch'):
                q.baseline(root)

    def test_linked_baseline_package_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, _ = self.receipt(root)
            target = root / 'borrowed'; target.write_bytes(b'not owned package')
            (source / f'eznest-shop-arm64-{q.BASELINE}.pkg').symlink_to(target)
            with self.assertRaisesRegex(q.a.AcceptanceError, 'bounded regular file'):
                q.baseline(root)
            self.assertEqual(target.read_bytes(), b'not owned package')

    def test_local_execution_cannot_start_work(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(q, 'run') as run, \
                patch.object(q.sys, 'argv', ['verify_rc8_upgrade.py', 'Run']):
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
