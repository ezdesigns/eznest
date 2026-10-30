"""Local shop server. Loopback by default; the shop network is an explicit option."""
import hashlib
from zipfile import ZipFile
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
import copy
import socket
import sqlite3
import ssl
import workload
import output_gate
import output_pairing
import telemetry
import telemetry_sender
import material_inventory
import macos_service_runtime
import illustrator_bridge
import shop_auth
from import_limits import request_limit
import print_export
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from engine import validate_job
from production import validate_identity, manifest, make_package
from folder_queue import FolderQueue, real_directory
from output_folder import OutputFolder, stage_pack
from nesting import validate_request
from shop_profiles import validate_profile, inspect_output
from app_info import VERSION
from shop_deploy import OUTPUT_NOTE, WARNING, approve_source_root, default_hot_folder, host_name, issues_url, lan_addresses, load_shop, output_network_status, output_status, peek_latest, pull_latest, save_shop, shop_name_allowed, updates_allowed, EZ_PRESET

ROOT = Path(__file__).resolve().parent
_STATIC_CACHE = {}


def remove_import_temp(path):
    """Windows may briefly retain a scan/worker handle on a large upload."""
    for attempt in range(50):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.1)


def static_bytes(name):
    """Read a shop file, retrying when Windows briefly locks it."""
    cached = _STATIC_CACHE.get(name)
    if cached is not None:
        return cached
    path = ROOT / name
    last = None
    for _ in range(8):
        try:
            data = path.read_bytes()
        except OSError as error:
            last = error
            time.sleep(0.05)
            continue
        _STATIC_CACHE[name] = data
        return data
    raise last


WORK = Path(os.environ.get('EZ_NEST_DATA', ROOT / '.local')).resolve()
WORK.mkdir(parents=True, exist_ok=True)
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
OPERATIONS = threading.RLock()
from update_queue import UpdateQueue
UPDATE_QUEUE = UpdateQueue()
UPDATE_CHECK = {}
UPDATE_WAKE = threading.Event()
STATE = {'status': 'idle'}
PROCESS = None
PORT = int(os.environ.get('EZ_NEST_PORT', '8765'))
HOST = os.environ.get('EZ_NEST_HOST', '127.0.0.1')
LAN = os.environ.get('EZ_NEST_LAN', '') == '1'
TLS = False
TLS_CONTEXT = None


def _protect_tls_key(path):
    """Refuse a POSIX key other accounts can read. On Windows, tighten the ACL."""
    if os.name == 'nt':
        command = ['icacls', str(path), '/inheritance:r', '/grant:r', '*S-1-5-18:(R)', '*S-1-5-32-544:(R)']
        user = os.environ.get('USERNAME', '')
        if user and all(mark not in user for mark in '*?"<>|'):
            command.extend(['/grant:r', user + ':(R)'])
        service = subprocess.run(command + ['/grant:r', 'eznest-svc:(R)'], capture_output=True)
        if service.returncode != 0:
            narrowed = subprocess.run(command, capture_output=True)
            if narrowed.returncode != 0:
                raise ValueError(
                    'Could not restrict the TLS private key. Run: '
                    'icacls KEY /inheritance:r /grant:r *S-1-5-18:(R) *S-1-5-32-544:(R) eznest-svc:(R)'
                )
        return
    if path.stat().st_mode & 0o077:
        raise ValueError(
            'The TLS private key is readable by the group or by other accounts. '
            f'Run: chmod 600 {path}'
        )


def configure_tls(cert=None, key=None):
    """Optional local HTTPS. Both files are required. Empty values leave HTTP."""
    global TLS, TLS_CONTEXT
    cert = (cert or '').strip()
    key = (key or '').strip()
    if not cert and not key:
        TLS = False
        TLS_CONTEXT = None
        return
    if not cert or not key:
        raise ValueError('Set both the TLS certificate and the TLS key, or neither.')
    cert_path, key_path = Path(cert), Path(key)
    if not cert_path.is_file() or not key_path.is_file() or cert_path.is_symlink() or key_path.is_symlink():
        raise ValueError('The TLS certificate and key must be regular files on this computer.')
    _protect_tls_key(key_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    TLS_CONTEXT = context
    TLS = True


def _approved_source_roots():
    return load_shop(WORK)['sourceRoots']


FOLDER = FolderQueue(WORK / 'production-folder.json', approved=_approved_source_roots)
FOLDER_LOCK = threading.Lock()
OUTPUT = OutputFolder(WORK / 'output-folder.json')
DOCUMENT_LOCK = threading.Lock()


def shop_status():
    saved = load_shop(WORK)
    build_id = ''
    if getattr(sys, 'frozen', False):
        try:
            trial = json.loads((Path(sys.executable).parent.parent / 'BUILD.json').read_text(encoding='utf-8'))
            value = trial.get('buildId', '')
            if isinstance(value, str) and len(value) <= 64 and all(c.isalnum() or c in '-._' for c in value):
                build_id = value
        except (OSError, ValueError):
            pass
    running = LAN and HOST == '0.0.0.0'
    name = host_name()
    return {
        'version': VERSION,
        'buildId': build_id,
        'onyxPc': saved['onyxPc'],
        'lan': saved['lan'],
        'updates': saved['updates'],
        'channel': saved['channel'],
        'testChannel': saved['channel'] == 'test',
        'outputNetwork': saved['outputNetwork'],
        'outputNote': OUTPUT_NOTE,
        'outputShare': output_network_status(saved),
        'setupComplete': saved['setupComplete'],
        'printer': saved['printer'],
        'units': saved['units'],
        'thru': saved['thru'],
        'kiss': saved['kiss'],
        'hotFolder': saved['hotFolder'],
        'preset': EZ_PRESET,
        'issuesUrl': issues_url(WORK),
        'runningLan': running,
        'restart': saved['lan'] != running,
        'lanWaiting': os.environ.get('EZ_NEST_LAN_WAITING') == 'pin' and not running,
        'port': PORT,
        'name': name,
        'addresses': lan_addresses(),
        'url': f'http://{name}:{PORT}/web',
        'warning': WARNING,
        'hotFolderDefault': default_hot_folder(saved['onyxPc']),
        **output_status(WORK),
    }


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


def record_workload(kind):
    # A statistics failure must not turn a successful delivery into a failed Send.
    try:
        ident = illustrator_bridge.tracking_id(STATE.get('job', {}), STATE['id'])
        workload.record(WORK, ident, kind, STATE['result'])
        STATE.pop('trackingWarning', None)
    except (OSError, sqlite3.Error, ValueError):
        STATE['trackingWarning'] = 'Local activity could not be saved. Check available disk space and folder permissions.'
    if kind == 'prepared':
        record_telemetry('nest.committed')
    elif kind == 'sent_to_folder':
        # A default save folder may be ordinary storage, not a RIP queue.
        try:
            hot = load_shop(WORK).get('hotFolder')
            is_hot = bool(hot and OUTPUT.root and Path(hot).resolve() == OUTPUT.root.resolve())
        except Exception:
            is_hot = False
        record_telemetry('nest.sent_to_print' if is_hot else 'nest.exported')
    elif kind == 'removed_from_folder':
        record_telemetry('nest.removed_from_folder')


def telemetry_paused():
    if UPDATE_QUEUE.stopping:
        return True
    # The optional Mac shop-service companion closes admission durably across
    # restart/recovery. Its absence in a claimed service environment fails closed.
    if os.environ.get('EZ_NEST_MACOS_SERVICE') == '1':
        try:
            from macos_service_runtime import maintenance
        except ImportError:
            return True
        return maintenance()
    return False


def record_telemetry(kind):
    # Observability cannot break a valid nest, export or print-folder delivery.
    try:
        telemetry.observe(WORK, STATE['id'], STATE['job'], STATE['result'], kind)
        STATE.pop('telemetryWarning', None)
    except Exception:
        STATE['telemetryWarning'] = 'Local job tracking could not be saved. The layout and file operation are unaffected.'


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
    search_seconds = STATE.get('job', {}).get('settings', {}).get('seconds')
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
    if incumbent and STATE.get('status') == 'ready':
        if search_seconds is not None:
            STATE['job']['settings']['seconds'] = search_seconds
            if STATE.get('requestJob'):
                STATE['requestJob']['settings']['seconds'] = search_seconds
        # Only compare equal quantities. Filler jobs can trade length for more
        # pieces, which is not a like-for-like material saving.
        if score(STATE['result'])[0] == score(incumbent['result'])[0]:
            baseline = incumbent.get('nestSavings', {}).get('baselineLengthMm', incumbent['result']['usedLength'])
            saved = max(0, baseline - STATE['result']['usedLength'])
            STATE['nestSavings'] = {'baselineLengthMm': baseline, 'savedLengthMm': saved,
                                    'percent': 100 * saved / baseline if baseline > 0 else 0}
        else:
            STATE.pop('nestSavings', None)
    if STATE.get('status') == 'ready' and STATE.get('job', {}).get('productionJobs'):
        STATE['manifest'] = manifest(STATE['job'], STATE['result'], STATE['id'])
        check=batch_output_check(STATE['job'])
        if check: STATE['manifest']['outputCheck']=check
    if STATE.get('status') == 'ready':
        record_telemetry('nest.created')
    persist_state()


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 so a stylesheet or script queued on the same connection is answered.
    # Closing after the page was dropping that next file on Windows.
    protocol_version = 'HTTP/1.1'
    timeout = 30

    def log_message(self, *args):
        pass

    def send(self, status, data, mime='application/json', filename=None, extra_headers=None):
        body = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        for key, value in extra_headers or ():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    SECURITY_HEADERS = (
        ('X-Content-Type-Options', 'nosniff'),
        ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"),
    )

    def end_headers(self):
        # Every response, including errors the base class writes itself (HEAD, bad requests).
        for key, value in self.SECURITY_HEADERS:
            self.send_header(key, value)
        super().end_headers()

    def local_name(self, value):
        name, separator, port = (value or '').partition(':')
        if not separator:
            return False
        if name in ('127.0.0.1', 'localhost'):
            return port == str(PORT)
        if not LAN or port != str(PORT):
            return False
        return shop_name_allowed(name)

    def allowed(self):
        return self.local_name(self.headers.get('Host'))

    def client_ip(self):
        address = getattr(self, 'client_address', None)
        if not address:
            return '127.0.0.1'
        return shop_auth.normalize_ip(address[0])

    def loopback_client(self):
        if not getattr(self, 'client_address', None):
            return True
        return self.client_ip() in ('127.0.0.1', '::1')

    def route_path(self):
        path = urlparse(self.path).path or '/'
        if path == '/web/':
            return '/web'
        return path

    def token_ok(self):
        supplied = self.headers.get('X-EZ-Token') if self.headers else None
        if not isinstance(supplied, str) or not supplied:
            return False
        try:
            return secrets.compare_digest(supplied, TOKEN)
        except (TypeError, ValueError):
            return False

    def cookie_ok(self):
        if not shop_auth.pin_configured(WORK):
            # The PIN was removed while running: no shop-network session stays valid.
            shop_auth.clear_sessions()
            return False
        header = self.headers.get('Cookie') if self.headers else None
        return shop_auth.session_valid(shop_auth.read_cookie(header), self.client_ip())

    def authenticated(self):
        # The write token stays on the host. A designer browser uses the PIN cookie.
        if self.loopback_client() and self.token_ok():
            return True
        return self.cookie_ok()

    def _discard_request_body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except (TypeError, ValueError):
            return
        if size <= 0:
            return
        if size > 1_048_576:
            size = 1_048_576
        remaining = size
        while remaining:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                return
            remaining -= len(chunk)

    def origin_ok(self, origin):
        scheme = 'https://' if TLS else 'http://'
        if not isinstance(origin, str) or not origin.startswith(scheme):
            return False
        rest = origin[len(scheme):]
        if not rest or '/' in rest:
            return False
        return self.local_name(rest)

    def browser_site_ok(self):
        """State changes and /api/session need a same-origin browser signal.

        A present Origin must name this host. A present Sec-Fetch-Site must be
        same-origin. LAN clients must send one of those. A loopback program
        that sends neither header (the launcher, Illustrator, the update helper)
        is not a browser rebinding.
        """
        origin = self.headers.get('Origin') if self.headers else None
        fetch_site = (self.headers.get('Sec-Fetch-Site') or '').strip().casefold() if self.headers else ''
        origin_matches = bool(origin) and self.origin_ok(origin)
        fetch_matches = fetch_site == 'same-origin'
        if origin and not origin_matches:
            return False
        if fetch_site and not fetch_matches:
            return False
        if origin_matches or fetch_matches:
            return True
        return self.loopback_client()

    def session_body(self):
        local = self.loopback_client()
        body = {
            'app': 'eznest',
            'version': VERSION,
            'pid': os.getpid(),
            'shopService': macos_service_runtime.active(),
            'maintenance': macos_service_runtime.maintenance(),
            'localSave': local and print_export.native_save_available(),
            'localPC': local,
            'authenticated': bool(local or self.authenticated()),
            'pinConfigured': shop_auth.pin_configured(WORK),
            'pinWeak': shop_auth.pin_is_weak(WORK),
            'tls': TLS,
            'outputConnection': output_gate.public_status(WORK, local),
            'outputLink': output_gate.link_status(WORK, local),
        }
        if local:
            body['token'] = TOKEN
            body['pinAlert'] = shop_auth.alert_status()
        return body

    def do_GET(self):
        if not self.allowed():
            return self.send(403, {'error': 'Invalid host'})
        path = self.route_path()
        if path == '/api/session':
            if not self.browser_site_ok():
                return self.send(403, {'error': 'Invalid session'})
            return self.send(200, self.session_body())
        if path.startswith('/api/'):
            if path == '/api/health':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Open health on the shop computer.'})
                return self.send(200, {'ok': True, 'app': 'eznest'})
            if not self.loopback_client() and not self.authenticated():
                return self.send(403, {'error': 'Enter the shop PIN on this computer.'})
            if not self.loopback_client() and (path == '/api/shop' or path == '/api/folder' or path.startswith('/api/folder/')):
                return self.send(403, {'error': 'Open this on the shop computer.'})
        if path == '/api/changelog':
            import installer_update
            return self.send(200, {'version': VERSION, 'entries': installer_update.changelog_entries(ROOT)})
        if path == '/api/update':
            if macos_service_runtime.active():
                import macos_update
                try:
                    info = macos_update.start(WORK) if parse_qs(urlparse(self.path).query).get('refresh') == ['1'] else macos_update.status(WORK)
                except (OSError, ValueError, subprocess.SubprocessError):
                    info = macos_update.status(WORK)
                info.update(localPC=self.loopback_client(), serverPid=os.getpid())
                return self.send(200, info)
            import installer_update
            refresh = parse_qs(urlparse(self.path).query).get('refresh', ['0'])[0] == '1'
            if refresh:
                info = peek_latest(WORK, VERSION)
            else:
                info = {'ok': True, 'current': VERSION, 'updateAvailable': False, 'latest': VERSION, 'message': '', 'error': None}
                if updates_allowed(WORK):
                    info.update(UPDATE_CHECK)
            info.update(installer_update.local_state(WORK, installer_update.install_root()))
            import managed_update
            info['managedSupported'] = managed_update.supported(installer_update.install_root())
            with OPERATIONS:
                info.update(UPDATE_QUEUE.status())
            info['localPC'] = self.loopback_client()
            info['serverPid'] = os.getpid()
            info['managedResult'] = installer_update.read_json(WORK/'updates'/'managed-result.json')
            info['notes'] = installer_update.current_notes(ROOT, VERSION)
            info['issuesUrl'] = issues_url(WORK)
            if info.get('rollback'):
                info['message'] = info['rollback'].get('reason') or info['message']
            elif info.get('applyOnRestart'):
                info['message'] = f"{info['stagedVersion']} is checked and installs the next time eznest starts. Settings and the hot folder stay."
                info['error'] = None
            elif info.get('staged'):
                info['message'] = 'A checked update is saved. Automatic installation is unavailable for this installation. The current app stays running.'
            if info.get('queued'):
                info['message'] = 'Update approved. Finish sending the current job or choose Start over. You can cancel before installation starts.'
            elif info.get('staged') and info['managedSupported']:
                info['message'] = 'Update ready. Choose Install when finished on this PC and approve the Windows prompt.'
            elif info.get('managedResult') and not info.get('staged'):
                info['message'] = info['managedResult'].get('message', '')
            return self.send(200, info)
        if path == '/api/macos-update/package':
            if not self.loopback_client() or not self.token_ok():
                return self.send(403, {'error':'Open the update on the shop Mac.'})
            import macos_update
            try:
                with macos_update.LOCK:
                    package, info = macos_update.package_path(WORK)
                    with os.fdopen(os.open(package, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as handle:
                        content = handle.read(macos_update.MAX_BYTES + 1)
                    if len(content) != info['size'] or hashlib.sha256(content).hexdigest() != info['sha256']:
                        raise ValueError('The checked package changed.')
                return self.send(200, content, 'application/octet-stream', 'eznest-update.pkg')
            except (OSError, ValueError):
                return self.send(409, {'error':'The checked Mac update is unavailable. Download it again.'})
        if path == '/api/shop':
            return self.send(200, shop_status())
        if path == '/api/materials':
            try:
                return self.send(200, material_inventory.read(WORK))
            except (OSError, sqlite3.Error):
                return self.send(503, {'error': 'Shop inventory is unavailable. Check disk space and folder permissions.'})
        if path.startswith('/api/illustrator/'):
            if not self.loopback_client():
                return self.send(403, {'error': 'Illustrator pilot requires this PC.'})
            try:
                return self.send(200, illustrator_bridge.read(WORK, path.rsplit('/', 1)[-1]))
            except (OSError, ValueError):
                return self.send(404, {'error': 'Illustrator handoff not found or changed. Export again.'})
        if path == '/api/workload':
            try:
                info = workload.summary(WORK)
                info['warning'] = STATE.get('trackingWarning')
                return self.send(200, info)
            except (OSError, sqlite3.Error):
                return self.send(503, {'error': 'Local activity is unavailable. Check disk space and folder permissions.'})
        if path in ('/api/telemetry', '/api/telemetry/events', '/api/telemetry/output'):
            if not self.loopback_client() or not self.token_ok():
                return self.send(403, {'error': 'Local session required for job tracking.'})
            try:
                if path.endswith('/output'):
                    return self.send(200, telemetry_sender.status(WORK, paused=telemetry_paused))
                if path.endswith('/events'):
                    return self.send(200, {'schema': telemetry.SCHEMA, 'events': telemetry.pending(WORK)})
                info = telemetry.status(WORK)
                delivery = telemetry_sender.status(WORK, paused=telemetry_paused)
                info.update(localOnly=not delivery['enabled'], hubConnected=None if delivery['enabled'] else False, outputDelivery=delivery)
                info.update(eventTypes=telemetry.KINDS, warning=STATE.get('telemetryWarning'))
                return self.send(200, info)
            except (OSError, sqlite3.Error):
                return self.send(503, {'error': 'Local job tracking is unavailable.'})
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
        if path.startswith(('/api/batch/', '/api/print/')):
            ident = path.rsplit('/',1)[-1]
            if len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
                return self.send(404, {'error':'Batch not found'})
            source = WORK / 'batches' / (ident+'.zip')
            if not source.exists():
                return self.send(404, {'error':'Batch not found'})
            if path.startswith('/api/print/'):
                with ZipFile(source) as archive:
                    if 'artwork.pdf' not in archive.namelist():
                        return self.send(409, {'error':'Save the complete pack for a multi-sheet or SVG layout.'})
                    return self.send(200, archive.read('artwork.pdf'), 'application/pdf', 'Print.pdf')
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
        static.update({'/queue-app.js': ('queue-app.js','text/javascript'), '/queue-core.js': ('queue-core.js','text/javascript'), '/queue.css': ('queue.css','text/css')})
        static['/production-features.js']=('production-features.js','text/javascript')
        static['/layout-comparison.js']=('layout-comparison.js','text/javascript')
        static['/cut-mapping.js']=('cut-mapping.js','text/javascript')
        static['/shop-profiles.js'] = ('shop-profiles.js','text/javascript')
        static['/web'] = ('web.html', 'text/html')
        static['/web.css'] = ('web.css', 'text/css')
        static['/web.js'] = ('web.js', 'text/javascript')
        static['/tester-results.js'] = ('tester-results.js', 'text/javascript')
        static['/fonts/rajdhani-700.woff2'] = ('fonts/rajdhani-700.woff2', 'font/woff2')
        static['/fonts/red-hat-display-400.woff2'] = ('fonts/red-hat-display-400.woff2', 'font/woff2')
        static['/fonts/red-hat-display-700.woff2'] = ('fonts/red-hat-display-700.woff2', 'font/woff2')
        if os.environ.get('EZ_NEST_TEST_UI') == '1':
            static.update({'/tests/svg-tests.html': ('tests/svg-tests.html', 'text/html'), '/tests/svg-tests.js': ('tests/svg-tests.js', 'text/javascript')})
        if path not in static:
            return self.send(404, {'error': 'Not found'})
        name, mime = static[path]
        return self.send(200, static_bytes(name), mime)

    def import_document(self, data, upload_size=None):
        if not DOCUMENT_LOCK.acquire(blocking=False):
            raise ValueError('Wait for the current document import to finish.')
        ident = uuid.uuid4().hex
        request, output = WORK/(ident+'-import.json'), WORK/(ident+'-import-result.json')
        upload = WORK/(ident+'-upload.pdf')
        try:
            if upload_size is not None:
                if upload_size == 0:
                    raise ValueError('The selected file is empty.')
                # Read bounded chunks straight to disk. No base64 or full-file
                # allocation in the HTTP server; the isolated worker parses it.
                remaining = upload_size
                with upload.open('xb') as target:
                    while remaining:
                        chunk = self.rfile.read(min(1_048_576, remaining))
                        if not chunk:
                            raise ValueError('Upload was interrupted. Please try the file again.')
                        target.write(chunk)
                        remaining -= len(chunk)
            # Never accept a local path from JSON or upload metadata.
            options = {key: data[key] for key in ('content', 'bleedMm', 'cutSpot', 'cutMapping', 'preserveArtwork', 'guideApproval', 'cutApproval') if key in data}
            if upload_size is not None:
                options.pop('content', None)
            request.write_text(json.dumps(options), encoding='utf-8')
            worker = [sys.executable, '--document-worker'] if getattr(sys, 'frozen', False) else [sys.executable, str(ROOT/'pdf_io.py')]
            args = [*worker, str(request), str(output)]
            if upload_size is not None:
                args.append(str(upload))
            subprocess.run(args, cwd=WORK, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300 if upload_size is not None else 120, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            payload = json.loads(output.read_text(encoding='utf-8'))
            if payload.get('cutReview'):
                status, response = 409, {'error':payload['error'], 'cutReview':payload['cutReview']}
            elif payload.get('guideReview'):
                status, response = 409, {'error':payload['error'], 'guideReview':payload['guideReview']}
            elif not payload['ok']:
                raise ValueError(payload['error'])
            else:
                status, response = 200, payload['document']
        except subprocess.TimeoutExpired:
            raise ValueError('PDF processing took too long. Try a print-only PDF without Illustrator editing data.') from None
        finally:
            try:
                remove_import_temp(request)
                remove_import_temp(output)
                remove_import_temp(upload)
                remove_import_temp(upload.with_name(upload.stem + '-print.pdf'))
            finally:
                DOCUMENT_LOCK.release()
        return self.send(status, response)

    def do_POST(self):
        # Hold admission through import, save and delivery. An update claim cannot
        # slip between a busy check and a new operation starting on another PC.
        with OPERATIONS:
            if (UPDATE_QUEUE.stopping or macos_service_runtime.maintenance()) and self.route_path() != '/api/macos-service/cancel':
                return self.send(503, {'error': 'Installing an update. Wait for eznest to restart.'})
            return self.handle_post()

    def _login(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send(400, {'error': 'Could not sign in.'})
        if not 0 <= size <= 4000:
            return self.send(400, {'error': 'Could not sign in.'})
        try:
            data = json.loads(self.rfile.read(size) or b'{}')
        except (ValueError, TypeError):
            return self.send(400, {'error': 'Could not sign in.'})
        pin = data.get('pin') if isinstance(data, dict) else ''
        result = shop_auth.login_attempt(WORK, self.client_ip(), pin if isinstance(pin, str) else '')
        if result == 'missing':
            return self.send(403, {'error': 'The shop PIN is not set. Set it on the shop computer.'})
        if result == 'locked':
            return self.send(429, {'error': 'Too many tries from this computer. Wait and try again.'})
        if result != 'ok':
            return self.send(401, {'error': 'That PIN is not right.'})
        sid = shop_auth.issue_session(self.client_ip())
        return self.send(200, {'ok': True, 'authenticated': True}, extra_headers=[('Set-Cookie', shop_auth.cookie_header(sid, secure=TLS))])

    def _logout(self):
        shop_auth.revoke_session(shop_auth.read_cookie(self.headers.get('Cookie') if self.headers else None))
        return self.send(200, {'ok': True}, extra_headers=[('Set-Cookie', shop_auth.clear_cookie_header(secure=TLS))])

    def handle_post(self):
        global PROCESS
        if not self.allowed() or not self.browser_site_ok():
            return self.send(403, {'error': 'Invalid session'})
        path = self.route_path()
        if path == '/api/login':
            return self._login()
        if path == '/api/logout':
            return self._logout()
        if not self.authenticated():
            return self.send(403, {'error': 'Invalid session'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= request_limit(path):
                raise ValueError('Job is too large.')
            if path == '/api/document/import-file':
                header = self.headers.get('X-EZ-Import', '{}')
                if len(header) > 16_000:
                    raise ValueError('Import options are too large.')
                options = json.loads(unquote(header))
                if not isinstance(options, dict):
                    raise ValueError('Invalid import options.')
                return self.import_document(options, upload_size=size)
            data = json.loads(self.rfile.read(size) or '{}')
            if path in ('/api/macos-service/claim', '/api/macos-service/cancel'):
                if not self.loopback_client():
                    return self.send(403, {'error': 'Approve updates on the server Mac.'})
                if not isinstance(data, dict) or set(data) != {'ticket'}:
                    raise ValueError('Supply the administrator update ticket.')
                macos_service_runtime.authorize_claim(data['ticket'])
                if path.endswith('/cancel'):
                    if UPDATE_QUEUE.ticket not in (None, data['ticket']):
                        raise ValueError('Another update owns admission.')
                    UPDATE_QUEUE.stopping = False
                    UPDATE_QUEUE.cancel()
                    return self.send(200, {'ok': True})
                UPDATE_QUEUE.queue(data['ticket'])
                with LOCK:
                    ready = UPDATE_QUEUE.claim(data['ticket'], STATE)
                    if ready:
                        persist_state()
                # launchd owns the process lifetime. The privileged installer
                # stops it only after this admission lock has closed new work.
                return self.send(200, {'ok': True, 'ready': ready, 'pid': os.getpid()})
            if path.startswith('/api/telemetry/'):
                if not self.loopback_client():
                    return self.send(403, {'error': 'Local session required for job tracking.'})
                if not isinstance(data, dict):
                    raise ValueError('Supply a tracking request object.')
                if path == '/api/telemetry/output/consent':
                    if set(data) != {'revision', 'version', 'configurationId', 'confirmed'}:
                        raise ValueError('Review and explicitly approve the sharing disclosure.')
                    return self.send(200, telemetry_sender.consent(WORK, **data))
                if path == '/api/telemetry/output/revoke':
                    if data:
                        raise ValueError('Stopping sharing takes no additional data.')
                    return self.send(200, telemetry_sender.revoke(WORK))
                if path == '/api/telemetry/output/pair':
                    if set(data) != {'code'}:
                        raise ValueError('Paste the pairing code from OUTPUT.')
                    # The exchange is network IO. Do not hold the job lock.
                    # reason is a short category. The pairing code and credential are not returned.
                    try:
                        return self.send(200, output_pairing.connect(WORK, data.get('code'), paused=telemetry_paused()))
                    except output_pairing.PairingError as error:
                        return self.send(400, {'error': str(error), 'reason': error.reason})
                if path == '/api/telemetry/output/disconnect':
                    if data:
                        raise ValueError('Disconnect takes no additional data.')
                    return self.send(200, output_pairing.disconnect(WORK, paused=telemetry_paused()))
                if path == '/api/telemetry/output/check-in':
                    if data:
                        raise ValueError('Check-in takes no additional data.')
                    return self.send(200, output_gate.check_in(WORK, local=True))
                with LOCK:
                    if path == '/api/telemetry/link':
                        if set(data) - {'id', 'jobCodes', 'rollId'}:
                            raise ValueError('Only job codes and an opaque roll ID may be linked.')
                        if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id') or STATE.get('released'):
                            raise ValueError('Link the current finished layout before freezing it.')
                        record_telemetry('nest.created')
                        telemetry.link(WORK, data.get('id'), data.get('jobCodes'), data.get('rollId'))
                    elif path == '/api/telemetry/status':
                        if set(data) - {'id', 'action', 'confirmed'} or data.get('confirmed') is not True:
                            raise ValueError('Explicitly confirm the queue, print or cancellation observation.')
                        telemetry.transition(WORK, data.get('id'), data.get('action'))
                    elif path == '/api/telemetry/stock':
                        if set(data) != {'rollId', 'materialKey', 'remainingMm', 'requestId', 'expectedRevision'}:
                            raise ValueError('Supply roll ID, material key, measured remaining mm, request ID and expected revision.')
                        telemetry.record_stock(WORK, data['rollId'], data['materialKey'], data['remainingMm'],
                                               data['requestId'], data['expectedRevision'])
                    else:
                        raise ValueError('Unknown tracking operation.')
                return self.send(200, {'ok': True})
            if path.startswith('/api/update/'):
                import installer_update
                if not self.loopback_client():
                    return self.send(403, {'error': 'Approve updates on the server PC.'})
                if path == '/api/update/cancel':
                    UPDATE_QUEUE.cancel()
                    return self.send(200, {'ok': True, 'message': 'Update cancelled. The app stays running.'})
                if path == '/api/update/result':
                    pending = installer_update.pending_state(WORK)
                    if pending and pending['sha256'] == data.get('sha256'):
                        (WORK/'updates'/'pending.json').unlink(missing_ok=True)
                    installer_update.write_json(WORK/'updates'/'managed-result.json', {'message': str(data.get('message', ''))[:500]})
                    return self.send(200, {'ok': True})
                if path in ('/api/update/queue', '/api/update/claim'):
                    if not installer_update.updates_enabled(WORK):
                        UPDATE_QUEUE.cancel()
                        raise ValueError('Updates are off.')
                    pending = installer_update.pending_state(WORK)
                    if not pending or pending['sha256'] != data.get('sha256'):
                        raise ValueError('The staged update changed. Open the update helper again.')
                    if pending.get('channel') != load_shop(WORK)['channel']:
                        UPDATE_QUEUE.cancel()
                        raise ValueError('The update channel changed. Download an update for the selected channel.')
                    if path.endswith('/queue'):
                        UPDATE_QUEUE.queue(data.get('ticket'))
                        return self.send(200, {'ok': True, 'queued': True})
                    with LOCK:
                        ready = UPDATE_QUEUE.claim(data.get('ticket'), STATE)
                        if ready:
                            persist_state()
                    self.send(200, {'ok': True, 'ready': ready, 'pid': os.getpid()})
                    if ready:
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                raise ValueError('Unknown update operation.')
            if path == '/api/illustrator/intake':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Illustrator pilot requires this PC.'})
                with LOCK:
                    info = illustrator_bridge.accept(WORK, data)
                return self.send(200, {'ok': True, 'id': info['id'], 'url': f'http://127.0.0.1:{PORT}/web?illustrator=' + info['id']})
            if path == '/api/document/import':
                return self.import_document(data)
            if path == '/api/export/pick':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Use browser download on another computer.'})
                target = print_export.pick_save_path(data.get('name'), data.get('format'))
                return self.send(200, {'path': target, 'cancelled': target is None})
            if path == '/api/export/folders':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Browse folders on the PC running eznest.'})
                return self.send(200, print_export.browse_folders(data.get('path'), OUTPUT.root))
            if path == '/api/export/save':
                with LOCK:
                    if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id') or not STATE.get('released'):
                        raise ValueError('Review and freeze the current layout before saving.')
                    package = (WORK/'batches'/(STATE['id']+'.zip')).read_bytes()
                    if hashlib.sha256(package).hexdigest() != data.get('sha256'):
                        raise ValueError('The saved layout changed. Review it again.')
                name, content = print_export.export_content(package, data.get('name'), data.get('format'))
                mode = data.get('destination')
                expected = data.get('replaceSha256')
                if mode == 'choose':
                    if not self.loopback_client():
                        return self.send(403, {'error': 'Choose a location on the PC running eznest, or use browser download.'})
                    selected = data.get('path')
                    if not isinstance(selected, str) or len(selected) > 1000 or not Path(selected).is_absolute():
                        raise ValueError('Choose a file in the Windows save window first.')
                    target = Path(selected)
                    if target.suffix.lower() != Path(name).suffix:
                        raise ValueError('Keep the selected PDF or ZIP file extension.')
                    print_export.export_filename(target.name, data.get('format'))
                elif mode == 'folder':
                    if not OUTPUT.root:
                        raise ValueError('Choose your default print folder in Settings first.')
                    target = OUTPUT.root / name
                else:
                    raise ValueError('Choose the default print folder or My computer.')
                with FOLDER_LOCK:
                    saved = print_export.save_file(target, content, WORK, expected, FOLDER.root)
                if saved.get('exists'):
                    return self.send(200, saved)
                if mode == 'folder':
                    with FOLDER_LOCK:
                        stage_pack(data.get('stagingFolder') or '', STATE['id'], package, FOLDER.root)
                with LOCK:
                    STATE['exportReceipt'] = {'path': saved['path'], 'destination': mode, 'format': data['format']}
                    if mode == 'folder':
                        STATE['deliveryCompleted'] = True
                        record_workload('sent_to_folder')
                    else:
                        record_telemetry('nest.exported')
                    persist_state()
                return self.send(200, dict(saved, ok=True))
            if path == '/api/pin':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Set the shop PIN on the shop computer.'})
                shop_auth.set_pin(WORK, data.get('pin') if isinstance(data, dict) else None)
                return self.send(200, {'ok': True, 'pinConfigured': True, 'pinWeak': False})
            if path == '/api/pin/alert/ack':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Review PIN failures on the shop computer.'})
                return self.send(200, shop_auth.acknowledge_alert())
            if path in ('/api/output/connect', '/api/output/pick'):
                if not self.loopback_client():
                    return self.send(403, {'error': 'Choose this folder on the PC running eznest.'})
                if path.endswith('/pick'):
                    if not self.loopback_client():
                        return self.send(403, {'error': 'Choose this folder on the PC running eznest.'})
                    data = {'path': pick_folder('Select where eznest will save print packs')}
                    if not data['path']:
                        return self.send(200, {'cancelled': True})
                with FOLDER_LOCK:
                    return self.send(200, OUTPUT.connect(data.get('path',''), FOLDER.root))
            if path == '/api/setup':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Finish setup on the shop computer.'})
                from shop_deploy import validate_setup
                setup = validate_setup(data)
                if setup['hotFolder']:
                    with FOLDER_LOCK:
                        OUTPUT.connect(setup['hotFolder'], FOLDER.root)
                current = load_shop(WORK)
                save_shop(WORK, data.get('onyxPc') is True, current['lan'], setupComplete=True, **setup)
                return self.send(200, shop_status())
            if path == '/api/shop':
                if not self.loopback_client():
                    return self.send(403, {'error': 'Change shop settings on the shop computer.'})
                current = load_shop(WORK)
                updates = current['updates'] if 'updates' not in data else data.get('updates') is True
                fields = {}
                for key in ('channel', 'outputNetwork', 'setupComplete', 'printer', 'units', 'thru', 'kiss', 'hotFolder', 'outputUrl'):
                    if key in data:
                        fields[key] = data.get(key)
                save_shop(WORK, data.get('onyxPc') is True, data.get('lan') is True, updates, **fields)
                UPDATE_CHECK.clear()
                UPDATE_WAKE.set()
                return self.send(200, shop_status())
            if path == '/api/materials/save':
                return self.send(200, material_inventory.save(WORK, data.get('id'), data.get('profile'), data.get('revision')))
            if path == '/api/materials/remove':
                return self.send(200, material_inventory.remove(WORK, data.get('id'), data.get('revision')))
            if path == '/api/materials/reserve':
                with LOCK:
                    if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id'):
                        raise ValueError('The layout changed. Reload and review the current layout before reserving stock.')
                    key = STATE['job'].get('inventoryMaterialId')
                    if not key:
                        raise ValueError('Save the material to shop inventory and nest again before reserving stock.')
                    if not STATE.get('manifest', {}).get('productionReady'):
                        check = batch_output_check(STATE['job'])
                        if check and not check.get('ready'):
                            raise ValueError('Resolve the print-file checks before reserving material.')
                    result = STATE['result']
                    fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
                    return self.send(200, material_inventory.reserve(WORK, key, STATE['id'], result['usedLength'], result['width'], fingerprint))
            if path == '/api/materials/transition':
                return self.send(200, material_inventory.transition(WORK, data.get('id'), data.get('action')))
            if path == '/api/update':
                if macos_service_runtime.active():
                    if not self.loopback_client():
                        return self.send(403, {'error':'Download and approve updates on the shop Mac.'})
                    import macos_update
                    return self.send(200, macos_update.start(WORK, 'download'))
                if UPDATE_QUEUE.status()['queued']:
                    raise ValueError('Cancel the waiting update before downloading another.')
                with LOCK:
                    if STATE.get('status') == 'running':
                        raise ValueError('Stop the current search before updating.')
                import installer_update
                result = pull_latest(WORK, VERSION, when=data.get('when') or 'restart', install_root=installer_update.install_root())
                if result.get('restarting'):
                    self.send(200, result)
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                return self.send(200, result)
            if path.startswith('/api/folder/'):
                if not self.loopback_client():
                    return self.send(403, {'error': 'Choose the source folder on the shop computer.'})
                if path == '/api/folder/pick':
                    if os.name != 'nt':
                        raise ValueError('Use the folder path field on this platform.')
                    folder_path = powershell_folder_picker('Select your print-ready SVG production folder', show_new=False)
                    if not folder_path:
                        return self.send(200, {'cancelled': True})
                    data = {'path':folder_path}
                with FOLDER_LOCK:
                    if path in ('/api/folder/connect','/api/folder/pick'):
                        root = real_directory(data['path'])
                        if OUTPUT.root and OUTPUT.root.resolve().is_relative_to(root):
                            raise ValueError('The source folder must not contain your output folder.')
                        approve_source_root(WORK, root)
                        result = FOLDER.connect(str(root))
                    elif path == '/api/folder/disconnect':
                        FOLDER.disconnect()
                        result = {'connected':False,'files':[]}
                    else:
                        raise ValueError('Unknown folder action.')
                return self.send(200,result)
            with LOCK:
                if path in ('/api/solve', '/api/improve'):
                    if STATE.get('status') == 'running':
                        raise ValueError('Cancel the current search before starting another.')
                    incumbent = None
                    if path == '/api/improve':
                        if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id'):
                            raise ValueError('Calculate a current layout before improving it.')
                        if STATE.get('released'):
                            raise ValueError('This batch is frozen. Start a new layout to make changes.')
                        seconds = data.get('seconds')
                        if seconds is not None and (type(seconds) is not int or seconds not in (5, 30, 90)):
                            raise ValueError('Choose Quick, Balanced or Best fit.')
                        incumbent = copy.deepcopy(STATE)
                        data = copy.deepcopy(STATE.get('requestJob', STATE['job']))
                        data['settings']['seed'] = secrets.randbelow(2147483647)
                        data['settings']['seconds'] = seconds if seconds is not None else max(30, data['settings']['seconds'])
                    for part in data.get('parts', []) + [p for fill in data.get('fillJobs', []) for p in fill['parts']]:
                        part.pop('nestingPoints', None)
                    validate_request(data)
                    if data.get('illustrator'):
                        handoff = illustrator_bridge.read(WORK, data['illustrator']['id'])
                        # Match the source PDF, not a client-supplied tracking identity.
                        sources = data.get('documentSources', [])
                        if len(sources) != 1:
                            raise ValueError('Nest the Illustrator handoff separately.')
                        data['illustrator'] = {k: handoff[k] for k in ('id', 'sourceId', 'revision')}
                    documents = None
                    if data.get('documentSources'):
                        from pdf_io import load_documents
                        complete={**data,'productionJobs':data.get('productionJobs',[])+[f['source'] for f in data.get('fillJobs',[])],
                                  'parts':data['parts']+[p for f in data.get('fillJobs',[]) for p in f['parts']]}
                        documents = load_documents(complete,WORK/'documents')
                        if data.get('illustrator') and any(meta['sourceHash'] != data['illustrator']['revision'] for _, meta in documents.values()):
                            raise ValueError('Illustrator source does not match this handoff.')
                    from pdf_io import prepare_nesting_geometry
                    prepare_nesting_geometry(data, documents)
                    validate_request(data)
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
                elif path == '/api/cancel':
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
                        STATE.pop('output', None)
                        # Stopping a retry must not replace the previous best
                        # with a worse intermediate arrangement.
                        finish_search({'ok':True, 'result':live})
                        STATE['note'] = 'Stopped. Your best layout is retained.'
                    else:
                        incumbent = STATE.get('incumbent')
                        STATE.clear()
                        STATE.update(incumbent or {'status': 'cancelled', 'note': 'Stopped before a layout was ready.'})
                        if incumbent:
                            STATE['note'] = 'Search cancelled; your best layout is retained.'
                    persist_state()
                elif path == '/api/output/undo':
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
                    record_workload('removed_from_folder')
                    STATE.update(savedPath='', deliveryCompleted=False)
                    persist_state()
                    return self.send(200, {'ok': True})
                elif path == '/api/shutdown':
                    if macos_service_runtime.active():
                        raise ValueError('The shop host stays available when a browser closes. The administrator controls its system service.')
                    if STATE.get('status') == 'running':
                        raise ValueError('Stop the current search before closing eznest.')
                    persist_state()
                    self.send(200, {'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif path == '/api/work/discard':
                    if STATE.get('status') == 'running':
                        raise ValueError('Stop the search before starting over.')
                    STATE.clear()
                    STATE.update(status='idle')
                    (WORK/'session.json').unlink(missing_ok=True)
                    return self.send(200, {'ok': True})
                elif path == '/api/release':
                    if STATE.get('status') != 'ready' or data.get('id') != STATE.get('id'):
                        raise ValueError('Calculate and review the current layout before exporting.')
                    export_job = copy.deepcopy(STATE['job'])
                    if not STATE.get('released'):
                        apply_web_export(export_job, data)
                    check = batch_output_check(export_job)
                    if check and not check['ready'] and data.get('workingOnly') is not True:
                        raise ValueError('This layout does not meet the shop output requirements. Save working files explicitly or use a supported output profile.')
                    if not STATE.get('released'):
                        documents=None
                        if export_job.get('documentSources'):
                            from pdf_io import load_documents
                            documents=load_documents(export_job,WORK/'documents')
                        from pdf_io import prepare_nesting_geometry, validate_auto_bleed_export
                        prepare_nesting_geometry(export_job, documents)
                        validate_auto_bleed_export(export_job, STATE['result'], documents)
                        content, details = make_package(export_job,STATE['result'],STATE['id'],data.get('artwork'),data['map'],documents,check)
                        directory = WORK / 'batches'
                        directory.mkdir(exist_ok=True)
                        temporary = directory / (STATE['id']+'.tmp')
                        temporary.write_bytes(content)
                        temporary.replace(directory / (STATE['id']+'.zip'))
                        STATE.update(job=export_job, released=True, manifest=details, deliveryCompleted=False)
                        persist_state()
                    package = (WORK/'batches'/(STATE['id']+'.zip')).read_bytes()
                    record_workload('prepared')
                    digest = hashlib.sha256(package).hexdigest()
                    with FOLDER_LOCK:
                        saved = None if data.get('downloadOnly') is True else OUTPUT.save(STATE['id'], package, FOLDER.root)
                        if saved:
                            record_workload('sent_to_folder')
                        if data.get('downloadOnly') is not True:
                            stage_pack(data.get('stagingFolder') or '', STATE['id'], package, FOLDER.root)
                    STATE.update(deliveryCompleted=bool(saved) or STATE.get('deliveryCompleted',False), savedPath=saved or (STATE.get('savedPath') if data.get('downloadOnly') is True else None), sha256=digest)
                    persist_state()
                    return self.send(200, {'ok':True,'id':STATE['id'],'url':'/api/batch/'+STATE['id'], 'savedPath':saved,'outputCheck':check,'deliveryCompleted':STATE['deliveryCompleted'],'sha256':digest})
                elif path == '/api/delivery/complete':
                    if STATE.get('status')!='ready' or data.get('id')!=STATE.get('id') or not STATE.get('released') or not (WORK/'batches'/(STATE['id']+'.zip')).is_file():
                        raise ValueError('Download the current frozen batch before completing its delivery.')
                    STATE['deliveryCompleted']=True
                    persist_state()
                    return self.send(200,{'ok':True})
                elif path == '/api/prepare-apply':
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


def powershell_folder_picker(description, show_new=True):
    """Ask Windows for a folder. The label is an environment variable, not script text."""
    if os.name != 'nt':
        raise ValueError('Enter the folder path on this platform.')
    prompt = description if isinstance(description, str) else ''
    if not prompt or len(prompt) > 200 or any(ord(char) < 32 for char in prompt):
        prompt = 'Select a folder'
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$picker=New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$picker.Description=$env:EZ_NEST_FOLDER_PROMPT; "
    )
    if not show_new:
        script += "$picker.ShowNewFolderButton=$false; "
    script += "if($picker.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Console]::Write($picker.SelectedPath)}"
    env = os.environ.copy()
    env['EZ_NEST_FOLDER_PROMPT'] = prompt
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    selected = subprocess.run(
        ['powershell.exe', '-NoProfile', '-STA', '-Command', script],
        capture_output=True, env=env, creationflags=flags, timeout=300)
    return selected.stdout.decode('utf-8-sig').strip()


def pick_folder(description):
    return powershell_folder_picker(description, show_new=True)


class LocalServer(ThreadingHTTPServer):
    # POSIX needs SO_REUSEADDR to restart while accepted sockets are in
    # TIME_WAIT. This does not enable SO_REUSEPORT or a second live listener.
    # Windows retains exclusive ownership instead of its weaker reuse flag.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()
        if TLS_CONTEXT is not None:
            self.socket = TLS_CONTEXT.wrap_socket(self.socket, server_side=True)


def check_updates(stop):
    global UPDATE_CHECK
    while not stop.is_set():
        UPDATE_WAKE.clear()
        try:
            channel = load_shop(WORK)['channel']
            if macos_service_runtime.active():
                import macos_update
                info = macos_update.start(WORK)
            else:
                info = peek_latest(WORK, VERSION)
            if load_shop(WORK)['channel'] == channel:
                UPDATE_CHECK = info
        except Exception:
            # Network failure must not affect nesting or make the UI unusable.
            pass
        UPDATE_WAKE.wait(6 * 60 * 60)


def serve(open_browser=False, page='/'):
    configure_tls(os.environ.get('EZ_NEST_TLS_CERT'), os.environ.get('EZ_NEST_TLS_KEY'))
    if HOST not in ('127.0.0.1', '::1') and not shop_auth.pin_configured(WORK):
        raise RuntimeError('Set a shop PIN on this computer before opening the shop network.')
    restore_state()
    import installer_update
    service = LocalServer((HOST, PORT), Handler)
    update_stop = threading.Event()
    sender_thread = threading.Thread(target=telemetry_sender.run, args=(WORK, update_stop, telemetry_paused), daemon=True)
    sender_thread.start()
    threading.Thread(target=output_gate.run, args=(WORK, update_stop), daemon=True).start()
    threading.Thread(target=check_updates, args=(update_stop,), daemon=True).start()
    if open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{PORT}{page}')
    if sys.stdout:
        print(f'eznest ready: http://127.0.0.1:{PORT}{page}', flush=True)
        if LAN:
            print(f'Shop network: http://{socket.gethostname()}:{PORT}{page}', flush=True)
    try:
        # The listening socket and startup initialization must succeed first.
        installer_update.mark_healthy(WORK)
        service.serve_forever()
    finally:
        update_stop.set()
        UPDATE_WAKE.set()
        service.server_close()
        sender_thread.join(timeout=12)


if __name__ == '__main__':
    serve()


