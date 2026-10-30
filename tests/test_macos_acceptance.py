"""Negative boundaries of the disposable Mac acceptance verifier (no OS writes)."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from macos_svg_acceptance import local_browser_url

import test_published_macos as acceptance


class MacAcceptanceVerifierTests(unittest.TestCase):
    def test_local_or_non_arm_runner_is_rejected_before_using_temp(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(acceptance.AcceptanceError):
                acceptance.runner_guard()
        env = {'CI':'true', 'GITHUB_ACTIONS':'true', 'RUNNER_ENVIRONMENT':'github-hosted',
               'RUNNER_OS':'macOS', 'GITHUB_REPOSITORY':'ezdesigns/eznest', 'GITHUB_RUN_ID':'1'}
        for arch, os_version in (('x86_64', '26.0'), ('arm64', '15.0')):
            with patch.dict(os.environ, env, clear=True), patch.object(acceptance.sys, 'platform', 'darwin'), \
                    patch.object(acceptance.platform, 'machine', return_value=arch), \
                    patch.object(acceptance.platform, 'mac_ver', return_value=(os_version, (), '')):
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.runner_guard()

    def test_candidate_url_never_sends_access_to_another_host(self):
        for url in ('http://release-assets.githubusercontent.com/a?sig=x',
                    'https://attacker.example/a?sig=x',
                    'https://user@release-assets.githubusercontent.com/a?sig=x',
                    'https://release-assets.githubusercontent.com/a?sig=x#fragment', ''):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {'EZ_NEST_MACOS_CANDIDATE_URL':url}), \
                    patch.object(acceptance, 'build_opener') as opener:
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.download(Path(folder))
                opener.assert_not_called()
                self.assertNotIn('EZ_NEST_MACOS_CANDIDATE_URL', os.environ)

    def test_mismatched_download_is_never_assessed_or_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / 'test.pkg'; package.write_bytes(b'reviewed package bytes')
            with patch.object(acceptance, 'command') as command:
                with self.assertRaisesRegex(acceptance.AcceptanceError, 'checksum mismatch'):
                    acceptance.verify_package(package, '0' * 64)
            command.assert_not_called()

    def test_wrong_publisher_or_app_store_identity_is_rejected_before_gatekeeper(self):
        for identity in ('Developer ID Installer: Other (ABCDEFGHIJ)',
                         '3rd Party Mac Developer Installer: Publisher (JC6858UYM9)'):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as folder:
                package = Path(folder) / 'test.pkg'; package.write_bytes(b'candidate')
                result = subprocess.CompletedProcess([], 0,
                    'Status: signed by a certificate trusted by macOS\n1. ' + identity + '\n', '')
                with patch.object(acceptance, 'command', return_value=result) as command:
                    with self.assertRaisesRegex(acceptance.AcceptanceError, 'approved Developer ID'):
                        acceptance.verify_package(package, hashlib.sha256(b'candidate').hexdigest())
                self.assertEqual(command.call_count, 1)

    def test_unnotarized_candidate_is_never_expanded(self):
        signed = subprocess.CompletedProcess([], 0,
            'Status: signed by a certificate trusted by macOS\n'
            '1. Developer ID Installer: Publisher (JC6858UYM9)\n', '')
        unsigned = subprocess.CompletedProcess([], 0, '', 'source=Developer ID')
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / 'test.pkg'; package.write_bytes(b'candidate')
            with patch.object(acceptance, 'command', side_effect=[signed, unsigned]) as command:
                with self.assertRaisesRegex(acceptance.AcceptanceError, 'notarized Gatekeeper'):
                    acceptance.verify_package(package, hashlib.sha256(b'candidate').hexdigest())
            self.assertEqual(command.call_count, 2)

    def test_preexisting_shop_never_gets_an_ownership_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); existing = root / 'existing-shop'; existing.mkdir()
            with patch.object(acceptance, 'OWNED_PATHS', (existing,)), \
                    patch.object(acceptance, 'verify_package'), \
                    patch.object(acceptance, 'write_json') as write, \
                    patch.object(acceptance.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(acceptance.AcceptanceError, 'Existing shop files'):
                    acceptance.install(root, 'a' * 64)
                write.assert_not_called(); process.assert_not_called()
            self.assertTrue(existing.is_dir())

    def test_offline_grace_and_revocation_cannot_count_as_fresh_checkin(self):
        for timestamp, response in ((100, {'ok': True}), (99, {'ok': True}),
                                    (101, {'ok': False, 'state': 'revoked'}),
                                    (101, {'ok': True, 'devMode': True})):
            api = Mock(); api.request.return_value = (200, response)
            with self.subTest(timestamp=timestamp, response=response), \
                    patch.object(acceptance, 'last_ok', return_value=timestamp):
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.fresh_checkin(api, 100)
        api.request.return_value = (200, {'ok':True, 'devMode':False})
        with patch.object(acceptance, 'last_ok', return_value=101):
            self.assertEqual(acceptance.fresh_checkin(api, 100), 101)

    def test_unsettled_installer_or_other_run_blocks_privileged_cleanup(self):
        for marker in ({'runId':'12', 'installerSettled':False},
                       {'runId':'99', 'installerSettled':True}):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); (root/'eznest-macos-owned.json').write_text(json.dumps(marker))
                with patch.dict(os.environ, {'GITHUB_RUN_ID':'12'}), \
                        patch.object(acceptance, 'sudo_python') as privileged:
                    with self.assertRaises(acceptance.AcceptanceError):
                        acceptance.cleanup(root)
                    privileged.assert_not_called()

    def test_missing_ownership_never_cleans_an_existing_machine(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(acceptance, 'sudo_python') as privileged:
            acceptance.cleanup(Path(folder))
            privileged.assert_not_called()

    @staticmethod
    def pack(kind='svg', *, pieces=2, complete=True, batch_id='test-batch', artwork=None):
        if artwork is None:
            artwork = (b'<svg xmlns="http://www.w3.org/2000/svg"><g id="ez-part-1"><rect width="20" height="20"/></g>'
                       b'<g id="ez-part-2"><rect width="20" height="20"/></g></svg>')
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as archive:
            archive.writestr('artwork.' + kind, artwork)
            archive.writestr('batch.json', json.dumps({'batchId':batch_id,'complete':complete,
                'totalPieces':pieces,'pieces':[{} for _ in range(pieces)],
                'printFiles':['artwork.' + kind]}))
            archive.writestr('sheet-map.svg', '<svg/>')
            archive.writestr('piece-checklist.csv', 'piece\n1\n2\n')
        return buffer.getvalue()

    def test_pack_rejects_lost_pieces_wrong_batch_and_missing_artwork(self):
        valid = self.pack()
        self.assertEqual(acceptance.validate_export(valid, 'svg', 'test-batch'),
                         hashlib.sha256(valid).hexdigest())
        for content in (self.pack(pieces=1), self.pack(complete=False),
                        self.pack(batch_id='other'), self.pack(artwork=b'<svg/>'),
                        self.pack(artwork=b'<svg xmlns="http://www.w3.org/2000/svg"><g id="ez-part-1"><rect width="20" height="20"/></g></svg>')):
            with self.subTest(content=hashlib.sha256(content).hexdigest()):
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.validate_export(content, 'svg', 'test-batch')
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.validate_export(valid, 'pdf', 'test-batch')

    def test_pdf_pack_rejects_truncated_document_and_lost_cut_spot(self):
        pdf = acceptance.synthetic_pdf()
        content = self.pack(kind='pdf', artwork=pdf)
        acceptance.validate_export(content, 'pdf', 'test-batch')
        for artwork in (pdf[:-20], pdf.replace(b'CutContour_Thru-cut', b'UnrelatedBrandInk')):
            with self.assertRaises(acceptance.AcceptanceError):
                acceptance.validate_export(self.pack(kind='pdf', artwork=artwork), 'pdf', 'test-batch')

    def test_changed_export_or_lost_workspace_cannot_pass_restart(self):
        content = self.pack(); digest = hashlib.sha256(content).hexdigest()
        exports = [{'format':'svg','id':'test-batch','sha256':digest,'bytes':content}]
        api = Mock(); api.request.return_value = (200, {'status':'ready','released':True,
                                                      'id':'test-batch','sha256':digest})
        api.exchange.return_value = (200, content)
        acceptance.verify_persistence(api, exports)
        # Still-valid ZIP with the same manifest but changed art must fail exact-byte persistence.
        api.exchange.return_value = (200, self.pack(artwork=b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<g id="ez-part-1"><rect width="20" height="20"/></g><g id="ez-part-2"><rect width="20" height="20"/></g><text>changed</text></svg>'))
        with self.assertRaisesRegex(acceptance.AcceptanceError, 'changed after'):
            acceptance.verify_persistence(api, exports)
        api.request.return_value = (200, {'status':'idle'})
        with self.assertRaisesRegex(acceptance.AcceptanceError, 'survive restart'):
            acceptance.verify_persistence(api, exports)

    def test_browser_and_local_client_reject_non_loopback_targets(self):
        self.assertTrue(local_browser_url('http://127.0.0.1:8765/web'))
        for url in ('https://output.network/', 'http://127.0.0.1:8765.attacker.test/web',
                    'http://user@127.0.0.1:8765/', 'http://localhost:8765/', 'file:///etc/passwd'):
            self.assertFalse(local_browser_url(url))
        api = acceptance.LocalAPI(); api.http = Mock()
        for path in ('//attacker.test/api', '/api/batch/../session', '/api/batch/x?token=secret'):
            with self.assertRaises(acceptance.AcceptanceError):
                api.exchange(path)
        api.http.open.assert_not_called()

    def test_preview_rejects_updates_lan_or_wildcard_listener(self):
        api = Mock()
        for shop in ({'updates':True,'lan':False}, {'updates':False,'lan':True}):
            api.request.return_value = (200, shop)
            with patch.object(acceptance, 'command') as command:
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.preview_settings(api)
                command.assert_not_called()
        api.request.return_value = (200, {'updates':False,'lan':False})
        with patch.object(acceptance, 'job_pid', return_value=123), \
                patch.object(acceptance, 'command', return_value=Mock(stdout='p123\nn*:8765\n')):
            with self.assertRaisesRegex(acceptance.AcceptanceError, 'loopback'):
                acceptance.preview_settings(api)

    def test_incomplete_connection_never_polls_production(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'eznest-macos-acceptance.json').write_text(json.dumps(
                dict(paired=True, restarted=False, nested=False, sharingOff=False)))
            with patch.object(acceptance, 'LocalAPI') as api:
                with self.assertRaisesRegex(acceptance.AcceptanceError, 'incomplete'):
                    acceptance.verify_revoked(root)
                api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
