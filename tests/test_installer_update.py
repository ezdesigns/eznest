"""The shop installer keeps settings and the hot folder, and restores a build that does not start."""
import hashlib
import json
import os
import tempfile
import textwrap
import time
import unittest
import zipfile
from unittest.mock import Mock, patch
from io import BytesIO
from pathlib import Path

import installer_update

OK = textwrap.dedent('''
import json, os, sys, time
from pathlib import Path
data = Path(os.environ["EZ_NEST_DATA"])
if "--update-confirm" in sys.argv:
    applying = json.loads((data / "updates" / "applying.json").read_text(encoding="utf-8"))
    (data / "updates" / "healthy.json").write_text(json.dumps({"version": applying["version"], "pid": os.getpid()}), encoding="utf-8")
time.sleep(1)
raise SystemExit(0)
''')
FAIL = 'import sys\nraise SystemExit(1)\n'


class InstallerUpdateTests(unittest.TestCase):
    def tearDown(self):
        installer_update.reap_left_running()

    def settle(self):
        """Let a stub launcher exit before the temp directory disappears."""
        installer_update.reap_left_running()
        if os.name == 'nt':
            return
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                time.sleep(0.05)

    def install(self, root, version, stub):
        root.mkdir()
        (root / 'version.json').write_text(json.dumps({'version': version}), encoding='utf-8')
        (root / 'eznest.py').write_text(stub, encoding='utf-8')

    def settings(self, data):
        data.mkdir()
        shop = {'onyxPc': True, 'lan': True}
        folder = {'path': r'D:\EZ\hot', 'configured': True}
        (data / 'shop.json').write_text(json.dumps(shop), encoding='utf-8')
        (data / 'output-folder.json').write_text(json.dumps(folder), encoding='utf-8')
        return shop, folder

    def stage(self, data, version, payload, name):
        return installer_update.stage_file(data, version, hashlib.sha256(payload).hexdigest(), payload, name)

    def test_setup_keeps_settings_when_the_new_build_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'app', root / 'data'
            self.install(install, '1.0.0-rc.1', 'raise SystemExit(0)\n')
            shop, folder = self.settings(data)
            payload = b'MZ-new'
            self.stage(data, '1.0.0-rc.2', payload, 'eznest-setup.exe')

            def runner(setup, install_root, data_dir):
                self.assertEqual(setup.read_bytes(), payload)
                (data_dir / 'shop.json').write_text('{"onyxPc": false, "lan": false}', encoding='utf-8')
                (data_dir / 'output-folder.json').write_text(json.dumps({'path': r'C:\ONYX\EPSON SureColor S80600 ONYX Input', 'configured': True}), encoding='utf-8')
                (install_root / 'version.json').write_text(json.dumps({'version': '1.0.0-rc.2'}), encoding='utf-8')
                (install_root / 'eznest.py').write_text(OK, encoding='utf-8')

            result = installer_update.apply_and_confirm(install, data, timeout=5, runner=runner)
            self.assertTrue(result['ok'])
            self.assertEqual(json.loads((install / 'version.json').read_text(encoding='utf-8'))['version'], '1.0.0-rc.2')
            self.assertEqual(json.loads((data / 'shop.json').read_text(encoding='utf-8')), shop)
            self.assertEqual(json.loads((data / 'output-folder.json').read_text(encoding='utf-8')), folder)
            self.settle()

    def test_failed_start_restores_the_app_and_the_hot_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'app', root / 'data'
            self.install(install, '1.0.0-rc.1', 'raise SystemExit(0)\n')
            shop, folder = self.settings(data)
            self.stage(data, '1.0.0-rc.2', b'MZ-bad', 'eznest-setup.exe')

            def runner(setup, install_root, data_dir):
                (data_dir / 'shop.json').write_text('{"onyxPc": false, "lan": false}', encoding='utf-8')
                (data_dir / 'output-folder.json').write_text('{"path": "", "configured": false}', encoding='utf-8')
                (install_root / 'version.json').write_text(json.dumps({'version': '1.0.0-rc.2'}), encoding='utf-8')
                (install_root / 'eznest.py').write_text(FAIL, encoding='utf-8')

            result = installer_update.apply_and_confirm(install, data, timeout=3, runner=runner)
            self.assertFalse(result['ok'])
            self.assertEqual(result['restored'], '1.0.0-rc.1')
            self.assertEqual(json.loads((install / 'version.json').read_text(encoding='utf-8'))['version'], '1.0.0-rc.1')
            self.assertEqual((install / 'eznest.py').read_text(encoding='utf-8'), 'raise SystemExit(0)\n')
            self.assertEqual(json.loads((data / 'shop.json').read_text(encoding='utf-8')), shop)
            self.assertEqual(json.loads((data / 'output-folder.json').read_text(encoding='utf-8')), folder)
            self.assertIn('hot folder', (data / 'updates' / 'rollback.json').read_text(encoding='utf-8'))
            self.settle()

    def test_zip_replaces_app_files_and_keeps_the_hot_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'app', root / 'data'
            self.install(install, '1.0.0-rc.1', 'raise SystemExit(0)\n')
            shop, folder = self.settings(data)
            buffer = BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.writestr('version.json', json.dumps({'version': '1.0.0-rc.2'}))
                archive.writestr('eznest.py', OK)
            self.stage(data, '1.0.0-rc.2', buffer.getvalue(), 'eznest-windows.zip')
            result = installer_update.apply_and_confirm(install, data, timeout=5)
            self.assertTrue(result['ok'])
            self.assertEqual(json.loads((data / 'shop.json').read_text(encoding='utf-8')), shop)
            self.assertEqual(json.loads((data / 'output-folder.json').read_text(encoding='utf-8')), folder)
            self.settle()

    def test_health_marker_requires_the_expected_live_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'healthy.json'
            child = Mock(pid=42)
            installer_update.write_json(path, {'version': 'new', 'pid': 42})
            child.poll.return_value = 1
            self.assertFalse(installer_update._wait_healthy(path, child, 'new', .05))
            child.poll.return_value = None
            installer_update.write_json(path, {'version': 'new', 'pid': 99})
            self.assertFalse(installer_update._wait_healthy(path, child, 'new', .05))
            installer_update.write_json(path, {'version': 'new', 'pid': 42})
            self.assertTrue(installer_update._wait_healthy(path, child, 'new', .05))

    def test_early_health_marker_does_not_prevent_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'app', root / 'data'
            self.install(install, 'old', 'raise SystemExit(0)\n')
            self.settings(data)
            self.stage(data, 'new', b'MZ-bad', 'eznest-setup.exe')
            def runner(setup, install_root, data_dir):
                (install_root / 'version.json').write_text(json.dumps({'version': 'new'}))
                # A child that reports healthy and then fails before serving.
                (install_root / 'eznest.py').write_text(OK.replace('time.sleep(1)', '').replace('SystemExit(0)', 'SystemExit(1)'))
            result = installer_update.apply_and_confirm(install, data, timeout=1, runner=runner)
            self.assertFalse(result['ok'])
            self.assertEqual(result['restored'], 'old')
            self.assertEqual(installer_update.read_version(install), 'old')
            self.settle()

    def test_partial_backup_never_replaces_intact_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'app', root / 'data'
            self.install(install, 'old', 'raise SystemExit(0)\n')
            (install / 'critical.dll').write_bytes(b'original library')
            self.settings(data)
            self.stage(data, 'new', b'MZ-new', 'eznest-setup.exe')
            before = {p.name: p.read_bytes() for p in install.iterdir()}
            copy_entry = installer_update._copy_entry
            calls = []
            def fail_second(source, destination):
                calls.append(source)
                if len(calls) == 2:
                    raise OSError('backup disk full')
                return copy_entry(source, destination)
            with patch.object(installer_update, '_copy_entry', side_effect=fail_second), \
                 patch.object(installer_update, 'run_setup') as setup, \
                 patch.object(installer_update, 'launch', wraps=installer_update.launch) as launch:
                with self.assertRaisesRegex(OSError, 'backup disk full'):
                    installer_update.apply_and_confirm(install, data)
                setup.assert_not_called()
                launch.assert_called_once_with(install / 'eznest.py', data, False)
            self.assertFalse(installer_update.pending_state(data)['applyOnRestart'])
            self.assertFalse(installer_update.handoff_if_pending(install, data))
            self.settle()
            self.assertEqual({p.name: p.read_bytes() for p in install.iterdir()}, before)
            self.assertIsNotNone(installer_update.pending_state(data))

    def test_failed_install_restarts_old_app_without_automatic_retry(self):
        for failure in ('installer error', 'missing executable'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                install, data = root / 'app', root / 'data'
                self.install(install, 'old', 'raise SystemExit(0)\n')
                shop, folder = self.settings(data)
                self.stage(data, 'new', b'MZ-new', 'eznest-setup.exe')
                def runner(setup, install_root, data_dir):
                    (install_root / 'version.json').write_text(json.dumps({'version': 'new'}))
                    (install_root / 'eznest.py').unlink()
                    (data_dir / 'shop.json').write_text('{}')
                    if failure == 'installer error':
                        raise OSError('installer denied')
                with patch.object(installer_update, 'launch', wraps=installer_update.launch) as launch:
                    with self.assertRaises((OSError, ValueError)):
                        installer_update.apply_and_confirm(install, data, runner=runner)
                    launch.assert_called_once_with(install / 'eznest.py', data, False)
                self.assertEqual(installer_update.read_version(install), 'old')
                self.assertEqual(json.loads((data / 'shop.json').read_text()), shop)
                self.assertEqual(json.loads((data / 'output-folder.json').read_text()), folder)
                pending = installer_update.pending_state(data)
                self.assertIsNotNone(pending)
                self.assertFalse(pending['applyOnRestart'])
                self.assertFalse(installer_update.handoff_if_pending(install, data))
                self.settle()

    def test_launch_error_restores_previous_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'app', root / 'data'
            self.install(install, 'old', 'raise SystemExit(0)\n')
            self.settings(data)
            self.stage(data, 'new', b'MZ-new', 'eznest-setup.exe')
            original_launch = installer_update.launch
            def launch(exe, data_dir, confirm):
                if confirm:
                    raise OSError('bad executable format')
                return original_launch(exe, data_dir, confirm)
            def runner(setup, install_root, data_dir):
                (install_root / 'version.json').write_text(json.dumps({'version': 'new'}))
                (install_root / 'eznest.py').write_text('invalid executable')
            with patch.object(installer_update, 'launch', side_effect=launch):
                result = installer_update.apply_and_confirm(install, data, runner=runner)
            self.assertFalse(result['ok'])
            self.assertEqual(installer_update.read_version(install), 'old')
            self.assertEqual((install / 'eznest.py').read_text(), 'raise SystemExit(0)\n')
            self.assertTrue((data / 'updates' / 'rollback.json').is_file())
            self.settle()

    def test_protected_install_does_not_shutdown_for_pending_update(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, data = root / 'ProgramFiles' / 'app', root / 'data'
            install.parent.mkdir()
            self.install(install, 'old', 'raise SystemExit(0)\n')
            self.settings(data)
            self.stage(data, 'new', b'MZ-new', 'eznest-setup.exe')
            windows = SimpleNamespace(name='nt', environ={'ProgramFiles': str(install.parent)})
            with patch.object(installer_update, 'os', windows), \
                 patch.object(installer_update, 'spawn_helper') as spawn:
                self.assertFalse(installer_update.apply_supported(install))
                self.assertFalse(installer_update.handoff_if_pending(install, data))
                self.assertFalse(installer_update.local_state(data, install)['applyOnRestart'])
                spawn.assert_not_called()

    def test_zip_slip_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / 'bad.zip'
            with zipfile.ZipFile(bad, 'w') as archive:
                archive.writestr('../eznest.py', 'print("no")\n')
            with self.assertRaisesRegex(ValueError, 'unsafe path'):
                installer_update.safe_extract(bad, root / 'out')


if __name__ == '__main__':
    unittest.main()

