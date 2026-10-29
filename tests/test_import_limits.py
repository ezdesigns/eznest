import opt_out
import base64
import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import illustrator_bridge
import pdf_io
import server
from import_limits import MAX_IMPORT_REQUEST_BYTES, MAX_PDF_BYTES, MAX_JSON_PDF_BYTES, request_limit
from test_illustrator_bridge import handoff


class ImportLimitTests(unittest.TestCase):
    def test_worker_timeout_removes_owned_print_copy_and_releases_lock(self):
        import subprocess
        handler=server.Handler.__new__(server.Handler);handler.rfile=io.BytesIO(b'%PDF-test')
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'WORK',Path(directory)):
            def fail(args,**kwargs):
                source=Path(args[-1]);source.with_name(source.stem+'-print.pdf').write_bytes(b'partial')
                raise subprocess.TimeoutExpired(args,300)
            with patch.object(server.subprocess,'run',side_effect=fail):
                with self.assertRaisesRegex(ValueError,'too long'):handler.import_document({},9)
            self.assertEqual(list(Path(directory).iterdir()),[])
        self.assertFalse(server.DOCUMENT_LOCK.locked())

    def test_temporary_windows_lock_is_retried_before_cleanup_finishes(self):
        with patch.object(Path, 'unlink', side_effect=[PermissionError('busy'), None]) as unlink, patch.object(server.time, 'sleep') as sleep:
            server.remove_import_temp(Path('synthetic-upload.pdf'))
        self.assertEqual(unlink.call_count, 2)
        sleep.assert_called_once_with(0.1)

    def test_binary_upload_checks_session_origin_and_length_before_reading(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = '/api/document/import-file'
        handler.allowed = lambda: True
        handler.local_name = lambda name: False
        sent = []
        handler.send = lambda status, data: sent.append((status, data))
        headers = {'X-EZ-Token':server.TOKEN, 'Content-Length':'100'}
        for change, status in [({'X-EZ-Token':'wrong'},403),
                               ({'Origin':'https://untrusted.invalid'},403),
                               ({'Content-Length':str(MAX_PDF_BYTES+1)},400)]:
            with self.subTest(change=change), patch.object(handler, 'import_document') as parse:
                handler.headers = {**headers, **change}
                handler.rfile = None  # Any attempt to read the body would fail.
                handler.handle_post()
                self.assertEqual(sent[-1][0], status)
                parse.assert_not_called()

    def test_upload_reads_bounded_chunks_and_never_uses_a_supplied_path(self):
        raw = b'%PDF-' + b'x' * 2_100_000
        class Reader(io.BytesIO):
            def read(self, size=-1):
                self.last_sizes.append(size)
                return super().read(size)
        reader = Reader(raw)
        reader.last_sizes = []
        handler = server.Handler.__new__(server.Handler)
        handler.rfile = reader
        handler.send = lambda status, data: (status, data)
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'WORK', Path(folder)):
            def run(args, **kwargs):
                request, output, source = map(Path, args[-3:])
                self.assertEqual(source.parent, Path(folder))
                self.assertEqual(source.read_bytes(), raw)
                self.assertEqual(json.loads(request.read_text()), {'preserveArtwork': True})
                output.write_text(json.dumps({'ok':True, 'document':{'parts':[]}}))
            with patch.object(server.subprocess, 'run', side_effect=run):
                self.assertEqual(handler.import_document({'contentFile':'C:/private.pdf', 'content':'ignored', 'preserveArtwork':True}, len(raw)), (200, {'parts':[]}))
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertLessEqual(max(reader.last_sizes), 1_048_576)
        self.assertFalse(server.DOCUMENT_LOCK.locked())

    def test_interrupted_upload_cleans_up_and_keeps_current_job(self):
        handler = server.Handler.__new__(server.Handler)
        handler.rfile = io.BytesIO(b'%PDF-short')
        before = dict(server.STATE)
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'WORK', Path(folder)):
            with patch.object(server.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'interrupted'):
                    handler.import_document({}, 100)
                run.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertEqual(server.STATE, before)
        self.assertFalse(server.DOCUMENT_LOCK.locked())

    def test_file_worker_rejects_over_limit_before_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            request, output, source = [Path(folder)/name for name in ('request.json','result.json','source.pdf')]
            request.write_text('{}')
            source.write_bytes(b'x' * 101)
            with patch.object(pdf_io, 'MAX_PDF_BYTES', 100), patch.object(pdf_io, 'import_to_store') as parse:
                pdf_io.worker(request, output, source)
            self.assertIn('2 GB', json.loads(output.read_text())['error'])
            parse.assert_not_called()

    def test_large_request_allowance_is_only_for_imports(self):
        self.assertGreater(MAX_IMPORT_REQUEST_BYTES, 4 * ((MAX_JSON_PDF_BYTES + 2) // 3))
        self.assertEqual(request_limit('/api/document/import-file'), MAX_PDF_BYTES)
        for route in ('/api/document/import', '/api/illustrator/intake'):
            self.assertEqual(request_limit(route), MAX_IMPORT_REQUEST_BYTES)
        for route in ('/api/preferences', '/api/document/import/extra', '/api/nest'):
            self.assertEqual(request_limit(route), 48_000_000)

    def test_pdf_worker_rejects_over_limit_before_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            request, output = Path(folder)/'request.json', Path(folder)/'result.json'
            request.write_text(json.dumps({'content': base64.b64encode(b'%PDF-' + b'x'*100).decode()}))
            with patch.object(pdf_io, 'MAX_JSON_PDF_BYTES', 100), patch.object(pdf_io, 'import_to_store') as parse:
                pdf_io.worker(request, output)
            self.assertFalse(json.loads(output.read_text())['ok'])
            self.assertIn('256 MB', json.loads(output.read_text())['error'])
            parse.assert_not_called()

    def test_illustrator_rejects_oversize_before_decode_and_write(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(illustrator_bridge, 'MAX_PDF_BASE64_CHARS', 4):
            data = handoff()
            with patch.object(illustrator_bridge.base64, 'b64decode') as decode:
                with self.assertRaisesRegex(ValueError, '256 MB'):
                    illustrator_bridge.accept(folder, data)
            decode.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])
