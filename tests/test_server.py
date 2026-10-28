import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import server
import copy
from unittest.mock import patch


class ServerTests(unittest.TestCase):
    def test_local_server_restarts_after_connection_but_rejects_live_listener(self):
        from http.server import BaseHTTPRequestHandler
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')
            def log_message(self, *_args):
                pass
        service = server.LocalServer(('127.0.0.1', 0), Handler)
        address = service.server_address
        thread = threading.Thread(target=service.serve_forever)
        thread.start()
        try:
            with self.assertRaises(OSError):
                server.LocalServer(address, Handler)
            with urlopen(f'http://127.0.0.1:{address[1]}', timeout=5) as response:
                self.assertEqual(response.read(), b'ok')
        finally:
            service.shutdown()
            service.server_close()
            thread.join()
        with server.LocalServer(address, Handler) as restarted:
            self.assertEqual(restarted.server_address, address)

    def test_failed_bind_never_marks_update_healthy(self):
        import installer_update
        with patch.object(server, 'restore_state'), \
             patch.object(server, 'LocalServer', side_effect=OSError('address already in use')), \
             patch.object(installer_update, 'mark_healthy') as healthy:
            with self.assertRaisesRegex(OSError, 'address already in use'):
                server.serve()
            healthy.assert_not_called()

    def test_session_advertises_native_save_only_when_dialog_is_available(self):
        old_port = server.PORT
        service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            for available in (False, True):
                with patch.object(server.print_export, 'native_save_available', return_value=available):
                    with urlopen(f'http://127.0.0.1:{server.PORT}/api/session') as response:
                        self.assertEqual(json.load(response)['localSave'], available)
        finally:
            service.shutdown()
            service.server_close()
            thread.join()
            server.PORT = old_port

    def test_download_only_never_delivers_and_print_is_from_frozen_pack(self):
        import io
        from zipfile import ZipFile
        original, old_port, old_work = copy.deepcopy(server.STATE), server.PORT, server.WORK
        service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True);thread.start()
        ident = 'b' * 32
        data = io.BytesIO()
        with ZipFile(data, 'w') as archive:archive.writestr('artwork.pdf', b'%PDF-frozen-test')
        try:
            with tempfile.TemporaryDirectory() as folder:
                server.WORK=Path(folder)
                server.STATE.clear();server.STATE.update(status='ready',id=ident,job={},result={})
                with patch.object(server,'make_package',return_value=(data.getvalue(),{'totalPieces':1})), patch.object(server.OUTPUT,'save') as deliver, patch.object(server,'stage_pack') as stage:
                    request=Request(f'http://127.0.0.1:{server.PORT}/api/release',data=json.dumps({'id':ident,'map':'map','downloadOnly':True,'stagingFolder':'must-not-write'}).encode(),headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
                    with urlopen(request) as response:reply=json.load(response)
                    self.assertFalse(reply['deliveryCompleted']);self.assertFalse(reply['savedPath'])
                    deliver.assert_not_called();stage.assert_not_called()
                    with urlopen(f'http://127.0.0.1:{server.PORT}/api/print/{ident}') as response:
                        self.assertEqual(response.read(),b'%PDF-frozen-test')
                        self.assertEqual(response.headers.get_content_type(),'application/pdf')
        finally:
            service.shutdown();service.server_close();thread.join()
            server.STATE.clear();server.STATE.update(original);server.PORT=old_port;server.WORK=old_work

    def test_one_connection_returns_the_stylesheet_and_a_script(self):
        old_port = server.PORT
        service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            sock = socket.create_connection(('127.0.0.1', server.PORT), timeout=5)
            try:
                sock.settimeout(5)
                sock.sendall((
                    f'GET /web.css HTTP/1.1\r\nHost: 127.0.0.1:{server.PORT}\r\n\r\n'
                    f'GET /shop-profiles.js HTTP/1.1\r\nHost: 127.0.0.1:{server.PORT}\r\nConnection: close\r\n\r\n'
                ).encode())
                chunks = []
                while True:
                    try:
                        block = sock.recv(65536)
                    except socket.timeout:
                        break
                    if not block:
                        break
                    chunks.append(block)
                payload = b''.join(chunks)
            finally:
                sock.close()
            self.assertGreaterEqual(payload.count(b'HTTP/1.1 200'), 2)
            self.assertIn(b'--alarm', payload)
            self.assertIn(b'EZNProfiles', payload)
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=3)
            server.PORT = old_port

    def test_shutdown_requires_session_and_idle_worker(self):
        original,old_port=copy.deepcopy(server.STATE),server.PORT
        service=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        server.PORT=service.server_port
        thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
        def stop(token=None):
            headers={'Content-Type':'application/json'}
            if token:headers['X-EZ-Token']=token
            with urlopen(Request(f'http://127.0.0.1:{server.PORT}/api/shutdown',data=b'{}',headers=headers),timeout=5) as response:return json.load(response)
        try:
            with self.assertRaises(HTTPError) as rejected:stop()
            self.assertEqual(rejected.exception.code,403)
            server.STATE.clear();server.STATE.update(status='running')
            with self.assertRaises(HTTPError) as busy:stop(server.TOKEN)
            self.assertEqual(busy.exception.code,400)
            self.assertTrue(thread.is_alive())
            server.STATE.clear();server.STATE.update(status='idle')
            self.assertTrue(stop(server.TOKEN)['ok'])
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        finally:
            service.shutdown();service.server_close();thread.join()
            server.STATE.clear();server.STATE.update(original);server.PORT=old_port

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_work = server.WORK
        server.WORK = Path(self.directory.name)

    def tearDown(self):
        server.WORK = self.previous_work
        self.directory.cleanup()

    def test_unavailable_output_requires_explicit_working_package(self):
        original, old_port = copy.deepcopy(server.STATE), server.PORT
        profile=json.loads((Path(__file__).parent/'shop-profile-cases.json').read_text()) [1]['profile']
        check=server.inspect_output(profile)
        service=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        server.PORT=service.server_port
        thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
        server.STATE.clear();server.STATE.update(status='ready',id='b'*32,job={'outputProfile':profile},result={})
        def release(working=False):
            req=Request(f'http://127.0.0.1:{server.PORT}/api/release',data=json.dumps({'id':'b'*32,'artwork':'svg','map':'map','workingOnly':working}).encode(),headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
            with urlopen(req,timeout=10) as response:return json.load(response)
        try:
            with patch.object(server,'make_package',return_value=(b'working-pack',{'outputCheck':check})) as package,patch.object(server.OUTPUT,'save',return_value=None):
                with self.assertRaises(HTTPError) as blocked:release()
                self.assertEqual(blocked.exception.code,400)
                self.assertFalse(server.STATE.get('released',False));self.assertEqual(package.call_count,0)
                response=release(True)
                self.assertFalse(response['outputCheck']['ready'])
                self.assertFalse(server.STATE['deliveryCompleted'])
                req=Request(f'http://127.0.0.1:{server.PORT}/api/delivery/complete',data=json.dumps({'id':'b'*32}).encode(),headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
                with urlopen(req,timeout=5) as delivered:self.assertTrue(json.load(delivered)['ok'])
                self.assertTrue(server.STATE['deliveryCompleted'])
                self.assertFalse(server.STATE['manifest']['outputCheck']['ready'])
        finally:
            service.shutdown();service.server_close();thread.join()
            server.STATE.clear();server.STATE.update(original);server.PORT=old_port

    def test_best_result_survives_worse_or_failed_search(self):
        original = copy.deepcopy(server.STATE)
        best = {'status':'ready', 'id':'best', 'result':{'usedLength':100}, 'job':{'captureId':'source'}}
        try:
            for payload in ({'ok':True,'result':{'usedLength':120}}, {'ok':False,'error':'failed'}):
                server.STATE.clear();server.STATE.update(status='running',id='new',incumbent=copy.deepcopy(best))
                server.finish_search(payload)
                self.assertEqual(server.STATE['id'],'best')
                self.assertEqual(server.STATE['result']['usedLength'],100)
                self.assertEqual(server.STATE['status'],'ready')
            server.STATE.clear();server.STATE.update(status='running',id='new',incumbent=copy.deepcopy(best))
            server.finish_search({'ok':True,'result':{'usedLength':90}})
            self.assertEqual(server.STATE['id'],'new')
            self.assertEqual(server.STATE['result']['usedLength'],90)
            self.assertEqual(server.STATE['nestSavings']['savedLengthMm'],10)
            improved=copy.deepcopy(server.STATE)
            for length in (80, 110):
                server.STATE.clear();server.STATE.update(status='running',id='retry',incumbent=improved)
                server.finish_search({'ok':True,'result':{'usedLength':length}})
                self.assertEqual(server.STATE['nestSavings']['baselineLengthMm'],100)
                self.assertEqual(server.STATE['nestSavings']['savedLengthMm'],20)
                improved=copy.deepcopy(server.STATE)
            saved=json.loads((server.WORK/'session.json').read_text())
            self.assertEqual(saved['nestSavings']['percent'],20)
            # A new quantity/filler outcome must not reuse an unrelated saving.
            server.STATE.clear();server.STATE.update(status='running',id='fill',incumbent=improved)
            server.finish_search({'ok':True,'result':{'usedLength':95,'fillSummary':[{'pieces':1}]}})
            self.assertNotIn('nestSavings',server.STATE)
            server.STATE.clear();server.STATE.update(status='running',id='fresh')
            server.finish_search({'ok':True,'result':{'usedLength':70}})
            self.assertNotIn('nestSavings',server.STATE)
        finally:
            server.STATE.clear();server.STATE.update(original)

    def test_session_validation_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            old_work, old_port = server.WORK, server.PORT
            server.WORK = Path(directory)
            service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            server.PORT = service.server_port
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            def request(path, data=None, token=None):
                headers = {'Content-Type': 'application/json'}
                if token:
                    headers['X-EZ-Token'] = token
                req = Request(f'http://127.0.0.1:{server.PORT}{path}',
                              data=json.dumps(data).encode() if data is not None else None,
                              headers=headers)
                with urlopen(req, timeout=10) as response:
                    return json.load(response)
            try:
                token = request('/api/session')['token']
                with self.assertRaises(HTTPError) as rejected:
                    request('/api/solve', {})
                self.assertEqual(rejected.exception.code, 403)
                with self.assertRaises(HTTPError) as invalid:
                    request('/api/solve', {}, token)
                self.assertEqual(invalid.exception.code, 400)
                sample = json.loads((server.ROOT / 'sample.json').read_text())
                request('/api/solve', sample, token)
                self.assertEqual(request('/api/state')['status'], 'running')
                request('/api/cancel', {}, token)
                self.assertEqual(request('/api/state')['status'], 'cancelled')
                self.assertIsNotNone(server.PROCESS.poll())
                # Effort changes only the search budget, not geometry or quantities.
                server.STATE.clear();server.STATE.update(status='ready',id='effort',job=copy.deepcopy(sample),result={'usedLength':100})
                with self.assertRaises(HTTPError):
                    request('/api/improve', {'id':'effort','seconds':999}, token)
                self.assertEqual(server.STATE['id'],'effort')
                request('/api/improve', {'id':'effort','seconds':5}, token)
                self.assertEqual(server.STATE['job']['settings']['seconds'],5)
                self.assertEqual(server.STATE['job']['parts'],sample['parts'])
                request('/api/cancel', {}, token)
                # A stopped retry can have a valid progress layout that is
                # longer than the incumbent. Keep the shorter original.
                best={'status':'ready','id':'best','job':{},'result':{'usedLength':100}}
                directory_path=Path(directory)
                (directory_path/'progress.json').write_text(json.dumps({'ok':True,'result':{'usedLength':120}}))
                server.STATE.clear();server.STATE.update(status='running',id='retry',job={},output=str(directory_path/'result.json'),incumbent=best)
                request('/api/cancel',{'keepBest':True},token)
                self.assertEqual(server.STATE['id'],'best')
                self.assertEqual(server.STATE['result']['usedLength'],100)
                with self.assertRaises(HTTPError) as stale:
                    request('/api/prepare-apply', {'id': 'stale'}, token)
                self.assertEqual(stale.exception.code, 400)
                server.STATE.clear()
                server.STATE.update(status='ready',id='frozen',released=True)
                with self.assertRaises(HTTPError) as frozen:
                    request('/api/improve', {'id':'frozen'}, token)
                self.assertIn('frozen',frozen.exception.read().decode())
            finally:
                if server.PROCESS and server.PROCESS.poll() is None:
                    server.PROCESS.terminate()
                    server.PROCESS.wait(timeout=5)
                service.shutdown()
                service.server_close()
                thread.join()
                server.WORK, server.PORT = old_work, old_port

    def test_output_failure_does_not_complete_delivery_and_retry_reuses_frozen_pack(self):
        original, old_port = copy.deepcopy(server.STATE), server.PORT
        service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        ident = 'a' * 32
        server.STATE.clear()
        server.STATE.update(status='ready', id=ident, job={}, result={})
        def release():
            request = Request(f'http://127.0.0.1:{server.PORT}/api/release',
                data=json.dumps({'id':ident,'artwork':'svg','map':'map'}).encode(),
                headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
            with urlopen(request, timeout=10) as response:
                return json.load(response)
        try:
            with patch.object(server, 'make_package', return_value=(b'frozen-pack', {'totalPieces':2})) as package, \
                 patch.object(server.OUTPUT, 'save', side_effect=[ValueError('Output unavailable'), 'saved-test-folder']):
                with self.assertRaises(HTTPError) as failure:
                    release()
                self.assertEqual(failure.exception.code, 400)
                self.assertTrue(server.STATE['released'])
                self.assertFalse(server.STATE['deliveryCompleted'])
                persisted = json.loads((server.WORK/'session.json').read_text())
                self.assertFalse(persisted['deliveryCompleted'])
                self.assertEqual(release()['savedPath'], 'saved-test-folder')
                self.assertTrue(server.STATE['deliveryCompleted'])
                self.assertTrue(json.loads((server.WORK/'session.json').read_text())['deliveryCompleted'])
                self.assertEqual(package.call_count, 1)
        finally:
            service.shutdown();service.server_close();thread.join()
            server.STATE.clear();server.STATE.update(original);server.PORT=old_port

