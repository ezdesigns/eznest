"""Failure boundaries for the optional Developer ID build path."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_macos

IDENTITY = 'Developer ID Application: Example Publisher (ABCDEFGHIJ)'
DETAILS = ('Authority=Developer ID Application: Example Publisher (ABCDEFGHIJ)\n'
           'TeamIdentifier=ABCDEFGHIJ\nCodeDirectory flags=0x10000(runtime)\n')


class SigningTests(unittest.TestCase):
    def test_only_developer_id_application_identity_is_accepted(self):
        self.assertIsNone(build_macos.signing_team(None))
        self.assertEqual(build_macos.signing_team(IDENTITY), 'ABCDEFGHIJ')
        for identity in ('-', 'Apple Development: Example (ABCDEFGHIJ)',
                         'Developer ID Installer: Example (ABCDEFGHIJ)',
                         'Developer ID Application: Example (bad)', IDENTITY + '\n'):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                build_macos.signing_team(identity)

    def test_spec_passes_identity_without_relaxing_entitlements(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = build_macos.bundle_spec(build_macos.ROOT, Path(tmp), 'arm64',
                                          '1.0.0-rc.5', codesign_identity=IDENTITY)
        self.assertIn(f'codesign_identity={IDENTITY!r}', spec)
        self.assertIn('entitlements_file=None', spec)
        compile(spec, '<spec>', 'exec')

    def test_signature_requires_expected_team_and_hardened_runtime(self):
        for details in (DETAILS.replace('ABCDEFGHIJ', 'KLMNOPQRST'),
                        DETAILS.replace('flags=0x10000(runtime)', 'flags=0x0(none)'),
                        DETAILS.replace('Developer ID Application:', 'Apple Development:'),
                        DETAILS + 'TeamIdentifier=KLMNOPQRST\n'):
            with self.subTest(details=details), patch('build_macos.subprocess.check_output', return_value=details), \
                    patch('build_macos.subprocess.run') as run, self.assertRaises(RuntimeError):
                build_macos.verify_signature('/candidate/eznest.app', 'ABCDEFGHIJ')
            run.assert_not_called()

    def test_valid_identity_still_requires_deep_signature_verification(self):
        with patch('build_macos.subprocess.check_output', return_value=DETAILS), \
                patch('build_macos.subprocess.run') as run:
            build_macos.verify_signature('/candidate/eznest.app', 'ABCDEFGHIJ')
            args = run.call_args.args[0]
            self.assertIn('--all-architectures', args)
            self.assertIn('--deep', args)
            self.assertIn('-R=anchor apple generic and certificate leaf[subject.OU] = "ABCDEFGHIJ"', args)
            self.assertTrue(run.call_args.kwargs['check'])
            run.side_effect = subprocess.CalledProcessError(1, 'codesign')
            with self.assertRaises(subprocess.CalledProcessError):
                build_macos.verify_signature('/candidate/eznest.app', 'ABCDEFGHIJ')


if __name__ == '__main__':
    unittest.main()
