"""Hosted native window verification with synthetic loopback responses; no installed data."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HTML = b'''<!doctype html><title>EZNest native window checks</title>
<style>body{font:20px system-ui;margin:60px;color:#202621;background:#f7f8f3}button,a,input{margin:20px}</style>
<h1>EZNest native window</h1><p>Synthetic native integration fixture</p>
<input id="file" type="file" multiple>
<a id="external" href="https://output.jeezlabs.io/workspace">OUTPUT</a>
<a id="bad" href="file:///etc/passwd">Blocked URL fixture</a>
<button id="download">Save synthetic file</button>
<button id="popup">Connect OUTPUT</button>
<button id="update" onclick="location.href='eznest-update://install'">Request checked update</button>
<script>
window.EZNStartup = {state: location.search ? 'ready' : 'waiting'};
setTimeout(() => window.EZNStartup.state = 'ready', 5500);
// This executes from page startup, not from WKWebView.evaluateJavaScript,
// whose host-injected scripts can carry a synthetic WebKit user gesture.
if(!location.search)setTimeout(()=>window.open('https://output.jeezlabs.io/workspace'),100);
document.querySelector('#file').onchange=async event=>{document.body.dataset.imported=await event.target.files[0].text()};
document.querySelector('#download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['EZNest native export'],{type:'text/plain'}));a.download='native-export.txt';document.body.append(a);a.click();a.remove()};
let popupAttempts=0;
document.querySelector('#popup').onclick=()=>{const p=window.open('', '_blank');popupAttempts++;setTimeout(()=>{if(p){if(popupAttempts===1)p.close();else p.location.href='https://output.jeezlabs.io/workspace'}},40)};
</script>'''


def actual_workspace(executable, out):
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / 'tests')]
    import opt_out  # Keep OUTPUT remote features and opt-ins closed in source verification.
    import server as workspace
    import shop_test
    from macos_svg_acceptance import SVG
    from test_macos_svg_flow import SourceAPI
    from test_published_macos import validate_export

    folder = out / 'workspace'; folder.mkdir()
    (folder / 'synthetic.svg').write_bytes(SVG)
    workspace.WORK = folder / 'data'
    shop_test.prepare(workspace.WORK)
    import shop_members
    shop_members.create(workspace.WORK, 'Native UI test shop')
    workspace.OUTPUT = workspace.OutputFolder(workspace.WORK / 'output-folder.json')
    workspace.STATE.clear(); workspace.STATE.update(status='idle')

    class Handler(workspace.Handler):
        def log_message(self, *_):
            pass

        def session_body(self):
            # The separately compiled verifier accepts this scratch server as
            # its fixture service. No real daemon, root install or user data is
            # impersonated; normal source API/CSRF checks remain active.
            value = super().session_body()
            return {**value, 'shopService': True}

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    workspace.PORT = http.server_port
    thread = threading.Thread(target=http.serve_forever); thread.start()
    origin = f'http://127.0.0.1:{http.server_port}'
    try:
        version = json.loads((root / 'version.json').read_text())['version']
        subprocess.run([str(executable.resolve()), origin, str(os.getpid()), str(folder),
                        'workspace', version], check=True, timeout=120)
        receipt = json.loads((folder / 'receipt.json').read_text())
        assert all(receipt['checks'].values())
        api = SourceAPI(origin)
        status, state = api.request('/api/state')
        assert status == 200 and state['released'] and len(state['result']['placements']) == 2
        content = (folder / 'workspace.zip').read_bytes()
        validate_export(content, 'svg', state['id'])
        status, frozen = api.exchange('/api/batch/' + state['id'])
        assert status == 200 and frozen == content
        assert api.request('/api/telemetry/output')[1]['enabled'] is False
        print('PASS: actual WKWebView SVG pack matches the frozen source batch; sharing off')
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=5)
        if workspace.PROCESS and workspace.PROCESS.poll() is None:
            workspace.PROCESS.terminate(); workspace.PROCESS.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--real-workspace', action='store_true')
    parser.add_argument('--local', action='store_true', help='Use a new scratch directory on this Mac, with synthetic service/data only.')
    args = parser.parse_args()
    hosted = os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
    if sys.platform != 'darwin' or not (hosted or args.local):
        raise SystemExit('Use the disposable hosted Mac, or explicitly opt into --local synthetic verification.')
    out = args.out.resolve()
    root = out.parent if args.local else Path(os.environ['RUNNER_TEMP']).resolve()
    if args.local and out.is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit('Keep local runtime artifacts outside the source checkout.')
    if out.exists() or not out.is_relative_to(root) or out == root:
        raise SystemExit('Use a new directory inside this hosted runner temp.')
    out.mkdir()
    if args.real_workspace:
        actual_workspace(args.executable, out)
        return
    for mode in ('valid', 'wrong-pid', 'wrong-version', 'redirect'):
        folder = out / mode; folder.mkdir()
        (folder / 'synthetic.txt').write_text('synthetic native import')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == '/api/session':
                    if mode == 'valid':
                        time.sleep(.25)  # A reload must cancel/ignore the older probe.
                    if mode == 'redirect':
                        self.send_response(302); self.send_header('Location', 'https://example.com/'); self.end_headers(); return
                    body = json.dumps({'app': 'eznest', 'version': 'wrong' if mode == 'wrong-version' else '1.0.0-rc.6',
                                       'shopService': True, 'pid': os.getpid() + (1 if mode == 'wrong-pid' else 0)}).encode()
                else:
                    body = HTML
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if self.path == '/api/session' else 'text/html')
                self.send_header('Content-Length', str(len(body))); self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass  # The retry case deliberately cancels the older probe.

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever); thread.start()
        try:
            subprocess.run([str(args.executable.resolve()), f'http://127.0.0.1:{server.server_port}',
                            str(os.getpid()), str(folder), mode], check=True, timeout=45)
            receipt = json.loads((folder / 'receipt.json').read_text())
            assert receipt['mode'] == mode and all(receipt['checks'].values())
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    print('PASS: native window, reopen, file picker, blob save, loopback identity and redirect refusal')


if __name__ == '__main__':
    main()
