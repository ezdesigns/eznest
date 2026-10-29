"""Installer build guards that can run outside Windows."""
import opt_out
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import importlib.metadata as metadata

import build_windows


class WindowsBuildGuardTests(unittest.TestCase):
    def test_inno_setup_must_know_exec_and_log_output(self):
        self.assertTrue(build_windows.iscc_supported(None))
        self.assertTrue(build_windows.iscc_supported((6, 3)))
        self.assertTrue(build_windows.iscc_supported((6, 7, 3)))
        self.assertFalse(build_windows.iscc_supported((6, 2, 2)))
        self.assertFalse(build_windows.iscc_supported((5, 6, 1)))

    def test_build_directory_rejects_spaces_and_the_source_tree(self):
        with self.assertRaises(ValueError):
            build_windows.check_build_directory(Path('/tmp/ez nest build'))
        with self.assertRaises(ValueError):
            build_windows.check_build_directory(build_windows.ROOT)

    def test_newer_installed_compiler_beats_an_older_one_on_path(self):
        def is_file(self):
            return 'ISCC.exe' in str(self)

        def version(path):
            text = str(path)
            if 'old-iscc' in text:
                return (6, 2, 0, 0)
            if 'Inno Setup 6' in text:
                return (6, 7, 3, 0)
            return (6, 0, 0, 0)

        with patch.object(Path, 'is_file', is_file), \
             patch('build_windows.iscc_file_version', side_effect=version), \
             patch('build_windows.shutil.which', return_value=r'C:\old-iscc\ISCC.exe'), \
             patch.dict(os.environ, {'ProgramFiles(x86)': r'C:\Program Files (x86)', 'ProgramFiles': r'C:\Program Files'}):
            chosen, found = build_windows.find_iscc()
        self.assertIn('Inno Setup 6', chosen)
        self.assertEqual(found[:3], (6, 7, 3))

    def test_only_an_old_compiler_is_a_clear_error(self):
        def is_file(self):
            return 'old-iscc' in str(self)

        with patch.object(Path, 'is_file', is_file), \
             patch('build_windows.iscc_file_version', return_value=(6, 2, 2, 0)), \
             patch('build_windows.shutil.which', return_value=r'C:\old-iscc\ISCC.exe'), \
             patch.dict(os.environ, {'ProgramFiles(x86)': r'C:\missing', 'ProgramFiles': r'C:\missing'}):
            with self.assertRaises(RuntimeError) as caught:
                build_windows.find_iscc()
        self.assertIn('6.3', str(caught.exception))
        self.assertIn('6.7.3', str(caught.exception))
        self.assertIn('ExecAndLogOutput', str(caught.exception))

    def test_missing_compiler_leaves_the_portable_choice_open(self):
        with patch.object(Path, 'is_file', lambda self: False), patch('build_windows.shutil.which', return_value=None):
            self.assertIsNone(build_windows.find_iscc())

    def test_compiler_text_names_the_engine_version(self):
        banner = 'Inno Setup 6 Command-Line Compiler\nCopyright (C) 1997-2026 Jordan Russell.\n'
        self.assertEqual(build_windows.parse_iscc_version_text(banner), (6,))
        self.assertEqual(build_windows.parse_iscc_version_text(banner + 'Compiler engine version: Inno Setup 6.7.3\n'), (6, 7, 3))
        self.assertEqual(build_windows.parse_iscc_version_text('Inno Setup 6.2.2'), (6, 2, 2))
        self.assertIsNone(build_windows.parse_iscc_version_text(''))
        self.assertIsNone(build_windows._usable_version((0, 0, 0, 0)))

    def test_unstamped_file_version_uses_product_version(self):
        def is_file(self):
            return str(self).endswith('ISCC.exe')

        with patch.object(Path, 'is_file', is_file), \
             patch('build_windows.iscc_file_version', return_value=(0, 0, 0, 0)), \
             patch('build_windows.iscc_product_version', return_value=(6, 7, 3, 0)), \
             patch('build_windows.iscc_reported_version', side_effect=AssertionError('help text is the later fallback')), \
             patch('build_windows.shutil.which', return_value=None), \
             patch.dict(os.environ, {'ProgramFiles(x86)': r'C:\Program Files (x86)', 'ProgramFiles': r'C:\missing', 'EZ_NEST_ISCC': ''}, clear=False):
            chosen, found = build_windows.find_iscc()
        self.assertIn('Inno Setup 6', chosen)
        self.assertEqual(found[:3], (6, 7, 3))

    def test_unstamped_compiler_uses_reported_version_and_prefers_673(self):
        def is_file(self):
            return str(self).endswith('ISCC.exe')

        def reported(path):
            text = str(path)
            if 'Inno Setup 6.7.3' in text:
                return (6, 7, 3)
            if 'Inno Setup 6' in text:
                return (6, 7, 1)
            return (6, 2, 2)

        with patch.object(Path, 'is_file', is_file), \
             patch('build_windows.iscc_file_version', return_value=(0, 0, 0, 0)), \
             patch('build_windows.iscc_product_version', return_value=None), \
             patch('build_windows.iscc_reported_version', side_effect=reported), \
             patch('build_windows.shutil.which', return_value=r'C:\old-iscc\ISCC.exe'), \
             patch.dict(os.environ, {'ProgramFiles(x86)': r'C:\Program Files (x86)', 'ProgramFiles': r'C:\missing', 'EZ_NEST_ISCC': ''}, clear=False):
            chosen, found = build_windows.find_iscc()
        self.assertIn('Inno Setup 6.7.3', chosen)
        self.assertEqual(found, (6, 7, 3))

    def test_banner_major_is_not_treated_as_older_than_63(self):
        def is_file(self):
            return str(self).endswith('ISCC.exe') and 'missing' not in str(self)

        with patch.object(Path, 'is_file', is_file), \
             patch('build_windows.iscc_file_version', return_value=(0, 0, 0, 0)), \
             patch('build_windows.iscc_product_version', return_value=None), \
             patch('build_windows.iscc_reported_version', return_value=(6,)), \
             patch('build_windows.shutil.which', return_value=None), \
             patch.dict(os.environ, {'ProgramFiles(x86)': r'C:\Program Files (x86)', 'ProgramFiles': r'C:\missing', 'EZ_NEST_ISCC': ''}, clear=False):
            chosen, found = build_windows.find_iscc()
        self.assertTrue(chosen.endswith('ISCC.exe'))
        self.assertEqual(found, (6,))

    def test_workflow_install_fails_unless_673_is_present(self):
        workflow = (build_windows.ROOT / '.github' / 'workflows' / 'windows-installer.yml').read_text(encoding='utf-8')
        install, _rest = workflow.split('- name: Build the shop installer', 1)
        self.assertIn('https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe', install)
        self.assertIn('ExitCode', install)
        self.assertIn('Inno Setup 6.7.3 is not present after install', install)
        self.assertIn('EZ_NEST_ISCC', install)
        upload, acceptance = workflow.split('- name: Test actual fresh install', 1)
        self.assertIn('actions/upload-artifact@v4', upload)
        self.assertIn('installer/Output/eznest-setup.exe.sha256', upload)
        self.assertIn('if: success()', upload)
        self.assertNotIn('- name: Test actual fresh install', upload)
        shop = (build_windows.ROOT / 'tests' / 'test_installed_shop.ps1').read_text(encoding='utf-8')
        lockdown = (build_windows.ROOT / 'installer' / 'install-shop.ps1').read_text(encoding='utf-8')
        self.assertIn("UserId 'SYSTEM'", shop)
        self.assertNotIn("Get-Content -LiteralPath (Join-Path $data 'shop.json')", shop)
        self.assertIn('SYSTEM:(OI)(CI)F', lockdown)
        self.assertIn('Administrators:(OI)(CI)F', lockdown)
        self.assertIn('${Account}:(OI)(CI)M', lockdown)

    def test_missing_pin_names_the_requirements_files(self):
        def missing(_name):
            raise metadata.PackageNotFoundError('pyinstaller')
        with patch('build_windows.metadata.version', side_effect=missing):
            with self.assertRaises(RuntimeError) as caught:
                build_windows.pinned_distribution('pyinstaller', '6.22.3')
        self.assertIn('requirements-build.txt', str(caught.exception))
        self.assertIn('pyinstaller==6.22.3', str(caught.exception))

    def test_installer_script_still_requires_the_version_from_version_json(self):
        script = (build_windows.ROOT / 'installer' / 'eznest.iss').read_text(encoding='utf-8')
        install = (build_windows.ROOT / 'installer' / 'install-shop.ps1').read_text(encoding='utf-8')
        self.assertIn('ExecAndLogOutput', script)
        self.assertIn('6.3', script)
        self.assertIn('eznest-svc', install)
        self.assertIn('-RunLevel Limited', install)
        self.assertIn('SeBatchLogonRight', install)
        self.assertNotIn('/RU SYSTEM', install)
        self.assertIn('Log on as a batch job', install)


if __name__ == '__main__':
    unittest.main()
