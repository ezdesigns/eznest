"""Exercise a built macOS bundle with synthetic SVG/PDF data and restart checks.

Requires the source test dependencies and Playwright with installed Chrome/Edge.
Only the explicit new output directory is written. No app installation or signing.
"""
import argparse, hashlib, io, json, os, socket, subprocess, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
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

def ready(page):
    page.wait_for_function("() => document.body.dataset.ready === '1'")
    if page.locator('#feedback-welcome').is_visible():
        page.click('#feedback-dismiss')

def download(page,target):
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
                assert session['account']['ready'] is False and session['account']['devMode'] is False
                try:
                    request('/api/solve', {})
                    raise AssertionError('Fresh frozen host bypassed first authorization')
                except HTTPError as error:
                    assert error.code == 403 and json.load(error)['code'] == 'sign_in_required'
                stop()
                # Only this newly created scratch folder is seeded. --shop-test
                # keeps all remote delivery off in the unchanged frozen binary.
                # This is offline authorization proof, never live Privy sign-in.
                import output_credential, output_gate
                output_credential.save(folder/'data', 'osa_'+'C'*43, 'Synthetic frozen CI fixture')
                output_gate.note_paired(folder/'data', now=int(time.time())-120*86400)
                session=start(folder/'data')
                assert session['account']['ready'] is True and session['account']['devMode'] is False
                assert request('/api/telemetry/output')['enabled'] is False
                page=browser.new_page(viewport={'width':1280,'height':900},accept_downloads=True)
                page.goto(URL+'/?view=simple')
                ready(page)
                page.click('#edit-material')
                page.fill('#preset-name', 'CI synthetic frozen stock')
                page.select_option('#unit','mm')
                page.fill('#roll','230')
                page.fill('#width','220')
                page.click('#save-material')
                page.wait_for_function("() => !document.querySelector('#material-dialog').open")
                page.wait_for_function("() => !document.querySelector('#save-material').disabled")
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
                page.reload();ready(page)
                print('FROZEN_STAGE:',kind,'restored',restored.get('status'),bool(restored.get('manifest')),
                      page.locator('body').get_attribute('data-step'),flush=True)
                assert download(page,folder/'restored.zip')==first
                receipts.append({'format':kind,'pieces':len(state['result']['placements']),'sha256':hashlib.sha256(first).hexdigest(),'restartIdentical':True})
                page.close();stop()
        finally:browser.close()
finally:
    if proc and proc.poll() is None:
        proc.terminate();proc.wait(timeout=10)
    log.close()
manifest=APP.parent.parent/'Resources'/'BUILD.json'
(OUT/'receipt.json').write_text(json.dumps({'build':json.loads(manifest.read_text()),'executableSha256':hashlib.sha256(APP.read_bytes()).hexdigest(),'firstAuthorizationRequired':True,'authorizationFixture':'synthetic-protected-receipt-remote-disabled','liveSignInVerified':False,'checks':receipts},indent=2)+'\n')
print(json.dumps(receipts,indent=2))
