"""Shop PIN and browser sessions for computers that are not the host.

The PIN is never stored or logged. The data directory keeps a random salt and
an scrypt hash. A designer browser gets an HttpOnly cookie, not the write token.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

PIN_FILE = 'shop-pin.json'
COOKIE = 'eznest_session'
LOCK_AFTER = 5
LOCK_SECONDS = 60
SESSION_SECONDS = 12 * 60 * 60
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
_MAX_N = 2 ** 15

_guard = threading.Lock()
_failures = {}
_sessions = {}


def _now(now):
    return time.monotonic() if now is None else now


def _pin_path(directory):
    return Path(directory) / PIN_FILE


def _acceptable(pin):
    return isinstance(pin, str) and pin.isascii() and pin.isdigit() and 6 <= len(pin) <= 12


def _write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    handle = os.open(temporary, flags, 0o600)
    try:
        os.write(handle, text.encode('utf-8'))
    finally:
        os.close(handle)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _record(directory):
    path = _pin_path(directory)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        salt = bytes.fromhex(data.get('salt', ''))
        digest = bytes.fromhex(data.get('hash', ''))
        n = int(data.get('n'))
        r = int(data.get('r'))
        p = int(data.get('p'))
    except (TypeError, ValueError):
        return None
    if not salt or not digest or not (2 ** 12 <= n <= _MAX_N) or r != SCRYPT_R or p != SCRYPT_P:
        return None
    return {'salt': salt, 'hash': digest, 'n': n, 'r': r, 'p': p}


def pin_configured(directory):
    return _record(directory) is not None


def set_pin(directory, pin):
    if not _acceptable(pin):
        raise ValueError('Use 6 to 12 digits for the shop PIN.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode('utf-8'), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    payload = {
        'v': 1,
        'salt': salt.hex(),
        'hash': digest.hex(),
        'n': SCRYPT_N,
        'r': SCRYPT_R,
        'p': SCRYPT_P,
    }
    _write_private(_pin_path(directory), json.dumps(payload, indent=2) + '\n')
    clear_sessions()


def _matches(directory, pin):
    record = _record(directory)
    if record is None or not _acceptable(pin):
        return False
    digest = hashlib.scrypt(
        pin.encode('utf-8'), salt=record['salt'], n=record['n'], r=record['r'], p=record['p'],
        dklen=len(record['hash']), maxmem=64 * 1024 * 1024)
    return hmac.compare_digest(digest, record['hash'])


def _state(ip, now):
    state = _failures.get(ip) or {'count': 0, 'locked_until': 0.0}
    if state['locked_until'] and now >= state['locked_until']:
        state = {'count': 0, 'locked_until': 0.0}
    return state


def login_attempt(directory, ip, pin, now=None):
    """Return ok, missing, locked, or denied. A lock does not grow when tries continue."""
    now = _now(now)
    if not isinstance(ip, str) or not ip:
        ip = 'unknown'
    if not pin_configured(directory):
        return 'missing'
    with _guard:
        state = _state(ip, now)
        if state['locked_until'] and now < state['locked_until']:
            _failures[ip] = state
            return 'locked'
    if _matches(directory, pin if isinstance(pin, str) else ''):
        with _guard:
            _failures.pop(ip, None)
        return 'ok'
    with _guard:
        state = _state(ip, now)
        if state['locked_until'] and now < state['locked_until']:
            return 'locked'
        state['count'] += 1
        if state['count'] >= LOCK_AFTER:
            state['locked_until'] = now + LOCK_SECONDS
            state['count'] = LOCK_AFTER
        _failures[ip] = state
    return 'denied'


def issue_session(now=None):
    now = _now(now)
    sid = secrets.token_urlsafe(32)
    with _guard:
        expired = [key for key, until in _sessions.items() if until <= now]
        for key in expired:
            _sessions.pop(key, None)
        _sessions[sid] = now + SESSION_SECONDS
    return sid


def session_valid(sid, now=None):
    if not isinstance(sid, str) or not 20 <= len(sid) <= 200:
        return False
    now = _now(now)
    with _guard:
        until = _sessions.get(sid)
        if until is None or until <= now:
            _sessions.pop(sid, None)
            return False
    return True


def clear_sessions():
    with _guard:
        _sessions.clear()


def reset_for_tests():
    with _guard:
        _failures.clear()
        _sessions.clear()


def cookie_header(sid):
    # The shop page is plain HTTP, so Secure would stop the browser from storing this.
    return f'{COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}'


def read_cookie(header, name=COOKIE):
    if not isinstance(header, str) or len(header) > 4096:
        return ''
    for part in header.split(';'):
        key, separator, value = part.strip().partition('=')
        if separator and key == name and value and len(value) <= 200 and all(c.isalnum() or c in '-_' for c in value):
            return value
    return ''
