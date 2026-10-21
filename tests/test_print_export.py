import hashlib
import io
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import print_export


class PrintExportTests(unittest.TestCase):
    @unittest.skipUnless(print_export.os.name == 'nt', 'Windows Save As')
    def test_native_picker_cancel_path_and_failure_never_write(self):
        with patch('print_export.subprocess.run') as run:
            run.return_value.stdout = b''
            self.assertIsNone(print_export.pick_save_path('kit', 'pdf'))
            run.return_value.stdout = 'C:\\Prints\\Changed name.pdf'.encode('utf-8')
            self.assertEqual(print_export.pick_save_path('kit', 'pdf'), 'C:\\Prints\\Changed name.pdf')
            run.side_effect = subprocess.TimeoutExpired('powershell', 300)
            with self.assertRaisesRegex(ValueError, 'could not finish'):
                print_export.pick_save_path('kit', 'pdf')

    def test_folder_chooser_lists_folders_only_and_checks_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'Kits').mkdir(); (root/'Material').mkdir()
            (root/'private.pdf').write_bytes(b'not listed')
            result = print_export.browse_folders(str(root), None)
            self.assertEqual([item['name'] for item in result['folders']], ['Kits', 'Material'])
            self.assertEqual(result['path'], str(root.resolve()))
            for value in ['../', 'relative', str(root/'private.pdf')]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    print_export.browse_folders(value, None)

    def test_exact_name_and_frozen_pdf_or_pack(self):
        stream = io.BytesIO()
        with ZipFile(stream, 'w') as archive:
            archive.writestr('artwork.pdf', b'%PDF-example')
        package = stream.getvalue()
        self.assertEqual(print_export.export_content(package, 'My kit', 'pdf'), ('My kit.pdf', b'%PDF-example'))
        self.assertEqual(print_export.export_content(package, 'My kit.PDF', 'pdf'), ('My kit.pdf', b'%PDF-example'))
        self.assertEqual(print_export.export_content(package, 'My kit', 'pack'), ('My kit.zip', package))
        for name in ['../source', 'C:\\source', 'x/y', 'NUL', 'CON.pdf', '.', 'kit.', 'kit ', 'a\0b']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                print_export.export_content(package, name, 'pdf')
        stream = io.BytesIO()
        with ZipFile(stream, 'w') as archive:
            archive.writestr('sheet-001.pdf', b'%PDF-example')
        with self.assertRaisesRegex(ValueError, 'multiple sheets'):
            print_export.export_content(stream.getvalue(), 'kit', 'pdf')

    def test_replacement_requires_current_digest_and_retains_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root/'kit.pdf'; work = root/'data'
            target.write_bytes(b'original')
            conflict = print_export.save_file(target, b'new', work)
            self.assertTrue(conflict['exists'])
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(work.exists())
            target.write_bytes(b'changed after review')
            conflict2 = print_export.save_file(target, b'new', work, conflict['existingSha256'])
            self.assertTrue(conflict2['exists'])
            result = print_export.save_file(target, b'new', work, conflict2['existingSha256'])
            self.assertEqual(target.read_bytes(), b'new')
            self.assertEqual(Path(result['backup']).read_bytes(), b'changed after review')
            self.assertEqual(result['sha256'], hashlib.sha256(b'new').hexdigest())
            self.assertEqual(print_export.save_file(target, b'new', work)['sha256'], result['sha256'])
            self.assertEqual(len(list((work/'export-backups').iterdir())), 1)

    def test_failed_publish_keeps_existing_file_and_watched_source_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root/'kit.pdf'; target.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError, 'watched source'):
                print_export.save_file(target, b'new', root/'data', source=root)
            with patch.object(print_export.os, 'replace', side_effect=PermissionError('File open')):
                with self.assertRaises(PermissionError):
                    print_export.save_file(target, b'new', root/'data', hashlib.sha256(b'original').hexdigest())
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(list(root.glob('.eznest-*')))
