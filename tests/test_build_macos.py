"""macOS packaging guards and resource assembly, without building or signing."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import build_macos
import installer_update
import shop_deploy


class MacPackagingTests(unittest.TestCase):
    def test_direct_mac_helper_refuses_even_an_existing_executable(self):
        with tempfile.TemporaryDirectory() as tmp, patch('installer_update.sys.platform', 'darwin'):
            root = Path(tmp)
            (root / 'eznest').write_text('synthetic executable')
            self.assertFalse(installer_update.apply_supported(root))
            with patch('installer_update.launch', side_effect=AssertionError('must not launch')):
                with self.assertRaises(ValueError):
                    installer_update.begin_apply(root, root)

    def test_source_mac_does_not_read_release_credentials_or_contact_github(self):
        with tempfile.TemporaryDirectory() as tmp, patch('shop_deploy.sys.platform', 'darwin'), \
             patch.dict('os.environ', {'EZ_NEST_UPDATES': '1', 'EZ_NEST_GITHUB_TOKEN': 'synthetic-only'}), \
             patch('shop_deploy.github_token', side_effect=AssertionError('credential read')), \
             patch('shop_deploy._open', side_effect=AssertionError('network')):
            root = Path(tmp)
            for when in ('now', 'restart'):
                result = shop_deploy.pull_latest(root, '1.0.0-rc.5', when=when)
                self.assertFalse(result['updated'])
                self.assertFalse(result['staged'])
                self.assertFalse(result['applyOnRestart'])
                self.assertFalse(result['applySupported'])
                self.assertIn('manually', result['message'])
            result = shop_deploy.peek_latest(root, '1.0.0-rc.5')
            self.assertFalse(result['updateAvailable'])
            self.assertIsNone(result['latest'])
            self.assertIn('manually', result['message'])
            self.assertFalse((root / 'updates').exists())

    def test_only_app_bundles_use_writable_user_data(self):
        with patch('shop_deploy.sys.platform', 'darwin'), patch('shop_deploy.Path.home', return_value=Path('/Users/test')):
            expected = Path('/Users/test/Library/Application Support/eznest')
            for app in ('/Applications/eznest.app', '/private/translocated/eznest.app'):
                self.assertEqual(shop_deploy.data_directory(app + '/Contents/MacOS', frozen=True), expected)
            self.assertEqual(shop_deploy.data_directory('/Applications/eznest.app/Contents/MacOS', '/tmp/trial', frozen=True), Path('/tmp/trial'))
            self.assertEqual(shop_deploy.data_directory('/tmp/source'), Path('/tmp/source/.local'))
            self.assertEqual(shop_deploy.data_directory('/tmp/portable', frozen=True), Path('/tmp/portable/data'))
        with patch('shop_deploy.sys.platform', 'win32'):
            self.assertEqual(shop_deploy.data_directory('/tmp/Program Files/eznest', frozen=True,
                             program_files='/tmp/Program Files', program_data='/tmp/ProgramData'), Path('/tmp/ProgramData/eznest'))

    def test_preflight_rejects_wrong_host_or_interpreter_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'build'
            for platform, version, pointer_size in [('win32', (3, 12), 8), ('darwin', (3, 13), 8), ('darwin', (3, 12), 4)]:
                with self.subTest(platform=platform, version=version, pointer_size=pointer_size), \
                     patch('build_macos.sys.platform', platform), patch('build_macos.sys.version_info', version), \
                     patch('build_macos.struct.calcsize', return_value=pointer_size):
                    with self.assertRaisesRegex(RuntimeError, 'Python 3.12 on macOS'):
                        build_macos.preflight(out)
            self.assertFalse(out.exists())

    def test_preflight_preserves_existing_and_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp, patch('build_macos.sys.platform', 'darwin'), \
             patch('build_macos.sys.version_info', (3, 12)), patch('build_macos.platform.machine', return_value='arm64'):
            root = Path(tmp) / 'source'
            root.mkdir()
            (root / 'keep.txt').write_text('preserve')
            for out in (root, root / 'out', root.parent):
                with self.assertRaises(ValueError):
                    build_macos.preflight(out, root=root)
            existing = Path(tmp) / 'existing'
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                build_macos.preflight(existing, root=root)
            self.assertEqual((root / 'keep.txt').read_text(), 'preserve')

    def test_pins_are_loaded_from_existing_requirements_and_mismatch_fails(self):
        pins = build_macos.pinned_requirements(build_macos.ROOT)
        self.assertEqual(set(pins), set(build_macos.PACKAGES))
        with tempfile.TemporaryDirectory() as tmp, patch('build_macos.sys.platform', 'darwin'), \
             patch('build_macos.sys.version_info', (3, 12)), patch('build_macos.platform.machine', return_value='arm64'), \
             patch('build_macos.metadata.version', side_effect=lambda name: pins[name]):
            out, arch = build_macos.preflight(Path(tmp) / 'build')
            self.assertEqual(arch, 'arm64')
            self.assertFalse(out.exists())
            with patch('build_macos.metadata.version', return_value='0'):
                with self.assertRaisesRegex(RuntimeError, 'pinned requirement'):
                    build_macos.preflight(out)
            with patch('build_macos.platform.machine', return_value='i386'):
                with self.assertRaisesRegex(RuntimeError, 'arm64 or x86_64'):
                    build_macos.preflight(out)

    def test_generated_spec_assembles_resources_before_bundle_signing(self):
        root, out = build_macos.ROOT, Path('/tmp/new build')
        version = json.loads((root / 'version.json').read_text())['version']
        spec = build_macos.bundle_spec(root, out, 'arm64', version)
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_all = Mock(return_value=([], [], []))
        hooks.copy_metadata = Mock(return_value=[])
        analysis = Mock(pure=[], scripts=[], binaries=[], datas=[])
        namespace = {'Analysis': Mock(return_value=analysis), 'PYZ': Mock(),
                     'EXE': Mock(), 'COLLECT': Mock(), 'BUNDLE': Mock()}
        with patch.dict(sys.modules, {'PyInstaller.utils.hooks': hooks}):
            exec(compile(spec, '<generated spec>', 'exec'), namespace)
        options = namespace['Analysis'].call_args.kwargs
        inputs = dict(options['datas'])
        for name in set(build_macos.STATIC + list(build_macos.DOCUMENTS)):
            self.assertEqual(inputs[str(root / name)], '.')
            self.assertTrue((root / name).is_file(), name)
        self.assertEqual(inputs[str(root / 'fonts')], 'fonts')
        self.assertEqual(inputs[str(out / 'licenses')], 'licenses')
        self.assertEqual(inputs[str(out / 'BUILD.json')], '.')
        self.assertEqual(namespace['EXE'].call_args.kwargs['target_arch'], 'arm64')
        self.assertIsNone(namespace['EXE'].call_args.kwargs['codesign_identity'])
        plist = namespace['BUNDLE'].call_args.kwargs['info_plist']
        self.assertEqual(plist['EzNestVersion'], version)
        self.assertEqual(plist['CFBundleShortVersionString'], version.split('-', 1)[0])
        self.assertNotIn('WINDOWS_CERT', spec)
        self.assertNotIn(str(root / '.local'), spec)

    def test_entry_keeps_workers_exact_and_disables_windows_updater(self):
        for args in [[], ['--no-browser'], ['--nest-worker', 'in', 'out'], ['--document-worker', 'input', 'out'], ['--telemetry-worker']]:
            with self.subTest(args=args), patch.object(sys, 'argv', ['eznest', *args]), \
                 patch.dict('os.environ', {'EZ_NEST_UPDATES': '1'}):
                called = []
                launcher = types.ModuleType('launcher')
                launcher.main = lambda: called.append((list(sys.argv), __import__('os').environ['EZ_NEST_UPDATES'])) or 0
                with patch.dict(sys.modules, {'launcher': launcher}), self.assertRaises(SystemExit) as result:
                    exec(compile(build_macos.ENTRY, '<mac entry>', 'exec'), {})
                self.assertEqual(result.exception.code, 0)
                expected = ['eznest', *args]
                if not args or args[0] not in ('--nest-worker', '--document-worker', '--telemetry-worker'):
                    expected.append('--web')
                self.assertEqual(called, [(expected, '0')])
        for flag in ('--apply-update', '--request-shop-update', '--update-confirm'):
            with patch.object(sys, 'argv', ['eznest', flag]), patch.dict('os.environ', {}), self.assertRaisesRegex(SystemExit, 'manual application replacement'):
                exec(compile(build_macos.ENTRY, '<mac entry>', 'exec'), {})

    def test_license_inventory_includes_python_and_dependency_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            (root / 'licenses').mkdir(parents=True)
            (root / 'licenses' / 'Repo.txt').write_text('repository license')
            python = Path(tmp) / 'python'
            python.mkdir()
            (python / 'LICENSE.txt').write_text('Python license')
            dep = Path(tmp) / 'dependency'
            (dep / 'package.dist-info' / 'licenses').mkdir(parents=True)
            license_path = Path('package.dist-info/licenses/LICENSE')
            (dep / license_path).write_text('dependency license')
            (dep / 'private.txt').write_text('not a license')
            distribution = Mock(files=[license_path, Path('private.txt')])
            distribution.locate_file.side_effect = lambda entry: dep / entry
            with patch('build_macos.ROOT', root), patch('build_macos.sys.base_prefix', str(python)), \
                 patch('build_macos.metadata.distribution', return_value=distribution):
                build_macos.collect_licenses(Path(tmp) / 'licenses')
            self.assertEqual((Path(tmp) / 'licenses' / 'Python-LICENSE.txt').read_text(), 'Python license')
            for name in build_macos.PACKAGES:
                self.assertTrue((Path(tmp) / 'licenses' / name / license_path).is_file())
                self.assertFalse((Path(tmp) / 'licenses' / name / 'private.txt').exists())

    def test_build_keeps_bundle_intact_and_hashes_actual_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'build'
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if 'PyInstaller' in command:
                    exe = out / 'dist/eznest.app/Contents/MacOS/eznest'
                    exe.parent.mkdir(parents=True)
                    exe.write_bytes(b'fake build, not a runtime test')
                elif command[0] == '/usr/bin/ditto':
                    Path(command[-1]).write_bytes(b'fake archive')

            with patch('build_macos.preflight', return_value=(out, 'arm64')), \
                 patch('build_macos.collect_licenses'), patch('build_macos.metadata.version', return_value='test'), \
                 patch('build_macos.subprocess.check_output', return_value='a' * 40), patch('build_macos.subprocess.run', side_effect=run):
                archive = build_macos.build(out)
            self.assertEqual(commands[1][0:4], ['/usr/bin/codesign', '--verify', '--deep', '--strict'])
            self.assertEqual(commands[2][0], '/usr/bin/ditto')
            self.assertIn('--keepParent', commands[2])
            expected = hashlib.sha256(b'fake archive').hexdigest()
            self.assertEqual(archive.with_suffix('.zip.sha256').read_text(), f'{expected}  {archive.name}\n')
            manifest = json.loads((out / 'BUILD.json').read_text())
            self.assertFalse(manifest['notarized'])
            self.assertFalse(manifest['automaticUpdates'])
            self.assertEqual(manifest['architecture'], 'arm64')


if __name__ == '__main__':
    unittest.main()
