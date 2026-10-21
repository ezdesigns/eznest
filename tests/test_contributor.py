from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contributor import locations, setup, ready, start_command


class ContributorTests(unittest.TestCase):
    def checkout(self, root, name):
        path = root / name; path.mkdir()
        (path / 'requirements.txt').write_text('example==1\n')
        return path

    def test_checkout_data_is_separate_and_stable_across_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); a = self.checkout(root, 'a'); b = self.checkout(root, 'b')
            first = locations(a, root/'local'); other = locations(b, root/'local')
            self.assertNotEqual(first['data'], other['data'])
            self.assertTrue(first['data'].is_relative_to(root/'local'/'eznest-contributors'))
            self.assertFalse(first['data'].is_relative_to(a))
            (a/'requirements.txt').write_text('example==2\n')
            updated = locations(a, root/'local')
            self.assertEqual(first['data'], updated['data'])
            self.assertNotEqual(first['environment'], updated['environment'])
            command = start_command(updated, 18765, True)
            self.assertIn('--shop-test', command)
            self.assertIn(str(updated['data']), command)
            self.assertIn('--no-browser', command)
            self.assertNotIn('--lan', command)

    def test_setup_preserves_unowned_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); paths=locations(self.checkout(root,'repo'),root/'local')
            paths['environment'].mkdir(parents=True)
            protected=paths['environment']/'keep.txt';protected.write_text('unchanged')
            with patch('contributor.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'unrecognized'):setup(paths)
                run.assert_not_called()
            self.assertEqual(protected.read_text(),'unchanged')
            self.assertFalse(paths['data'].exists())

    def test_failed_dependency_install_can_resume_only_owned_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); paths=locations(self.checkout(root,'repo'),root/'local')
            def create(_):
                paths['python'].parent.mkdir(parents=True,exist_ok=True)
                paths['python'].write_bytes(b'test stub')
            with patch('contributor.venv.EnvBuilder') as builder, patch('contributor.subprocess.run') as run:
                builder.return_value.create.side_effect=create
                run.side_effect=subprocess.CalledProcessError(1,['pip'])
                with self.assertRaises(subprocess.CalledProcessError):setup(paths)
                self.assertFalse(ready(paths))
                run.side_effect=None
                setup(paths)
                self.assertTrue(ready(paths))
                count=run.call_count
                setup(paths)
                self.assertEqual(run.call_count,count)
            self.assertFalse(paths['data'].exists())
