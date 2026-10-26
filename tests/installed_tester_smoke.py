"""Browser acceptance for the installed tester on a disposable Windows runner.

The reusable browser checks can also exercise an isolated packaged test server;
only main() starts the installed app against the runner's default trial data.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def request(url, path, data=None, token=None):
    headers={'Content-Type':'application/json'}
    if token:headers['X-EZ-Token']=token
    req=Request(url+path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
    with urlopen(req,timeout=15) as response:return json.load(response)


def browser_check(url, report_dir, build_id, output_dir):
    from playwright.sync_api import sync_playwright, expect
    from test_mixed_cuts import mixed_fixture
    from test_web_mvp import launch_browser
    from pdf_io import read_document
    from cut_mapping import defaults
    shop=request(url,'/api/shop')
    assert shop['buildId']==build_id
    assert not any(shop.get(k) for k in ('runningLan','outputNetwork','updates'))
    with sync_playwright() as playwright:
        browser=launch_browser(playwright)
        page=browser.new_page(viewport={'width':1366,'height':768})
        try:
            page.goto(url+'/web')
            page.wait_for_function("() => document.body.dataset.ready === '1'")
            expect(page.locator('#setup')).to_be_hidden()
            expect(page.locator('#file')).to_be_enabled()
            page.screenshot(path=str(report_dir/'first-run.png'),full_page=True)
            page.locator('#layout-options').evaluate('n => { n.open = true }')
            page.select_option('#nesting-effort','5')
            source=mixed_fixture()
            page.set_input_files('#file',{'name':'synthetic-kit.pdf','mimeType':'application/pdf','buffer':source})
            page.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
            state=request(url,'/api/state')
            assert len(state['job']['parts'])==2
            assert state['manifest']['cutSummary']=={'thru':2,'kiss':4,'contour':0}
            assert len(state['result'].get('sheets') or [1])==1
            expect(page.locator('#export')).to_be_enabled()
            page.screenshot(path=str(report_dir/'nested.png'),full_page=True)
            page.click('#feedback-open')
            expect(page.locator('#feedback-numbers')).not_to_be_checked()
            expect(page.locator('#feedback-version')).to_contain_text(build_id)
            assert 'synthetic-kit' not in page.inner_text('#feedback-preview')
            page.click('#feedback-close')
            page.click('#export')
            page.select_option('#save-format','pdf')
            page.select_option('#save-destination','folder')
            page.click('#confirm-send')
            page.wait_for_function("() => document.body.dataset.step === 'sent'",timeout=30000)
            state=request(url,'/api/state')
            target=Path(state['exportReceipt']['path']).resolve()
            assert target.parent==output_dir.resolve() and target.name=='synthetic-kit.pdf'
            raw=target.read_bytes()
            _,meta=read_document(raw,cut_mapping=defaults())
            assert len(meta['pieces'])==2
            assert sum(len(p['cutPaths']) for p in meta['pieces'])==6
            page.reload()
            page.wait_for_function("() => document.body.dataset.ready === '1'")
            expect(page.locator('#delivery-receipt')).to_contain_text('synthetic-kit.pdf')
            page.screenshot(path=str(report_dir/'saved-and-reloaded.png'),full_page=True)
            return {'state':state,'savedPath':str(target),'savedSha256':hashlib.sha256(raw).hexdigest()}
        finally:browser.close()


def restart_check(url, checked):
    state=request(url,'/api/state')
    for key in ('id','job','result','exportReceipt'):
        assert state[key]==checked['state'][key],f'Restart changed {key}'
    assert hashlib.sha256(Path(checked['savedPath']).read_bytes()).hexdigest()==checked['savedSha256']


def main():
    # Do not move this guard below argument parsing, filesystem writes or launch.
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('Installed-tester acceptance is restricted to disposable GitHub-hosted runners.')
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--build-id',required=True)
    args=parser.parse_args()
    exe=args.exe.resolve();report=args.report_dir.resolve()
    trial=Path(os.environ['LOCALAPPDATA'])/'eznest-shop-trial'
    expected=Path(os.environ['LOCALAPPDATA'])/'Programs'/'EZ Nest Tester'/args.build_id/'app'/'eznest.exe'
    if exe!=expected.resolve() or not exe.is_file() or trial.exists():
        raise RuntimeError('Expected a fresh default tester installation with no prior trial data.')
    if not report.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()):
        raise RuntimeError('Keep acceptance reports in the disposable runner temp directory.')
    report.mkdir(parents=True,exist_ok=True)
    with socket.socket() as probe:probe.bind(('127.0.0.1',8765))
    url='http://127.0.0.1:8765';process=None;token=None
    def start():
        nonlocal process,token
        process=subprocess.Popen([str(exe),'--shop-test','--no-browser'],creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            try:
                session=request(url,'/api/session')
                assert session['pid']==process.pid and session['app']=='eznest'
                token=session['token']
                addresses=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',
                    f'@(Get-NetTCPConnection -OwningProcess {process.pid} -State Listen).LocalAddress | ConvertTo-Json -Compress'],text=True,timeout=15))
                if isinstance(addresses,str):addresses=[addresses]
                assert addresses and all(address=='127.0.0.1' for address in addresses),'Installed tester opened a non-loopback listener.'
                return
            except (URLError,TimeoutError):
                if process.poll() is not None:raise RuntimeError('Installed app exited during startup.')
                time.sleep(.2)
        raise TimeoutError('Installed app did not start within 60 seconds.')
    def stop():
        nonlocal process,token
        if process is not None and process.poll() is None:
            if token:request(url,'/api/shutdown',{},token)
            process.wait(timeout=20)
        process=None;token=None
    try:
        start()
        checked=browser_check(url,report,args.build_id,trial/'TEST Output')
        stop();start();restart_check(url,checked);stop()
        summary={'passed':True,'buildId':args.build_id,'pieces':2,'cuts':6,'outputSha256':checked['savedSha256'],
                 'checks':['installed executable','default trial isolation','browser first run','PDF import and nesting',
                           'vector PDF save to local TEST Output','feedback opt-in defaults','browser reload','process restart'],
                 'notVerified':['default browser auto-open','native Windows Save As interaction','standard-user account','physical printing/cutting','signed upgrade/rollback']}
        (report/'app-validation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    finally:
        if process is not None and process.poll() is None:
            try:stop()
            except Exception:
                # Only terminate the subprocess created above, never another listener.
                process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
