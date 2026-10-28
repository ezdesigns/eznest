"""Exercise a built macOS bundle with synthetic SVG/PDF data and restart checks.

Requires the source test dependencies and Playwright with installed Chrome/Edge.
Only the explicit new output directory is written. No app installation or signing.
"""
import argparse, hashlib, io, json, os, socket, subprocess, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
from test_mixed_cuts import mixed_fixture
from playwright.sync_api import sync_playwright


def launch_browser(playwright):
    last = None
    for channel in ('chrome', 'msedge'):
        try:
            return playwright.chromium.launch(channel=channel, headless=True)
        except Exception as error:
            last = error
    raise RuntimeError('Install Chrome or Edge for this bundle check.') from last

APP=(args.bundle/'Contents'/'MacOS'/'eznest').resolve()
if sys.platform != 'darwin' or not APP.is_file():
    parser.error('Pass a built eznest.app bundle on macOS.')
OUT=args.out.resolve()
OUT.mkdir(parents=True,exist_ok=False)
with socket.socket() as s:
    s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
URL=f'http://127.0.0.1:{port}'
proc=None
log=(OUT/'app.log').open('w')
env={k:os.environ[k] for k in ('HOME','PATH','TMPDIR') if k in os.environ}
def request(path,data=None):
    headers={'Content-Type':'application/json'}
    if data is not None:headers['X-EZ-Token']=request('/api/session')['token']
    with urlopen(Request(URL+path,data=None if data is None else json.dumps(data).encode(),headers=headers),timeout=15) as r:return json.load(r)
def start(folder):
    global proc
    proc=subprocess.Popen([str(APP),'--no-browser','--shop-test','--data-dir',str(folder),'--port',str(port)],cwd=OUT,env=env,stdout=log,stderr=log)
    for _ in range(100):
        if proc.poll() is not None:raise AssertionError(f'app exited {proc.returncode}')
        try:return request('/api/session')
        except OSError:time.sleep(.1)
    raise AssertionError('app did not start')
def stop():
    global proc
    if proc and proc.poll() is None:
        request('/api/shutdown',{})
        assert proc.wait(timeout=10)==0
    proc=None

def download(page,target):
    page.evaluate('localSave=false')
    page.click('#export')
    page.select_option('#save-destination','download')
    page.select_option('#save-format','pack')
    with page.expect_download(timeout=60000) as pending:page.click('#confirm-send')
    pending.value.save_as(str(target))
    return target.read_bytes()
receipts=[]
try:
    with sync_playwright() as p:
        browser=launch_browser(p)
        try:
            for kind in ('svg','pdf'):
                folder=OUT/kind
                folder.mkdir()
                session=start(folder/'data')
                assert session['app']=='eznest'
                page=browser.new_page(viewport={'width':1280,'height':900},accept_downloads=True)
                page.goto(URL+'/web')
                page.wait_for_function("() => document.body.dataset.ready === '1'")
                page.click('#edit-material');page.select_option('#unit','mm');page.fill('#width','220');page.click('#save-material')
                page.wait_for_function("() => !document.querySelector('#save-material').disabled")
                page.locator('#layout-options').evaluate('n=>n.open=true')
                page.select_option('#nesting-effort','5')
                source=ROOT/'sample-artwork.svg'
                if kind=='pdf':
                    source=folder/'synthetic.pdf';source.write_bytes(mixed_fixture())
                page.set_input_files('#file',str(source))
                page.wait_for_function('() => !importing && kits.length === 1')
                page.click('#start-nesting')
                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')",timeout=90000)
                state=request('/api/state');assert state['status']=='ready'
                first=download(page,folder/'first.zip')
                second=download(page,folder/'second.zip')
                assert first==second
                with ZipFile(io.BytesIO(first)) as archive:
                    assert archive.testzip() is None
                    artwork=archive.read('artwork.'+kind)
                    assert b'CutContour_Kiss-cut' in artwork
                page.screenshot(path=str(folder/'saved.png'),full_page=True)
                stop();start(folder/'data')
                restored=request('/api/state');assert restored['id']==state['id'] and restored['released']
                page.reload();page.wait_for_function("() => document.body.dataset.ready === '1'")
                assert download(page,folder/'restored.zip')==first
                receipts.append({'format':kind,'pieces':len(state['result']['placements']),'sha256':hashlib.sha256(first).hexdigest(),'restartIdentical':True})
                page.close();stop()
        finally:browser.close()
finally:
    if proc and proc.poll() is None:
        proc.terminate();proc.wait(timeout=10)
    log.close()
manifest=APP.parent.parent/'Resources'/'BUILD.json'
(OUT/'receipt.json').write_text(json.dumps({'build':json.loads(manifest.read_text()),'executableSha256':hashlib.sha256(APP.read_bytes()).hexdigest(),'checks':receipts},indent=2)+'\n')
print(json.dumps(receipts,indent=2))
