"""Require a shop host to be connected to OUTPUT.

Nesting, sending, and stock stay closed until this computer has a shop
credential and a current check-in. After a successful pairing or check-in,
an unreachable OUTPUT does not stop the shop until CHECK_IN_MAX_AGE_DAYS
have passed. A banner appears after OFFLINE_BANNER_AFTER_DAYS. The check-in
body is only the app version. The computer name and installation id are sent
once, by pairing.

The check-in record is signed with a key derived from the shop credential.
A record from the previous build has no signature. If it is otherwise
current, the first load signs it and the offline grace continues. Any other
missing, unreadable, or mismatched record stays closed until a live check-in
or pairing succeeds. A check-in time ahead of this computer is not current.
Revoked credentials are part of the signed record.

The credential is never written here, logged, or returned to the browser.
"""
import hashlib
import hmac
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
REVOCATION_NAME = 'output-revocations.json'
RELEASE_MARKER = '.eznest-release'
DEV_BANNER = 'DEV MODE: not connected to OUTPUT'

HOST_UNPAIRED = 'Connect this computer to OUTPUT before nesting, sending, or changing stock.'
HOST_DISCONNECTED = 'This computer is disconnected from OUTPUT. Connect again to nest, send, or change stock.'
HOST_REVOKED = 'OUTPUT says this computer is no longer connected. Paste a new pairing code.'
HOST_RECONNECT = (
    f'Reconnect this computer to OUTPUT. The last successful check-in was more than {CHECK_IN_MAX_AGE_DAYS} days ago.'
)
HOST_CHECKIN = 'This computer needs a current OUTPUT check-in before nesting, sending, or changing stock.'
HOST_UPLOADS_OFF = (
    'This run has OUTPUT delivery turned off. Start Ez Nest without that setting, then connect with a pairing code.'
)
HOST_LAUNCH_MISSING = 'This computer uses OUTPUT launch settings, but the shop credential is missing.'
LAN_MESSAGE = 'Ask the shop computer to connect to OUTPUT.'

REVOKED_CODES = frozenset({
    'unpaired', 'revoked', 'invalid_credential', 'invalid_token', 'unauthorized', 'not_paired',
})
LOCK = threading.Lock()
_STATE_FIELDS = ('v', 'lastOkAt', 'lastAttemptAt', 'reason', 'credential', 'revoked')


class Offline(Exception):
    """OUTPUT did not answer. The credential is unchanged."""


def source_checkout():
    """True when this process is the repo's Python files, not an installed build."""
    if getattr(sys, 'frozen', False) or _release_marked() or _installed_module():
        return False
    root = Path(__file__).resolve().parent
    return (root / 'launcher.py').is_file() and (root / 'version.json').is_file() and (root / 'server.py').is_file()


def _release_marked():
    return (Path(__file__).resolve().parent / RELEASE_MARKER).is_file()


def _installed_module():
    """True when the image build wrote an installed-build module."""
    try:
        import eznest_build
    except ImportError:
        return False
    return eznest_build.INSTALLED is True


def dev_mode():
    """Labeled dev mode. Installed builds and the container image never qualify."""
    return source_checkout() and os.environ.get('EZ_NEST_DEV') == '1'


def dev_escape():
    """EZ_NEST_DEV_NO_OUTPUT=1 counts only in labeled dev mode on a source checkout."""
    return dev_mode() and os.environ.get('EZ_NEST_DEV_NO_OUTPUT') == '1'


def gate_opt_out():
    """EZ_NEST_OUTPUT_GATE_OPEN=1 counts only in labeled dev mode on a source checkout."""
    return dev_mode() and os.environ.get('EZ_NEST_OUTPUT_GATE_OPEN') == '1'


def endpoint(directory=None):
    return shop_deploy.output_base_url(directory) + '/api/shop/agent/check-in'


def credential_fingerprint(token):
    """One-way name for a credential. The credential itself is not stored."""
    return hashlib.sha256(b'eznest-output-credential/1\0' + token.encode('utf-8')).hexdigest()


def _state_key(token):
    return hashlib.sha256(b'eznest-output-checkin/1\0' + token.encode('utf-8')).digest()


def _state_path(directory):
    return Path(directory) / STATE_NAME


def _revocation_path(directory):
    return Path(directory) / REVOCATION_NAME


def _read_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_state(directory):
    return _read_json(_state_path(directory))


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
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
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _write_state(directory, payload):
    _write_json(_state_path(directory), payload)


def _stamp(now):
    return int(time.time() if now is None else now)


def _fingerprint_list(value):
    if not isinstance(value, list):
        return []
    found = []
    for item in value:
        if isinstance(item, str) and len(item) == 64 and all(char in '0123456789abcdef' for char in item) and item not in found:
            found.append(item)
    return sorted(found)


def _signed_body(payload):
    last = payload.get('lastOkAt')
    attempt = payload.get('lastAttemptAt')
    reason = payload.get('reason') if isinstance(payload.get('reason'), str) else ''
    credential = payload.get('credential') if isinstance(payload.get('credential'), str) else ''
    return {
        'v': 2,
        'lastOkAt': last if isinstance(last, int) or last is None else None,
        'lastAttemptAt': attempt if isinstance(attempt, int) else None,
        'reason': reason,
        'credential': credential,
        'revoked': _fingerprint_list(payload.get('revoked')),
    }


def _canonical(body):
    return json.dumps({key: body[key] for key in _STATE_FIELDS}, separators=(',', ':'), sort_keys=True).encode()


def _mac(token, body):
    return hmac.new(_state_key(token), _canonical(body), hashlib.sha256).hexdigest()


def _mac_ok(token, payload):
    if not token or not isinstance(payload, dict):
        return False
    mac = payload.get('mac')
    if not isinstance(mac, str) or len(mac) != 64:
        return False
    body = _signed_body(payload)
    if body['credential'] != credential_fingerprint(token):
        return False
    return hmac.compare_digest(_mac(token, body), mac)


def _stored_revoked(directory):
    found = set(_read_revocations(directory))
    raw = _read_state(directory)
    if isinstance(raw, dict):
        found.update(_fingerprint_list(raw.get('revoked')))
    return found


def _write_signed(directory, token, *, last_ok, attempt, reason, also=()):
    revoked = _stored_revoked(directory)
    revoked.update(also)
    body = _signed_body({
        'lastOkAt': last_ok,
        'lastAttemptAt': attempt,
        'reason': reason,
        'credential': credential_fingerprint(token),
        'revoked': sorted(revoked),
    })
    stored = dict(body)
    stored['mac'] = _mac(token, body)
    _write_state(directory, stored)


def _known_revoked(directory, token):
    return bool(token) and credential_fingerprint(token) in _stored_revoked(directory)


def _record_altered(directory, token):
    """A signature bound to this credential that does not verify stays closed."""
    raw = _read_state(directory)
    if not token or not isinstance(raw, dict):
        return False
    mac = raw.get('mac')
    if not isinstance(mac, str) or len(mac) != 64:
        return False
    if raw.get('credential') != credential_fingerprint(token):
        return False
    return not _mac_ok(token, raw)


def _legacy_last_ok(raw, stamp):
    """Previous builds stored an unsigned check-in. Only a current one is signed."""
    if not isinstance(raw, dict):
        return None
    mac = raw.get('mac')
    if isinstance(mac, str) and mac:
        return None
    last = raw.get('lastOkAt')
    if isinstance(last, bool) or not isinstance(last, int) or last <= 0 or last > stamp:
        return None
    if stamp - last >= CHECK_IN_MAX_AGE:
        return None
    reason = raw.get('reason') if isinstance(raw.get('reason'), str) else ''
    if reason in ('revoked', 'disconnected'):
        return None
    return last


def _migrate_unsigned(directory, token, stamp):
    if not token or _known_revoked(directory, token):
        return
    raw = _read_state(directory)
    last = _legacy_last_ok(raw, stamp)
    if last is None:
        return
    attempt = raw.get('lastAttemptAt') if isinstance(raw.get('lastAttemptAt'), int) and not isinstance(raw.get('lastAttemptAt'), bool) else last
    _write_signed(directory, token, last_ok=last, attempt=attempt, reason='')


def _read_revocations(directory):
    payload = _read_json(_revocation_path(directory))
    items = payload.get('fingerprints') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return set()
    return {item for item in items if isinstance(item, str) and len(item) == 64 and all(char in '0123456789abcdef' for char in item)}


def _write_revocations(directory, fingerprints):
    _write_json(_revocation_path(directory), {'v': 1, 'fingerprints': sorted(fingerprints)})


def _revoked(directory, token):
    return _known_revoked(directory, token)


def _remember_revoked(directory, token):
    if not token:
        return
    fingerprint = credential_fingerprint(token)
    fingerprints = _read_revocations(directory)
    fingerprints.add(fingerprint)
    _write_revocations(directory, fingerprints)
    raw = _read_state(directory)
    attempt = raw.get('lastAttemptAt') if isinstance(raw, dict) and isinstance(raw.get('lastAttemptAt'), int) else _stamp(None)
    _write_signed(directory, token, last_ok=None, attempt=attempt, reason='revoked', also=(fingerprint,))


def note_paired(directory, now=None):
    """A successful pairing is the first check-in for that credential."""
    stamp = _stamp(now)
    token, _source = _token(directory)
    with LOCK:
        if not token or _known_revoked(directory, token) or _record_altered(directory, token):
            return
        _write_signed(directory, token, last_ok=stamp, attempt=stamp, reason='')


def note_disconnected(directory, now=None):
    stamp = _stamp(now)
    with LOCK:
        _write_state(directory, {'v': 2, 'lastOkAt': None, 'lastAttemptAt': stamp, 'reason': 'disconnected'})


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


def _mark_revoked(directory, token, now):
    if token:
        _remember_revoked(directory, token)
    else:
        _write_state(directory, {'v': 2, 'lastOkAt': None, 'lastAttemptAt': _stamp(now), 'reason': 'revoked', 'revoked': []})
    try:
        telemetry_sender.revoke(directory)
    except Exception:
        pass
    output_credential.clear(directory)


def _closed_message(reason, uploads, *, has_token):
    if uploads == '0':
        return HOST_UPLOADS_OFF
    if uploads == '1' and not has_token:
        return HOST_LAUNCH_MISSING
    if reason == 'disconnected':
        return HOST_DISCONNECTED
    if reason == 'revoked':
        return HOST_REVOKED
    if reason == 'reconnect':
        return HOST_RECONNECT
    if reason == 'unchecked':
        return HOST_CHECKIN
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


def _verdict(directory, token, stamp):
    _migrate_unsigned(directory, token, stamp)
    raw = _read_state(directory)
    reason = raw.get('reason') if isinstance(raw.get('reason'), str) else ''
    if token and (_known_revoked(directory, token) or _record_altered(directory, token)):
        return {'open': False, 'reason': 'revoked', 'state': 'revoked', 'can_check_in': False}
    if not token:
        return {'open': False, 'reason': reason, 'state': reason or 'unpaired', 'can_check_in': False}
    if not _mac_ok(token, raw):
        return {'open': False, 'reason': 'unchecked', 'state': 'unchecked', 'can_check_in': True}
    last = raw.get('lastOkAt')
    if isinstance(last, int) and last > stamp:
        return {'open': False, 'reason': 'reconnect', 'state': 'reconnect', 'can_check_in': True}
    if not isinstance(last, int) or last <= 0:
        closed = reason if reason in ('disconnected', 'revoked') else 'unchecked'
        return {'open': False, 'reason': closed, 'state': closed, 'can_check_in': closed != 'revoked'}
    return {'open': True, 'reason': '', 'state': 'ok', 'age': stamp - last, 'can_check_in': False}


def public_status(directory, local, now=None):
    """Browser-safe connection state. No credential, code, or shop key."""
    if dev_escape():
        return _view(True, 'dev', '', DEV_BANNER, local, False)
    if gate_opt_out():
        return _view(True, 'ok', '', None, local, False)
    stamp = _stamp(now)
    token, _source = _token(directory)
    uploads = _uploads()
    with LOCK:
        verdict = _verdict(directory, token, stamp)
    if not verdict['open']:
        return _view(
            False,
            verdict['state'],
            _closed_message(verdict['reason'], uploads, has_token=bool(token)),
            None,
            local,
            verdict['can_check_in'],
        )
    age = verdict['age']
    if age >= CHECK_IN_MAX_AGE:
        return _view(False, 'reconnect', _closed_message('reconnect', uploads, has_token=True), None, local, True)
    if age >= OFFLINE_BANNER_AFTER:
        days = max(OFFLINE_BANNER_AFTER_DAYS, age // DAY_SECONDS)
        banner = (
            f'OUTPUT has been unreachable for {days} days. '
            f'This computer keeps working until {CHECK_IN_MAX_AGE_DAYS} days from the last check-in.'
        )
        return _view(True, 'offline', '', banner, local, False)
    return _view(True, 'ok', '', None, local, False)


def _touch_attempt(directory, token, stamp):
    state = _read_state(directory)
    if not _mac_ok(token, state):
        return
    last = state.get('lastOkAt') if isinstance(state.get('lastOkAt'), int) else None
    reason = state.get('reason') if isinstance(state.get('reason'), str) else ''
    _write_signed(directory, token, last_ok=last, attempt=stamp, reason=reason)


def _post(directory, raw, token):
    url = endpoint(directory)
    if not shop_deploy.allowed_output_request(url):
        raise Offline
    request = Request(
        url,
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
    if not token or dev_escape() or gate_opt_out():
        return public_status(directory, local, now=now)
    if _known_revoked(directory, token) or _record_altered(directory, token):
        if _record_altered(directory, token):
            with LOCK:
                _mark_revoked(directory, token, _stamp(now))
        return public_status(directory, local, now=now)
    raw = json.dumps({'appVersion': VERSION}, separators=(',', ':')).encode()
    stamp = _stamp(now)
    try:
        status, body = transport(raw, token) if transport else _post(directory, raw, token)
    except Offline:
        with LOCK:
            _touch_attempt(directory, token, stamp)
        return public_status(directory, local, now=stamp)
    kind = classify(status, body)
    if kind == 'revoked' or _known_revoked(directory, token) or _record_altered(directory, token):
        with LOCK:
            _mark_revoked(directory, token, stamp)
    elif kind == 'ok':
        with LOCK:
            if _known_revoked(directory, token) or _record_altered(directory, token):
                _mark_revoked(directory, token, stamp)
            else:
                _write_signed(directory, token, last_ok=stamp, attempt=stamp, reason='')
    else:
        with LOCK:
            _touch_attempt(directory, token, stamp)
    return public_status(directory, local, now=stamp)


def run(directory, stop):
    """Background check-in. A network failure must not stop nesting."""
    while not stop.is_set():
        try:
            if not gate_opt_out() and not dev_escape():
                token, _source = _token(directory)
                if token and not _known_revoked(directory, token) and not _record_altered(directory, token):
                    check_in(directory)
        except Exception:
            pass
        if stop.wait(60 * 60):
            return


SEEN_RECENTLY = DAY_SECONDS


def link_status(directory, local, now=None):
    """Browser-safe OUTPUT link for the header control. Never gates nesting.

    state is unpaired, connected, stale (paired, no check-in within a day,
    the same window OUTPUT uses for "seen recently"), or revoked.
    """
    stamp = _stamp(now)
    info = telemetry_sender.connection(directory)
    token = info.get('token')
    base = shop_deploy.output_base_url(directory)
    view = {
        'state': 'unpaired', 'shopName': info.get('shopName'), 'lastCheckInAt': None,
        'secondsSinceCheckIn': None, 'canPair': bool(local) and _uploads() not in ('0', '1'),
        'connectUrl': base + '/outpost/ez-nest',
    }
    with LOCK:
        raw = _read_state(directory)
        revoked = bool(token) and (_known_revoked(directory, token) or _record_altered(directory, token))
        signed = bool(token) and _mac_ok(token, raw)
    if not token:
        if raw.get('reason') == 'revoked':
            view['state'] = 'revoked'
        return view
    if revoked:
        view['state'] = 'revoked'
        return view
    last = raw.get('lastOkAt') if signed else None
    if isinstance(last, int) and not isinstance(last, bool) and 0 < last <= stamp:
        view['lastCheckInAt'] = last
        view['secondsSinceCheckIn'] = stamp - last
        view['state'] = 'connected' if stamp - last < SEEN_RECENTLY else 'stale'
    else:
        view['state'] = 'stale'
    return view
