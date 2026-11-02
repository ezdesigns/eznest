"""Native window packaging and authority boundaries; Apple SDK runtime runs in Mac CI."""
import opt_out
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

import build_macos
import build_macos_desktop


class DesktopBuildTests(unittest.TestCase):
    def test_unsupported_host_or_existing_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'native'
            with patch('build_macos_desktop.sys.platform', 'win32'):
                with self.assertRaises(ValueError):
                    build_macos_desktop.build(out, 'arm64')
            self.assertFalse(out.exists())
            out.mkdir(); (out / 'keep').write_text('preserve')
            with patch('build_macos_desktop.sys.platform', 'darwin'):
                with self.assertRaises(ValueError):
                    build_macos_desktop.build(out, 'arm64')
            self.assertEqual((out / 'keep').read_text(), 'preserve')

    def test_native_entry_is_signed_before_resealing_bundle_and_backend_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            app = out / 'eznest.app'
            (app / 'Contents/MacOS').mkdir(parents=True)
            backend = app / 'Contents/MacOS/eznest'
            backend.write_bytes(b'synthetic backend')
            info = app / 'Contents/Info.plist'
            info.write_bytes(plistlib.dumps({'CFBundleExecutable': 'eznest', 'EzNestShopService': True,
                                            'EzNestVersion': '1.0.0-rc.6', 'LSUIElement': True}))
            native = out / 'test-native'; native.write_bytes(b'synthetic native'); native.chmod(0o755)
            with patch('build_macos_desktop.build', return_value=native), \
                 patch('build_macos.subprocess.run') as run:
                build_macos.add_desktop_client(app, out, 'arm64', 'Developer ID Application: Synthetic (TESTTEAM01)')
            result = plistlib.loads(info.read_bytes())
            self.assertEqual(result['CFBundleExecutable'], 'eznest-desktop')
            self.assertEqual(result['CFBundleDisplayName'], 'EZNest')
            self.assertIs(result['LSUIElement'], False)
            self.assertIs(result['EzNestShopService'], True)
            self.assertEqual(backend.read_bytes(), b'synthetic backend')
            self.assertEqual((app / 'Contents/MacOS/eznest-desktop').read_bytes(), b'synthetic native')
            self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                             [str(backend), str(app / 'Contents/MacOS/eznest-desktop'), str(app)])

    def test_native_source_changes_invalidate_build_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'native/macos').mkdir(parents=True)
            for name in set(build_macos.STATIC) | set(build_macos.DOCUMENTS):
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('synthetic')
            swift = root / 'native/macos/EZNestDesktop.swift'
            swift.write_text('first native build')
            before = build_macos.source_fingerprint(root)
            swift.write_text('second native build')
            self.assertNotEqual(build_macos.source_fingerprint(root), before)
