"""Loopback-only prototype server; each native search runs in an isolated process."""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
import copy
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from engine import validate_job
from production import validate_identity, manifest, make_package
from folder_queue import FolderQueue
from output_folder import OutputFolder
from nesting import validate_request
from shop_profiles import validate_profile, inspect_output
from app_info import VERSION

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get('EZ_NEST_DATA', ROOT / '.local')).resolve()
WORK.mkdir(parents=True, exist_ok=True)
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
STATE = {'status': 'idle'}
PROCESS = None
PORT = int(os.environ.get('EZ_NEST_PORT', '8765'))
HOST = os.environ.get('EZ_NEST_HOST', '127.0.0.1')
FOLDER = FolderQueue(WORK / 'production-folder.json')
FOLDER_LOCK = threading.Lock()
OUTPUT = OutputFolder(WORK / 'output-folder.json')
DOCUMENT_LOCK = threading.Lock()


def apply_web_export(job, data):
    """Apply gear choices to the first freeze. Later sends reuse the same bytes."""
    if not isinstance(data, dict):
        return
    settings = job.setdefault('settings', {})
    if 'autoBleedMm' in data and data['autoBleedMm'] is not None:
        value = data['autoBleedMm']
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('Auto bleed must be from 0 to 25 mm.')
        value = float(value)
        if value != value or value < 0 or value > 25:
            raise ValueError('Auto bleed must be from 0 to 25 mm.')
        settings['autoBleedMm'] = value
    if 'drawRegmarks' in data and data['drawRegmarks'] is not None:
        if not isinstance(data['drawRegmarks'], bool):
            raise ValueError('Registration marks are on or off.')
        settings['drawRegmarks'] = data['drawRegmarks']
    if data.get('cutMapping') and isinstance(job.get('outputProfile'), dict):
        from cut_mapping import validate
        job['outputProfile']['cutMapping'] = validate(data['cutMapping'])


def batch_output_check(job):
    if job.get('documentSources'):
        from pdf_io import output_check
        return output_check(job, WORK/'documents')
    return inspect_output(job['outputProfile']) if job.get('outputProfile') else None


def persist_state():
    if STATE.get('status') == 'ready':
        snapshot = {k:v for k,v in STATE.items() if k not in ('output','incumbent')}
        temporary = WORK / 'session.tmp'
        temporary.write_text(json.dumps(snapshot), encoding='utf-8')
        temporary.replace(WORK / 'session.json')


def restore_state():
    try:
        saved = json.loads((WORK / 'session.json').read_text(encoding='utf-8'))
        if saved.get('status') == 'ready':
            from engine import validate_result
            validate_result(saved['job'], saved['result'])
            STATE.update(saved)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def finish_search(payload):
    incumbent = STATE.pop('incumbent', None)
    def score(result):
        fillers = sum(s['pieces'] for s in result.get('fillSummary', []))
        return (-fillers, result['usedLength'])
    if incumbent and (not payload.get('ok') or score(payload['result']) >= score(incumbent['result'])):
        STATE.clear()
        STATE.update(incumbent)
        STATE['note'] = 'Kept your best layout; this search did not improve it.' if payload.get('ok') else 'Kept your best layout; the new search could not return a valid improvement.'
    else:
        STATE.update(status='ready' if payload['ok'] else 'error', **payload)
        if incumbent:
            STATE['note'] = 'Found a better layout.'
    if STATE.get('status') == 'ready' and STATE.get('job', {}).get('productionJobs'):
        STATE['manifest'] = manifest(STATE['job'], STATE['result'], STATE['id'])
        check=batch_output_check(STATE['job'])
        if check: STATE['manifest']['outputCheck']=check
    persist_state()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, data, mime='application/json', filename=None):
        body = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_name(self, value):
        name, separator, port = (value or '').partition(':')
        if name not in ('127.0.0.1', 'localhost') or not separator:
            return False
        # The desktop app only accepts its own port. A container published on
        # another host port still sends a loopback Host name.
        return True if HOST != '127.0.0.1' else port == str(PORT)

    def allowed(self):
        return self.local_name(self.headers.get('Host'))

    def do_GET(self):
        if not self.allowed():
            return self.send(403, {'error': 'Invalid host'})
        path = urlparse(self.path).path
        if path == '/web/':
            path = '/web'
        if path == '/api/session':
            return self.send(200, {'token': TOKEN, 'app': 'eznest', 'version': VERSION})
        if path == '/api/output':
            return self.send(200, OUTPUT.status())
        if path == '/api/folder':
            with FOLDER_LOCK:
                return self.send(200, FOLDER.scan())
        if path == '/api/folder/file':
            try:
                query = parse_qs(urlparse(self.path).query)
                with FOLDER_LOCK:
                    content = FOLDER.read(query.get('id',[''])[0], query.get('revision',[''])[0])
                return self.send(200, {'text': content})
            except (ValueError, OSError) as error:
                return self.send(409, {'error': str(error)})
        if path.startswith('/api/batch/'):
            ident = path.rsplit('/',1)[-1]
            if len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
                return self.send(404, {'error':'Batch not found'})
            source = WORK / 'batches' / (ident+'.zip')
            if not source.exists():
                return self.send(404, {'error':'Batch not found'})
            return self.send(200, source.read_bytes(), 'application/zip', 'EZ-Nest-Batch-'+ident[:8]+'.zip')
        if path == '/api/state':
            with LOCK:
                if STATE.get('status') == 'running' and PROCESS.poll() is not None:
                    output = Path(STATE['output'])
                    if output.exists():
                        payload = json.loads(output.read_text())
                        finish_search(payload)
                    else:
                        finish_search({'ok': False, 'error': 'The engine stopped without returning a layout.'})
                public = {k: v for k, v in STATE.items() if k not in ('output', 'incumbent')}
                if public.get('status') == 'running' and STATE.get('output'):
                    progress = Path(STATE['output']).with_name('progress.json')
                    try:
                        live = json.loads(progress.read_text(encoding='utf-8'))
                        if live.get('ok') and live.get('result'):
                            public['live'] = live['result']
                    except (OSError, ValueError):
                        pass
            return self.send(200, public)
        if path == '/api/selection':
            source = WORK / 'selection.json'
            if not source.exists():
                return self.send(404, {'error': 'Capture paths in Illustrator first, or load the sample job.'})
            try:
                return self.send(200, json.loads(source.read_text(encoding='utf-8-sig')))
            except Exception:
                return self.send(400, {'error': 'Illustrator capture could not be read.'})
        static = {'/': ('production.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'), '/sample.json': ('sample.json', 'application/octet-stream')}
        static.update({'/svg-io.js': ('svg-io.js', 'text/javascript'), '/sample-artwork.svg': ('sample-artwork.svg', 'image/svg+xml')})
        static.update({'/queue-app.js': ('queue-app.js','text/javascript'), '/queue-core.js': ('queue-core.js','text/javascript'), '/queue.css': ('queue.css','text/css'), '/classic': ('classic.html','text/html')})
        static['/production-features.js']=('production-features.js','text/javascript')
        static['/cut-mapping.js']=('cut-mapping.js','text/javascript')
        static['/shop-profiles.js'] = ('shop-profiles.js','text/javascript')
        static['/web'] = ('web.html', 'text/html')
        static['/web.css'] = ('web.css', 'text/css')
        static['/web.js'] = ('web.js', 'text/javascript')
        static['/fonts/rajdhani-700.woff2'] = ('fonts/rajdhani-700.woff2', 'font/woff2')
        static['/fonts/red-hat-display-400.woff2'] = ('fonts/red-hat-display-400.woff2', 'font/woff2')
        static['/fonts/red-hat-display-700.woff2'] = ('fonts/red-hat-display-700.woff2', 'font/woff2')
        if os.environ.get('EZ_NEST_TEST_UI') == '1':
            static.update({'/tests/svg-tests.html': ('tests/svg-tests.html', 'text/html'), '/tests/svg-tests.js': ('tests/svg-tests.js', 'text/javascript')})
        if path not in static:
            return self.send(404, {'error': 'Not found'})
        name, mime = static[path]
        return self.send(200, (ROOT / name).read_bytes(), mime)

    def do_POST(self):
        global PROCESS
        if not self.allowed() or self.headers.get('X-EZ-Token') != TOKEN:
            return self.send(403, {'error': 'Invalid session'})
        origin = self.headers.get('Origin')
        if origin and not self.local_name(origin.removeprefix('http://')):
            return self.send(403, {'error': 'Invalid origin'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= 48_000_000:
                raise ValueError('Job is too large.')
            data = json.loads(self.rfile.read(size) or '{}')
            if self.path == '/api/document/import':
                if not DOCUMENT_LOCK.acquire(blocking=False):
                    raise ValueError('Wait for the current document import to finish.')
                ident=uuid.uuid4().hex
                request,output=WORK/(ident+'-import.json'),WORK/(ident+'-import-result.json')
                try:
                    request.write_text(json.dumps(data),encoding='utf-8')
                    worker=[sys.executable,'--document-worker'] if getattr(sys,'frozen',False) else [sys.executable,str(ROOT/'pdf_io.py')]
                    subprocess.run([*worker,str(request),str(output)],cwd=WORK,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120,check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    payload=json.loads(output.read_text(encoding='utf-8'))
                    if not payload['ok']: raise ValueError(payload['error'])
                    return self.send(200,payload['document'])
                except subprocess.TimeoutExpired:
                    raise ValueError('PDF import took too long. Use a smaller print-only document.')
                finally:
                    request.unlink(missing_ok=True); output.unlink(missing_ok=True)
                    DOCUMENT_LOCK.release()
            if self.path in ('/api/output/connect', '/api/output/pick'):
                if self.path.endswith('/pick'):
                    data = {'path': pick_folder('Select where eznest will save print packs')}
                    if not data['path']:
                        return self.send(200, {'cancelled': True})
                with FOLDER_LOCK:
                    return self.send(200, OUTPUT.connect(data.get('path',''), FOLDER.root))
            if self.path.startswith('/api/folder/'):
                if self.path == '/api/folder/pick':
                    if os.name != 'nt':
                        raise ValueError('Use the folder path field on this platform.')
                    script = "Add-Type -AssemblyName System.Windows.Forms; $picker=New-Object System.Windows.Forms.FolderBrowserDialog; $picker.Description='Select your print-ready SVG production folder'; $picker.ShowNewFolderButton=$false; if($picker.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Console]::Write($picker.SelectedPath)}"
                    selected = subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',script],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=300)
                    folder_path = selected.stdout.decode('utf-8-sig').strip()
                    if not folder_path:
                        return self.send(200, {'cancelled': True})
                    data = {'path':folder_path}
                with FOLDER_LOCK:
                    if self.path in ('/api/folder/connect','/api/folder/pick'):
                        root = Path(data['path']).expanduser().resolve(strict=True)
                        if OUTPUT.root and OUTPUT.root.resolve().is_relative_to(root):
                            raise ValueError('The source folder must not contain your output folder.')
                        result = FOLDER.connect(data['path'])
                    elif self.path == '/api/folder/disconnect':
                        FOLDER.disconnect()
                        result = {'connected':False,'files':[]}
                    else:
                        raise ValueError('Unknown folder action.')
                return self.send(200,result)
            with LOCK:
                if self.path in ('/api/solve', '/api/improve'):
                    if STATE.get('status') == 'running':
                        raise ValueError('Cancel the current search before starting another.')
                    incumbent = None
                    if self.path == '/api/improve':
                        if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id'):
                            raise ValueError('Calculate a current layout before improving it.')
                        if STATE.get('released'):
                            raise ValueError('This batch is frozen. Start a new layout to make changes.')
                        incumbent = copy.deepcopy(STATE)
                        data = copy.deepcopy(STATE.get('requestJob', STATE['job']))
                        data['settings']['seed'] = secrets.randbelow(2147483647)
                    validate_request(data)
                    if data.get('documentSources'):
                        from pdf_io import load_documents
                        complete={**data,'productionJobs':data.get('productionJobs',[])+[f['source'] for f in data.get('fillJobs',[])],
                                  'parts':data['parts']+[p for f in data.get('fillJobs',[]) for p in f['parts']]}
                        load_documents(complete,WORK/'documents')
                    if 'outputProfile' in data:
                        data['outputProfile'] = validate_profile(data['outputProfile'])
                    run_id = uuid.uuid4().hex
                    directory = WORK / run_id
                    directory.mkdir()
                    request, output = directory / 'job.json', directory / 'result.json'
                    request.write_text(json.dumps(data), encoding='utf-8')
                    worker = [sys.executable, '--nest-worker'] if getattr(sys, 'frozen', False) else [sys.executable, str(ROOT / 'nesting.py')]
                    PROCESS = subprocess.Popen([*worker, str(request), str(output)], cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    STATE.clear()
                    STATE.update(status='running', id=run_id, output=str(output), job=data)
                    if incumbent:
                        STATE['incumbent'] = incumbent
                elif self.path == '/api/cancel':
                    keep = data.get('keepBest') is True
                    if PROCESS and PROCESS.poll() is None:
                        PROCESS.terminate()
                        PROCESS.wait(timeout=5)
                    live = None
                    if keep and STATE.get('status') == 'running' and STATE.get('output'):
                        try:
                            payload = json.loads(Path(STATE['output']).with_name('progress.json').read_text(encoding='utf-8'))
                            if payload.get('ok') and payload.get('result'):
                                live = payload['result']
                        except (OSError, ValueError):
                            live = None
                    if live:
                        STATE.pop('incumbent', None)
                        STATE.pop('output', None)
                        STATE.update(status='ready', ok=True, result=live, note='Stopped. This is the best layout so far.')
                        if STATE.get('job', {}).get('productionJobs'):
                            STATE['manifest'] = manifest(STATE['job'], STATE['result'], STATE['id'])
                            check = batch_output_check(STATE['job'])
                            if check:
                                STATE['manifest']['outputCheck'] = check
                    else:
                        incumbent = STATE.get('incumbent')
                        STATE.clear()
                        STATE.update(incumbent or {'status': 'cancelled', 'note': 'Stopped before a layout was ready.'})
                        if incumbent:
                            STATE['note'] = 'Search cancelled; your best layout is retained.'
                    persist_state()
                elif self.path == '/api/output/undo':
                    if STATE.get('status') != 'ready' or not STATE.get('released') or data.get('id') != STATE.get('id'):
                        raise ValueError('Send a layout before undoing it.')
                    if not OUTPUT.root:
                        raise ValueError('No hot folder is set.')
                    import shutil
                    root = OUTPUT.root.resolve(strict=True)
                    destination = root / ('eznest-' + STATE['id'])
                    if not destination.is_dir() or destination.is_symlink() or not destination.resolve().is_relative_to(root):
                        raise ValueError('That file is no longer in the hot folder.')
                    shutil.rmtree(destination)
                    return self.send(200, {'ok': True})
                elif self.path == '/api/shutdown':
                    if STATE.get('status') == 'running':
                        raise ValueError('Stop the current search before closing eznest.')
                    persist_state()
                    self.send(200, {'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif self.path == '/api/release':
                    if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id'):
                        raise ValueError('Calculate and review the current layout before exporting.')
                    if not STATE.get('released'):
                        apply_web_export(STATE['job'], data)
                    check = batch_output_check(STATE['job'])
                    if check and not check['ready'] and data.get('workingOnly') is not True:
                        raise ValueError('This layout does not meet the shop output requirements. Save working files explicitly or use a supported output profile.')
                    if not STATE.get('released'):
                        documents=None
                        if STATE['job'].get('documentSources'):
                            from pdf_io import load_documents
                            documents=load_documents(STATE['job'],WORK/'documents')
                        content, details = make_package(STATE['job'],STATE['result'],STATE['id'],data.get('artwork'),data['map'],documents,check)
                        directory = WORK / 'batches'
                        directory.mkdir(exist_ok=True)
                        temporary = directory / (STATE['id']+'.tmp')
                        temporary.write_bytes(content)
                        temporary.replace(directory / (STATE['id']+'.zip'))
                        STATE.update(released=True, manifest=details, deliveryCompleted=False)
                        persist_state()
                    package = (WORK/'batches'/(STATE['id']+'.zip')).read_bytes()
                    digest = hashlib.sha256(package).hexdigest()
                    with FOLDER_LOCK:
                        saved = OUTPUT.save(STATE['id'], package, FOLDER.root)
                    STATE.update(deliveryCompleted=bool(saved) or STATE.get('deliveryCompleted',False), savedPath=saved, sha256=digest)
                    persist_state()
                    return self.send(200, {'ok':True,'id':STATE['id'],'url':'/api/batch/'+STATE['id'], 'savedPath':saved,'outputCheck':check,'deliveryCompleted':STATE['deliveryCompleted'],'sha256':digest})
                elif self.path == '/api/delivery/complete':
                    if STATE.get('status')!='ready' or data.get('id')!=STATE.get('id') or not STATE.get('released') or not (WORK/'batches'/(STATE['id']+'.zip')).is_file():
                        raise ValueError('Download the current frozen batch before completing its delivery.')
                    STATE['deliveryCompleted']=True
                    persist_state()
                    return self.send(200,{'ok':True})
                elif self.path == '/api/prepare-apply':
                    if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id'):
                        raise ValueError('Calculate a current validated layout first.')
                    if not STATE['job'].get('captureId'):
                        raise ValueError('Sample jobs cannot be applied to Illustrator. Capture your own paths first.')
                    payload = {'captureId': STATE['job']['captureId'], 'runId': STATE['id'], 'result': STATE['result']}
                    (WORK / 'apply.json').write_text(json.dumps(payload), encoding='utf-8')
                else:
                    return self.send(404, {'error': 'Not found'})
            self.send(200, {'ok': True})
        except Exception as error:
            self.send(400, {'error': str(error)})


def pick_folder(description):
    if os.name != 'nt':
        raise ValueError('Enter the folder path on this platform.')
    script = "Add-Type -AssemblyName System.Windows.Forms; $picker=New-Object System.Windows.Forms.FolderBrowserDialog; $picker.Description='"+description+"'; if($picker.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Console]::Write($picker.SelectedPath)}"
    selected = subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',script],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=300)
    return selected.stdout.decode('utf-8-sig').strip()


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(open_browser=False, page='/'):
    restore_state()
    service = LocalServer((HOST, PORT), Handler)
    if open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{PORT}{page}')
    if sys.stdout:
        print(f'eznest ready: http://127.0.0.1:{PORT}{page}', flush=True)
    try:
        service.serve_forever()
    finally:
        service.server_close()


if __name__ == '__main__':
    serve()
