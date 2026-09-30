import json
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

