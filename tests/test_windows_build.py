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
