"""Require a shop host to be connected to OUTPUT.

Nesting, sending, and stock stay closed until this computer has a shop
credential. After a successful pairing, an unreachable OUTPUT does not stop
the shop until CHECK_IN_MAX_AGE_DAYS have passed without a check-in. A banner
appears after OFFLINE_BANNER_AFTER_DAYS. The check-in body is only the app
version. The computer name and installation id are sent once, by pairing.

The credential is never written here, logged, or returned to the browser.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import output_credential
import shop_deploy
import telemetry_sender
from app_info import VERSION

CHECK_IN_MAX_AGE_DAYS = 14
OFFLINE_BANNER_AFTER_DAYS = 3
DAY_SECONDS = 24 * 60 * 60
CHECK_IN_MAX_AGE = CHECK_IN_MAX_AGE_DAYS * DAY_SECONDS
OFFLINE_BANNER_AFTER = OFFLINE_BANNER_AFTER_DAYS * DAY_SECONDS
STATE_NAME = 'output-checkin.json'
DEV_BANNER = 'DEV MODE: not connected to OUTPUT'

HOST_UNPAIRED = 'Connect this computer to OUTPUT before nesting, sending, or changing stock.'
HOST_DISCONNECTED = 'This computer is disconnected from OUTPUT. Connect again to nest, send, or change stock.'
HOST_REVOKED = 'OUTPUT says this computer is no longer connected. Paste a new pairing code.'
HOST_RECONNECT = (
    f'Reconnect this computer to OUTPUT. The last successful check-in was more than {CHECK_IN_MAX_AGE_DAYS} days ago.'
)
HOST_UPLOADS_OFF = (
    'This run has OUTPUT delivery turned off. Start Ez Nest without that setting, then connect with a pairing code.'
)
HOST_LAUNCH_MISSING = 'This computer uses OUTPUT launch settings, but the shop credential is missing.'
LAN_MESSAGE = 'Ask the shop computer to connect to OUTPUT.'

REVOKED_CODES = frozenset({
    'unpaired', 'revoked', 'invalid_credential', 'invalid_token', 'unauthorized', 'not_paired',
})
LOCK = threading.Lock()


class Offline(Exception):
    """OUTPUT did not answer. The credential is unchanged."""


def source_checkout():
    """True when this process is the repo's Python files, not an installed build."""
    if getattr(sys, 'frozen', False):
        return False
    root = Path(__file__).resolve().parent
    return (root / 'launcher.py').is_file() and (root / 'version.json').is_file() and (root / 'server.py').is_file()


def dev_mode():
    """Labeled dev mode. Installed Windows and macOS builds are frozen and never qualify."""
    return source_checkout() and os.environ.get('EZ_NEST_DEV') == '1'


def dev_escape():
    """EZ_NEST_DEV_NO_OUTPUT=1 counts only in labeled dev mode on a source checkout."""
    return dev_mode() and os.environ.get('EZ_NEST_DEV_NO_OUTPUT') == '1'


def test_harness_open():
    """Regression tests started with python -m unittest are not a shop install.

    EZ_NEST_OUTPUT_GATE_ENFORCE=1 turns this off so the gate tests see a real
    unpaired host. Frozen builds never take this path. launcher.py and
    server.py never take it either.
    """
    if getattr(sys, 'frozen', False):
        return False
    if os.environ.get('EZ_NEST_OUTPUT_GATE_ENFORCE') == '1':
        return False
    argv = (sys.argv[0] if sys.argv else '').replace('\\', '/')
    if argv.endswith(('launcher.py', 'server.py', 'eznest.exe', '/eznest', '\\eznest')):
        return False
    main = sys.modules.get('__main__')
    path = (getattr(main, '__file__', '') or '').replace('\\', '/')
    if path.endswith('unittest/__main__.py'):
        return True
    # Some runners report argv[0] as the text "python -m unittest".
    joined = ' '.join(sys.argv)
    return 'unittest' in joined and ('discover' in joined or '-m unittest' in joined)


def endpoint(directory=None):
    return shop_deploy.output_base_url(directory) + '/api/shop/agent/check-in'


def _state_path(directory):
    return Path(directory) / STATE_NAME


def _read_state(directory):
    try:
        payload = json.loads(_state_path(directory).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(directory, payload):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = _state_path(directory)
    temporary = target.with_name(STATE_NAME + '.tmp')
    raw = (json.dumps(payload, separators=(',', ':')) + '\n').encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    fd = os.open(temporary, flags, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    os.chmod(target, 0o600)


def _stamp(now):
    return int(time.time() if now is None else now)


def note_paired(directory, now=None):
    """A successful pairing is the first check-in."""
    stamp = _stamp(now)
    with LOCK:
        _write_state(directory, {'v': 1, 'lastOkAt': stamp, 'lastAttemptAt': stamp, 'reason': ''})


def note_disconnected(directory, now=None):
    with LOCK:
        _write_state(directory, {'v': 1, 'lastOkAt': None, 'lastAttemptAt': _stamp(now), 'reason': 'disconnected'})


def _uploads():
    return os.environ.get('EZ_NEST_OUTPUT_UPLOADS')


def _token(directory):
    info = telemetry_sender.connection(directory)
    return info.get('token'), info.get('source')


def _problem_code(payload):
    if not isinstance(payload, dict):
        return ''
    error = payload.get('error')
    if isinstance(error, dict):
        raw = error.get('code')
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    if isinstance(error, str) and error.strip():
        return error.strip().lower()
    raw = payload.get('code')
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return ''


def classify(status, body):
    """Map an OUTPUT response to ok, revoked, or offline. The body is not stored."""
    if not isinstance(status, int):
        return 'offline'
    payload = None
    if isinstance(body, (bytes, bytearray)) and body and len(body) <= 16384:
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
    code = _problem_code(payload)
    if code in REVOKED_CODES:
        return 'revoked'
    if status == 200:
        return 'ok'
    if status in (401, 403) and code != 'rate_limited':
        return 'revoked'
    return 'offline'


def _mark_revoked(directory, now):
    try:
        telemetry_sender.revoke(directory)
    except Exception:
        pass
    output_credential.clear(directory)
    _write_state(directory, {'v': 1, 'lastOkAt': None, 'lastAttemptAt': _stamp(now), 'reason': 'revoked'})


def _closed_message(reason, uploads):
    if uploads == '0':
        return HOST_UPLOADS_OFF
    if uploads == '1':
        return HOST_LAUNCH_MISSING
    if reason == 'disconnected':
        return HOST_DISCONNECTED
    if reason == 'revoked':
        return HOST_REVOKED
    if reason == 'reconnect':
        return HOST_RECONNECT
    return HOST_UNPAIRED


def _view(ok, state, message, banner, local, can_check_in):
    uploads = _uploads()
    return {
        'ok': ok,
        'state': state,
        'code': None if ok else 'connect_required',
        'message': '' if ok else (LAN_MESSAGE if not local else message),
        'banner': banner,
        'devMode': state == 'dev',
        'canPair': bool(local) and uploads not in ('0', '1'),
        'canCheckIn': bool(can_check_in and local),
    }


def public_status(directory, local, now=None):
    """Browser-safe connection state. No credential, code, or shop key."""
    if dev_escape():
        return _view(True, 'dev', '', DEV_BANNER, local, False)
    if test_harness_open():
        return _view(True, 'ok', '', None, local, False)
    stamp = _stamp(now)
    token, _source = _token(directory)
    uploads = _uploads()
    with LOCK:
        state = _read_state(directory)
        reason = state.get('reason') if isinstance(state.get('reason'), str) else ''
        last = state.get('lastOkAt')
        if token and not isinstance(last, int):
            last = stamp
            state = {'v': 1, 'lastOkAt': stamp, 'lastAttemptAt': stamp, 'reason': ''}
            _write_state(directory, state)
            reason = ''
    if not token:
        return _view(False, reason or 'unpaired', _closed_message(reason, uploads), None, local, False)
    age = stamp - last
    if age < 0:
        age = 0
    if age >= CHECK_IN_MAX_AGE:
        return _view(False, 'reconnect', _closed_message('reconnect', uploads), None, local, True)
    if age >= OFFLINE_BANNER_AFTER:
        days = max(OFFLINE_BANNER_AFTER_DAYS, age // DAY_SECONDS)
        banner = (
            f'OUTPUT has been unreachable for {days} days. '
            f'This computer keeps working until {CHECK_IN_MAX_AGE_DAYS} days from the last check-in.'
        )
        return _view(True, 'offline', '', banner, local, False)
    return _view(True, 'ok', '', None, local, False)


def _post(directory, raw, token):
    request = Request(
        endpoint(directory),
        data=raw,
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )
    try:
        with build_opener(telemetry_sender.NoRedirect()).open(request, timeout=10) as response:
            return response.status, response.read(16385)
    except HTTPError as error:
        try:
            detail = error.read(16385)
        except Exception:
            detail = b''
        return error.code, detail
    except (OSError, URLError, TimeoutError):
        raise Offline


def check_in(directory, *, transport=None, now=None, local=True):
    """Ask OUTPUT whether this credential is still paired. Sends appVersion only."""
    token, _source = _token(directory)
    if not token or dev_escape() or test_harness_open():
        return public_status(directory, local, now=now)
    raw = json.dumps({'appVersion': VERSION}, separators=(',', ':')).encode()
    stamp = _stamp(now)
    try:
        status, body = transport(raw, token) if transport else _post(directory, raw, token)
    except Offline:
        with LOCK:
            state = _read_state(directory)
            state['lastAttemptAt'] = stamp
            state['v'] = 1
            _write_state(directory, state)
        return public_status(directory, local, now=stamp)
    kind = classify(status, body)
    if kind == 'revoked':
        with LOCK:
            _mark_revoked(directory, stamp)
    elif kind == 'ok':
        with LOCK:
            _write_state(directory, {'v': 1, 'lastOkAt': stamp, 'lastAttemptAt': stamp, 'reason': ''})
    else:
        with LOCK:
            state = _read_state(directory)
            state['v'] = 1
            state['lastAttemptAt'] = stamp
            _write_state(directory, state)
    return public_status(directory, local, now=stamp)


def run(directory, stop):
    """Background check-in. A network failure must not stop nesting."""
    while not stop.is_set():
        try:
            if not test_harness_open() and not dev_escape():
                token, _source = _token(directory)
                if token:
                    check_in(directory)
        except Exception:
            pass
        if stop.wait(6 * 60 * 60):
            return
