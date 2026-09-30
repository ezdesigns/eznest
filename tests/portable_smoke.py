"""Explicit packaged-app smoke check; uses synthetic art and a new data directory.

python tests/portable_smoke.py --exe <eznest.exe> --work <new-directory>
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pypdf import PdfReader
from test_pdf_production import pdf_fixture, document_job
from test_mixed_cuts import mixed_fixture
from cut_mapping import defaults
from pdf_io import read_document, MM


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args();exe=args.exe.resolve();work=args.work.resolve()
    if not exe.is_file():raise ValueError('Executable not found.')
    if work.exists():raise ValueError('Use a new, dedicated smoke-test directory.')
    work.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([str(exe),'--no-browser','--port',str(port),'--data-dir',str(work/'data')],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    token=None
    def request(path,data=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-EZ-Token']=token
        req=Request(f'http://127.0.0.1:{port}'+path,headers=headers,data=json.dumps(data).encode() if data is not None else None)
        with urlopen(req,timeout=120) as response:
            return json.load(response) if response.headers.get_content_type()=='application/json' else response.read()
    try:
        for _ in range(100):
            try:session=request('/api/session');break
            except URLError:
                if process.poll() is not None:raise RuntimeError('Portable app exited before startup.')
                time.sleep(.1)
        else:raise TimeoutError('Portable app did not start.')
        token=session['token']
        assert b'production-features.js' in request('/')
        assert b'importDocument' in request('/production-features.js')
        parsed=[]
        for forms in (False,True):
            parsed.append(request('/api/document/import',{'content':base64.b64encode(mixed_fixture(forms=forms)).decode(),'bleedMm':1,'cutSpot':'CutContour','cutMapping':defaults()}))
        job=document_job(parsed[0]);job['settings'].update(width=80,sheetLength=40,gap=3,margin=5,costPerSquareMeter=17.5,currency='USD')
        second=document_job(parsed[1]);source=second['productionJobs'][0]
        source.update(id='second',code='B',customer='Customer Two',order='ORDER-13',partIds=['second:'+p['pdfPieceId'] for p in second['parts']])
        for p in second['parts']:p.update(id='second:'+p['pdfPieceId'],sourceJobId='second')
        job['parts']+=second['parts'];job['productionJobs'].append(source)
        job['documentSources']['second']=second['documentSources']['job']
        for source in job['productionJobs']:source['sets']=2
        for part in job['parts']:part['quantity']=2
        request('/api/solve',job)
        for _ in range(600):
            state=request('/api/state')
            if state['status']!='running':break
            time.sleep(.1)
        assert state['status']=='ready',state.get('error')
        assert state['manifest']['outputCheck']['ready']
        assert state['manifest']['totalPieces']==8
        assert state['manifest']['cutSummary']=={'thru':8,'kiss':16,'contour':0}
        assert len(state['manifest']['sheets'])>1
        (work/'delivered').mkdir()
        request('/api/output/connect',{'path':str(work/'delivered')})
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 {state["result"]["usedLength"]}"/>'
        released=request('/api/release',{'id':state['id'],'map':svg})
        assert released['deliveryCompleted'] and Path(released['savedPath']).is_dir()
        content=request(released['url']);(work/'batch.zip').write_bytes(content)
        contour_count=0
        with ZipFile(io.BytesIO(content)) as archive:
            manifest=json.loads(archive.read('batch.json'))
            for name in manifest['printFiles']:
                raw=archive.read(name);reader=PdfReader(io.BytesIO(raw));page=reader.pages[0]
                assert reader.pdf_header=='%PDF-1.7'
                assert len(reader.pages)==1
                assert abs(float(page.mediabox.width)*MM-80)<.001
                assert float(page.mediabox.height)*MM<=40.001
                assert page['/Resources']['/ColorSpace']['/EZCut'][1]=='/CutContour_Thru-cut'
                assert {g.get_object()['/Name'] for g in reader.root_object['/OCProperties']['/OCGs']}=={'Thru-cut','Kiss-cut'}
                checked=read_document(raw,cut_mapping=defaults())[1]
                assert checked['registrationPaintRemoved']==0
                assert all(p['cutCounts']=={'thru':1,'kiss':2,'contour':0} for p in checked['pieces'])
                contour_count+=len(checked['pieces'])
                assert (Path(released['savedPath'])/name).read_bytes()==raw
            assert {p['order'] for p in manifest['pieces']}=={'ORDER-12','ORDER-13'}
            assert abs(sum(j['cost'] for j in manifest['materialCost']['jobs'])-manifest['materialCost']['total'])<.001
        assert contour_count==8
        request('/api/release',{'id':state['id'],'map':'frozen retry'})
        assert request(released['url'])==content
        try:request('/api/document/import',{'content':base64.b64encode(b'%!PS old Illustrator').decode()})
        except HTTPError as error:assert error.code==400
        else:raise AssertionError('Non-PDF AI must be rejected.')
        summary={'version':session['version'],'pieces':8,'orders':2,'sheets':len(manifest['sheets']),'usedLengthMm':manifest['usedLength'],'materialCost':manifest['materialCost']['total'],'sha256':hashlib.sha256(content).hexdigest(),'checks':'packaged PDFium import, native solver, vector PDF cut spot/layer, sheet size, source contours, folder save, frozen retry, unsupported AI rejection'}
        (work/'validation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary,indent=2))
    finally:
        if token:
            try:request('/api/shutdown',{})
            except Exception:pass
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)


if __name__=='__main__':main()
