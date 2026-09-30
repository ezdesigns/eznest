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
from test_pdf_production import pdf_fixture,document_job


class DocumentServerTests(unittest.TestCase):
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
                parsed=request('/api/document/import',{'content':base64.b64encode(pdf_fixture()).decode(),'bleedMm':1,'cutSpot':'CutContour'})
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
