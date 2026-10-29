import opt_out
import base64
import copy
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from zipfile import ZipFile
from unittest.mock import patch
import server
from test_pdf_production import pdf_fixture,document_job,square_pdf_fixture
from test_mixed_cuts import mixed_fixture
from cut_mapping import defaults


class DocumentServerTests(unittest.TestCase):
    def test_changed_bleed_cannot_freeze_an_unsafe_old_layout(self):
        from pdf_io import import_to_store
        old_work, old_port, old_state = server.WORK, server.PORT, copy.deepcopy(server.STATE)
        with tempfile.TemporaryDirectory() as directory:
            server.WORK = Path(directory)
            parsed = import_to_store(square_pdf_fixture(), server.WORK/'documents', 0)
            job = document_job(parsed)
            job['settings'].update(width=100, gap=1, margin=2, rotations=[0], autoBleedMm=0)
            result = {'width':100, 'usedLength':40, 'placements':[
                {'id':job['parts'][0]['id'], 'x':10, 'y':10, 'rotation':0},
                {'id':job['parts'][1]['id'], 'x':31.02, 'y':10, 'rotation':0}]}
            service = server.ThreadingHTTPServer(('127.0.0.1',0), server.Handler)
            server.PORT = service.server_port
            thread = threading.Thread(target=service.serve_forever, daemon=True); thread.start()
            try:
                server.STATE.clear()
                server.STATE.update(status='ready', id='a'*32, job=copy.deepcopy(job), result=result)
                data = {'id':'a'*32, 'autoBleedMm':3.175,
                        'map':'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40"/>'}
                request = Request(f'http://127.0.0.1:{server.PORT}/api/release',
                                  data=json.dumps(data).encode(),
                                  headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
                with patch.object(server.OUTPUT, 'save') as deliver:
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(request, timeout=10)
                    self.assertEqual(rejected.exception.code, 400)
                    self.assertIn('Auto bleed needs more space', rejected.exception.read().decode())
                    deliver.assert_not_called()
                self.assertFalse(server.STATE.get('released'))
                self.assertEqual(server.STATE['job'], job)
                self.assertFalse((server.WORK/'batches'/('a'*32+'.zip')).exists())
            finally:
                service.shutdown(); service.server_close(); thread.join()
                server.WORK, server.PORT = old_work, old_port
                server.STATE.clear(); server.STATE.update(old_state)

    def test_import_solve_export_acknowledgment_and_frozen_retry(self):
        old_work,old_port,old_state=server.WORK,server.PORT,copy.deepcopy(server.STATE)
        with tempfile.TemporaryDirectory() as directory:
            server.WORK=Path(directory)
            service=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);server.PORT=service.server_port
            thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
            def request(path,data=None):
                req=Request(f'http://127.0.0.1:{server.PORT}'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
                with urlopen(req,timeout=30) as response:return json.load(response) if response.headers.get_content_type()=='application/json' else response.read()
            try:
                server.STATE.clear();server.STATE.update(status='idle')
                parsed=request('/api/document/import',{'content':base64.b64encode(mixed_fixture()).decode(),'bleedMm':1,'cutSpot':'CutContour','cutMapping':defaults()})
                self.assertEqual(parsed['format'],'pdf');self.assertFalse(parsed['reviewed'])
                job=document_job(parsed);job['settings'].update(sheetLength=45,costPerSquareMeter=20,currency='USD')
                request('/api/solve',job)
                for _ in range(100):
                    state=request('/api/state')
                    if state['status']!='running':break
                    time.sleep(.1)
                self.assertEqual(state['status'],'ready',state.get('error'))
                self.assertTrue(state['manifest']['outputCheck']['ready'])
                self.assertIn('materialCost',state['manifest'])
                self.assertEqual(state['manifest']['cutSummary'],{'thru':2,'kiss':4,'contour':0})
                svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 45"/>'
                with patch.object(server.OUTPUT,'save',return_value=None):
                    released=request('/api/release',{'id':state['id'],'map':svg})
                    self.assertFalse(released['deliveryCompleted'])
                    content=request(released['url'])
                    with ZipFile(io.BytesIO(content)) as archive:self.assertIn('artwork.pdf',archive.namelist())
                    self.assertFalse(request('/api/state')['deliveryCompleted'])
                    with self.assertRaises(HTTPError):request('/api/delivery/complete',{'id':'stale'})
                    request('/api/delivery/complete',{'id':state['id']})
                    self.assertTrue(request('/api/state')['deliveryCompleted'])
                    request('/api/release',{'id':state['id'],'map':'not used on retry'})
                    self.assertEqual(content,request(released['url']))
            finally:
                if server.PROCESS and server.PROCESS.poll() is None:
                    server.PROCESS.terminate();server.PROCESS.wait(timeout=5)
                service.shutdown();service.server_close();thread.join()
                server.WORK,server.PORT=old_work,old_port;server.STATE.clear();server.STATE.update(old_state)


if __name__=='__main__':unittest.main()
