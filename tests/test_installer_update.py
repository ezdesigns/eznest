"""The shop installer keeps settings and the hot folder, and restores a build that does not start."""
import hashlib
import json
import os
import tempfile
import textwrap
import time
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

import installer_update

OK = textwrap.dedent('''
import json, os, sys
from pathlib import Path
data = Path(os.environ["EZ_NEST_DATA"])
if "--update-confirm" in sys.argv:
    applying = json.loads((data / "updates" / "applying.json").read_text(encoding="utf-8"))
    (data / "updates" / "healthy.json").write_text(json.dumps({"version": applying["version"]}), encoding="utf-8")
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

