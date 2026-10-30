"""Shop PIN and browser sessions for computers that are not the host.

The PIN is never stored or logged. The data directory keeps a random salt and
an scrypt hash. A designer browser gets an HttpOnly cookie, not the write token.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

PIN_FILE = 'shop-pin.json'
COOKIE = 'eznest_session'
LOCK_AFTER = 5
LOCK_SECONDS = 60
LOCK_CAP_SHIFT = 6
GLOBAL_ALERT_AFTER = 15
IDLE_SECONDS = 60 * 60
ABSOLUTE_SECONDS = 8 * 60 * 60
SESSION_SECONDS = ABSOLUTE_SECONDS
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
_MAX_N = 2 ** 15
_LOG = logging.getLogger('eznest.pin')

_guard = threading.Lock()
_failures = {}
_sessions = {}
_global = {'failures': 0, 'acked': 0}
_pin_seen = {}  # last PIN file check: stat key, status, fingerprint


def _now(now):
    return time.monotonic() if now is None else now


def _pin_path(directory):
    return Path(directory) / PIN_FILE


def normalize_ip(value):
    """Treat IPv4-mapped IPv6 as the IPv4 address, including ::ffff:127.0.0.1."""
    if not isinstance(value, str):
        return 'unknown'
    text = value.strip().lower()
    if text.startswith('::ffff:'):
        mapped = text[len('::ffff:'):]
        try:
            address = ipaddress.ip_address(mapped)
        except ValueError:
            return text
        if address.version == 4:
            return str(address)
    return text


def _plausible(pin):
    """Attempts that can be checked, including a PIN saved before the 8-digit rule."""
    if not isinstance(pin, str) or not pin.isascii() or not pin.isprintable():
        return False
    if any(char.isspace() for char in pin):
        return False
    if pin.isdigit():
        return 6 <= len(pin) <= 12
    return 10 <= len(pin) <= 64


def _meets_current_rule(pin):
    if not isinstance(pin, str) or not _plausible(pin):
        return False
    if pin.isdigit():
        return 8 <= len(pin) <= 12
    return any(char.isalpha() for char in pin)


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
    try:
        return _parse_record(_pin_path(directory).read_bytes())
    except OSError:
        return None


def _parse_record(raw):
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
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
    return {'salt': salt, 'hash': digest, 'n': n, 'r': r, 'p': p, 'policy': 2 if data.get('policy') == 2 else 0}


PIN_REHASH_SECONDS = 5      # the PIN file's contents are re-checked at least this often
PIN_UNREADABLE_SECONDS = 60  # how long sessions survive a PIN file that can't be read


def pin_status(directory, now=None):
    """'ok', 'missing' or 'invalid' for the PIN file, or 'unknown' when it could not be read
    right now (for example a backup tool or antivirus holding it).

    The file is re-read when its size, times or file id change, and at least every few
    seconds anyway, so a replacement with the same size and time is still noticed.
    A PIN file that changes outside the app (restored, copied in, edited) ends every
    shop-network session, the same as setting a new PIN in the app."""
    now = _now(now)
    path = _pin_path(directory)
    try:
        info = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return _remember(path, None, 'missing', None, now)
    except OSError:
        return _unreadable(path, now)
    if not path.is_file():
        return _remember(path, None, 'invalid', None, now)
    key = (str(path), info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev, info.st_size)
    with _guard:
        if _pin_seen.get('key') == key and now - _pin_seen.get('read_at', now) < PIN_REHASH_SECONDS:
            return _pin_seen['status']
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return _remember(path, None, 'missing', None, now)
    except OSError:
        return _unreadable(path, now)
    if _parse_record(raw) is None:
        return _remember(path, key, 'invalid', None, now)
    return _remember(path, key, 'ok', hashlib.sha256(raw).hexdigest(), now)


def _unreadable(path, now):
    with _guard:
        if _pin_seen.get('path') != str(path) or _pin_seen.get('unreadable_since') is None:
            _pin_seen['unreadable_since'] = now
        _pin_seen['key'] = None
    return 'unknown'


def _remember(path, key, status, fingerprint, now):
    with _guard:
        before = _pin_seen.get('fingerprint') if _pin_seen.get('path') == str(path) else None
        if status != 'ok' or (before is not None and before != fingerprint):
            _sessions.clear()
        _pin_seen.update(path=str(path), key=key, status=status, fingerprint=fingerprint,
                         read_at=now, unreadable_since=None)
    return status


def lan_sessions_allowed(directory, now=None):
    """False ends shop-network sessions. A read that fails for a moment keeps the last
    known answer instead of logging every shop computer out; after a minute of failed
    reads, sessions end."""
    now = _now(now)
    status = pin_status(directory, now)
    if status == 'unknown':
        with _guard:
            same = _pin_seen.get('path') == str(_pin_path(directory))
            since = _pin_seen.get('unreadable_since')
            if same and since is not None and now - since <= PIN_UNREADABLE_SECONDS:
                status = _pin_seen.get('status')
            else:
                _sessions.clear()
                status = None
    return status == 'ok'


def pin_configured(directory):
    return _record(directory) is not None


def pin_is_weak(directory):
    """A hash from before the 8-digit rule still signs in. The host should replace it."""
    record = _record(directory)
    return record is not None and record['policy'] != 2


def set_pin(directory, pin):
    if not _meets_current_rule(pin):
        raise ValueError('Use 8 to 12 digits, or a passphrase of at least 10 characters with a letter.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode('utf-8'), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    payload = {
        'v': 1,
        'policy': 2,
        'salt': salt.hex(),
        'hash': digest.hex(),
        'n': SCRYPT_N,
        'r': SCRYPT_R,
        'p': SCRYPT_P,
    }
    _write_private(_pin_path(directory), json.dumps(payload, indent=2) + '\n')
    clear_sessions()
    pin_status(directory)


def _matches(directory, pin):
    record = _record(directory)
    if record is None or not _plausible(pin):
        return False
    digest = hashlib.scrypt(
        pin.encode('utf-8'), salt=record['salt'], n=record['n'], r=record['r'], p=record['p'],
        dklen=len(record['hash']), maxmem=64 * 1024 * 1024)
    return hmac.compare_digest(digest, record['hash'])


def backoff_seconds(strikes):
    """Each new lock for one address waits twice as long, up to 64 minutes."""
    shift = min(max(int(strikes), 1) - 1, LOCK_CAP_SHIFT)
    return LOCK_SECONDS * (2 ** shift)


def _state(ip, now):
    state = _failures.get(ip) or {'count': 0, 'locked_until': 0.0, 'strikes': 0}
    if state['locked_until'] and now >= state['locked_until']:
        return {'count': 0, 'locked_until': 0.0, 'strikes': state.get('strikes', 0)}
    return state


def _note_failure():
    with _guard:
        _global['failures'] += 1
        pending = _global['failures'] - _global['acked']
        crossed = pending == GLOBAL_ALERT_AFTER or (pending > GLOBAL_ALERT_AFTER and (pending - GLOBAL_ALERT_AFTER) % 10 == 0)
    if crossed:
        _LOG.warning(
            'eznest shop PIN: %s failed attempts since the host last reviewed them. '
            'This includes tries from rotating addresses. Designers are not locked out by this notice.',
            pending)


def alert_status():
    with _guard:
        pending = _global['failures'] - _global['acked']
    return {'active': pending >= GLOBAL_ALERT_AFTER, 'failures': pending}


def acknowledge_alert():
    with _guard:
        _global['acked'] = _global['failures']
    return alert_status()


def login_attempt(directory, ip, pin, now=None):
    """Return ok, missing, unreadable, locked, or denied.

    One address waits longer after each lock. A global counter only warns the
    host, so a different address is not locked out by someone else's tries.
    """
    now = _now(now)
    # Note the PIN file this session is based on.
    if pin_status(directory, now) == 'unknown':
        return 'unreadable'
    ip = normalize_ip(ip)
    if not pin_configured(directory):
        return 'missing'
    with _guard:
        state = _state(ip, now)
        locked = bool(state['locked_until'] and now < state['locked_until'])
        if locked:
            _failures[ip] = state
    if locked:
        _note_failure()
        return 'locked'
    if _matches(directory, pin if isinstance(pin, str) else ''):
        with _guard:
            _failures.pop(ip, None)
        return 'ok'
    with _guard:
        state = _state(ip, now)
        if state['locked_until'] and now < state['locked_until']:
            result = 'locked'
        else:
            state['count'] = state.get('count', 0) + 1
            if state['count'] >= LOCK_AFTER:
                state['strikes'] = int(state.get('strikes', 0)) + 1
                state['locked_until'] = now + backoff_seconds(state['strikes'])
                state['count'] = 0
            _failures[ip] = state
            result = 'denied'
    _note_failure()
    return result


def _prune(now):
    expired = []
    for key, record in _sessions.items():
        if now - record['issued'] > ABSOLUTE_SECONDS or now - record['seen'] > IDLE_SECONDS:
            expired.append(key)
    for key in expired:
        _sessions.pop(key, None)


def issue_session(ip, now=None):
    now = _now(now)
    ip = normalize_ip(ip)
    sid = secrets.token_urlsafe(32)
    with _guard:
        _prune(now)
        _sessions[sid] = {'issued': now, 'seen': now, 'ip': ip}
    return sid


def session_valid(sid, ip, now=None):
    if not isinstance(sid, str) or not 20 <= len(sid) <= 200:
        return False
    now = _now(now)
    ip = normalize_ip(ip)
    with _guard:
        record = _sessions.get(sid)
        if record is None:
            return False
        if record['ip'] != ip or now - record['issued'] > ABSOLUTE_SECONDS or now - record['seen'] > IDLE_SECONDS:
            _sessions.pop(sid, None)
            return False
        record['seen'] = now
    return True


def revoke_session(sid):
    if not isinstance(sid, str):
        return
    with _guard:
        _sessions.pop(sid, None)


def clear_sessions():
    with _guard:
        _sessions.clear()


def reset_for_tests():
    with _guard:
        _failures.clear()
        _sessions.clear()
        _global['failures'] = 0
        _global['acked'] = 0
        _pin_seen.clear()


def cookie_header(sid, secure=False):
    # Secure is set only for HTTPS. On plain HTTP the browser would drop it.
    header = f'{COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={ABSOLUTE_SECONDS}'
    if secure:
        header += '; Secure'
    return header


def clear_cookie_header(secure=False):
    header = f'{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
    if secure:
        header += '; Secure'
    return header


def read_cookie(header, name=COOKIE):
    if not isinstance(header, str) or len(header) > 4096:
        return ''
    for part in header.split(';'):
        key, separator, value = part.strip().partition('=')
        if separator and key == name and value and len(value) <= 200 and all(c.isalnum() or c in '-_' for c in value):
            return value
    return ''
