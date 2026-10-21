import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from build_tester_kit import package


class TesterKitTests(unittest.TestCase):
    def source(self, root):
        source = root / 'source'; (source / 'app').mkdir(parents=True)
        (source / 'app/eznest.exe').write_bytes(b'test executable')
        (source / 'START Shop Test.cmd').write_text('@echo off\nstart "" "%~dp0app\\eznest.exe" --shop-test\n')
        manifest = {'buildId':'Verified-Trial', 'version':'test-version', 'channel':'local-shop-trial',
                    'automaticUpdates':False, 'exeSha256':hashlib.sha256(b'test executable').hexdigest()}
        (source / 'BUILD.json').write_text(json.dumps(manifest))
        files = {p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        (source / 'FILES.sha256.json').write_text(json.dumps(files))
        return source

    def test_copies_verified_distribution_only_and_keeps_app_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.source(root)
            (source / 'private-job.pdf').write_bytes(b'never distribute')
            result = package(source, root / 'kit', 'Tester-01')
            self.assertEqual((root / 'kit/app/eznest.exe').read_bytes(), b'test executable')
            self.assertEqual((root / 'kit/BUILD.json').read_bytes(), (source / 'BUILD.json').read_bytes())
            self.assertFalse((root / 'kit/private-job.pdf').exists())
            self.assertIn('Tester-01', (root / 'kit/START HERE.html').read_text(encoding='utf-8'))
            self.assertNotIn('{{', (root / 'kit/START HERE.html').read_text(encoding='utf-8'))
            with zipfile.ZipFile(result['zip']) as z:
                self.assertIsNone(z.testzip())
                for name, digest in json.loads((root / 'kit/FILES.sha256.json').read_text()).items():
                    self.assertEqual(hashlib.sha256(z.read('kit/' + name)).hexdigest(), digest)
            with self.assertRaisesRegex(ValueError, 'preserved'):
                package(source, root / 'kit', 'Tester-01')

    def test_tampered_app_and_escaping_paths_are_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.source(root)
            (source / 'app/eznest.exe').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'verification'):
                package(source, root / 'kit', 'Tester-01')
            self.assertFalse((root / 'kit').exists())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.source(root)
            (source / 'FILES.sha256.json').write_text(json.dumps({'../secret':'invalid'}))
            with self.assertRaisesRegex(ValueError, 'verification'):
                package(source, root / 'kit', 'Tester-01')
            self.assertFalse((root / 'kit').exists())
