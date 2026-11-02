"""Hosted native window verification with synthetic loopback responses; no installed data."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

HTML = b'''<!doctype html><title>EZNest native window checks</title>
<style>body{font:20px system-ui;margin:60px;color:#202621;background:#f7f8f3}button,a,input{margin:20px}</style>
<h1>EZNest native window</h1><p>Synthetic native integration fixture</p>
<input id="file" type="file" multiple>
<a id="external" href="https://output.jeezlabs.io/workspace">OUTPUT</a>
<a id="bad" href="file:///etc/passwd">Blocked URL fixture</a>
<button id="download">Save synthetic file</button>
<script>
document.querySelector('#file').onchange=async event=>{document.body.dataset.imported=await event.target.files[0].text()};
document.querySelector('#download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['EZNest native export'],{type:'text/plain'}));a.download='native-export.txt';document.body.append(a);a.click();a.remove()};
</script>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if (sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise SystemExit('Native UI verification runs only on the disposable hosted Mac.')
    root = Path(os.environ['RUNNER_TEMP']).resolve()
    out = args.out.resolve()
    if out.exists() or not out.is_relative_to(root) or out == root:
        raise SystemExit('Use a new directory inside this hosted runner temp.')
    out.mkdir()
    for mode in ('valid', 'wrong-pid', 'wrong-version', 'redirect'):
        folder = out / mode; folder.mkdir()
        (folder / 'synthetic.txt').write_text('synthetic native import')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == '/api/session':
                    if mode == 'redirect':
                        self.send_response(302); self.send_header('Location', 'https://example.com/'); self.end_headers(); return
                    body = json.dumps({'app': 'eznest', 'version': 'wrong' if mode == 'wrong-version' else '1.0.0-rc.6',
                                       'shopService': True, 'pid': os.getpid() + (1 if mode == 'wrong-pid' else 0)}).encode()
                else:
                    body = HTML
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if self.path == '/api/session' else 'text/html')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

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
