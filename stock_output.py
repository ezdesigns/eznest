"""Read-only stock summary for OUTPUT.

The host opts in. A paired computer then sends eznest-stock/1. Roll names,
widths, length left, reserved length, and a low marker are the whole payload.
Reservations, job codes, cost, supplier, profile text, file names, and customer
details stay on this computer. The shop credential is not written to logs.
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import material_inventory
import shop_deploy
import telemetry
import telemetry_sender
from app_info import VERSION

SCHEMA = 'eznest-stock/1'
PAYLOAD_KEYS = ('schema', 'requestId', 'snapshotAt', 'appVersion', 'unit', 'rolls')
ROLL_KEYS = ('key', 'name', 'widthIn', 'leftFt', 'reservedFt', 'low')
MAX_ROLLS = 200
MAX_BYTES = 32768
NAME_LIMIT = 60
DEBOUNCE_SECONDS = 30
HEARTBEAT_SECONDS = 3600
BACKOFF_MIN = 30
BACKOFF_MAX = 900
STAMP_KEY = 'stock_output_stamp'
_JOB = re.compile(r'EZ-[0-9]{4,12}')
_CREDENTIAL = re.compile(r'osa_[A-Za-z0-9_-]{43}')
_PHONE = re.compile(r'(?<!\w)(?:\+?\d|\(\d{2,4}\))[\d ()-]*\d(?!\w)')
_INCH = {'in': Decimal('1'), 'cm': Decimal('1') / Decimal('2.54'), 'mm': Decimal('1') / Decimal('25.4')}
_MM = {'in': Decimal('25.4'), 'cm': Decimal('10'), 'mm': Decimal('1')}

LOCK = threading.RLock()
WAKE = threading.Event()
_SCHEDULE = {}


def clock():
    return time.monotonic()


def endpoint(directory):
    return shop_deploy.output_base_url(directory) + '/api/shop/agent/stock'


def deliver(method, url, payload, token):
    """Isolated telemetry transport. Tests replace this; it does not log."""
    return telemetry_sender.emit(payload, token, method=method, url=url) is True


def _sched(directory):
    key = str(Path(directory).resolve())
    return _SCHEDULE.setdefault(key, {
        'delete_pending': False,
        'not_before': 0,
        'backoff': BACKOFF_MIN,
        'last_success': None,
        'dirty_at': None,
        'sent_fingerprint': None,
    })


def note_change(directory, now=None):
    with LOCK:
        _sched(directory)['dirty_at'] = clock() if now is None else now
    WAKE.set()


def apply_settings(directory, before, after):
    """React to the host settings save. Turning sharing off clears the remote copy."""
    was = before.get('shareStockSummary') is True
    enabled = after.get('shareStockSummary') is True
    names_before = before.get('showRollNames') is not False
    names_after = after.get('showRollNames') is not False
    with LOCK:
        sched = _sched(directory)
        if was and not enabled:
            sched['delete_pending'] = True
            sched['not_before'] = 0
            sched['backoff'] = BACKOFF_MIN
        elif enabled and not was:
            sched['delete_pending'] = False
            sched['last_success'] = None
            sched['not_before'] = 0
            sched['dirty_at'] = None
        elif enabled and names_before != names_after:
            sched['dirty_at'] = clock()
    WAKE.set()


def _credential(directory):
    if os.environ.get('EZ_NEST_OUTPUT_UPLOADS') == '0':
        return None
    token = telemetry_sender.configuration(directory)
    if not isinstance(token, str):
        return None
    return token


def _sharing(directory):
    return shop_deploy.load_shop(directory).get('shareStockSummary') is True


def _show_names(directory):
    return shop_deploy.load_shop(directory).get('showRollNames') is not False


def tenth(value):
    number = Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    return Decimal(str(value).strip())


def plain_name(value, show):
    """Plain text up to 60 characters, or null when the name is unsafe or hidden."""
    if not show or not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > NAME_LIMIT:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None
    lowered = text.casefold()
    if '/' in text or '\\' in text or '@' in text or '://' in lowered or lowered.startswith('www.') or ' www.' in lowered:
        return None
    if _JOB.search(text) or _CREDENTIAL.search(text):
        return None
    if any(sum(char.isdigit() for char in match.group()) >= 8 for match in _PHONE.finditer(text)):
        return None
    if re.search(r'(^|[\s])[A-Za-z]:[\\/]', text) or '..' in text:
        return None
    return text


def _width_in(profile):
    return tenth(_decimal(profile.get('roll')) * _INCH[profile.get('unit')])


def _feet_from_amount(amount, unit):
    return tenth(_decimal(amount) * _MM[unit] / Decimal('304.8'))


def _feet_from_mm(mm):
    return tenth(_decimal(mm) / Decimal('304.8'))


def _low(profile, on_hand):
    if on_hand is None:
        return False
    unit = profile.get('unit')
    text = str(profile.get('available-length') or '').strip()
    left = _decimal(text) if text else _decimal(on_hand) / _MM[unit]
    low_text = str(profile.get('low-stock') or '').strip()
    roll_text = str(profile.get('roll-length') or '').strip()
    if low_text:
        threshold = _decimal(low_text)
    elif roll_text:
        threshold = _decimal(roll_text) * Decimal('0.1')
    else:
        threshold = Decimal(0)
    return left <= threshold


def _roll(material, show_names):
    if not isinstance(material, dict):
        return None
    identity = material.get('id')
    profile = material.get('profile')
    if not isinstance(identity, str) or not identity or not isinstance(profile, dict):
        return None
    if profile.get('unit') not in _INCH:
        return None
    try:
        width = _width_in(profile)
        on_hand = material.get('onHandMm')
        reserved = material.get('reservedMm')
        if on_hand is None:
            left = None
            low = False
        else:
            text = str(profile.get('available-length') or '').strip()
            left = _feet_from_amount(text, profile['unit']) if text else _feet_from_mm(on_hand)
            low = _low(profile, on_hand)
        held = 0 if reserved in (None, '') else _feet_from_mm(reserved)
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None
    return {
        'key': hashlib.sha256(identity.encode()).hexdigest()[:32],
        'name': plain_name(profile.get('preset-name'), show_names),
        'widthIn': width,
        'leftFt': left,
        'reservedFt': held,
        'low': low is True,
    }


def project_snapshot(snapshot, *, show_names, instance_id, snapshot_at):
    """Build the allowlisted payload. Extra local fields are dropped."""
    if not isinstance(snapshot, dict):
        raise ValueError('Stock snapshot is unavailable.')
    materials = snapshot.get('materials')
    if not isinstance(materials, list):
        materials = []
    rolls = []
    for material in sorted(materials, key=lambda item: str(item.get('id') if isinstance(item, dict) else '')):
        roll = _roll(material, show_names)
        if roll is not None:
            roll = {key: roll[key] for key in ROLL_KEYS if key in roll}
            if set(roll) != set(ROLL_KEYS):
                raise ValueError('Stock roll keys do not match the contract.')
            rolls.append(roll)
    chosen = rolls[:MAX_ROLLS]
    while True:
        fingerprint = hashlib.sha256(json.dumps(chosen, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        payload = {
            'schema': SCHEMA,
            'requestId': str(uuid.uuid5(uuid.NAMESPACE_URL, f'{SCHEMA}:{instance_id}:{fingerprint}')),
            'snapshotAt': snapshot_at(fingerprint) if callable(snapshot_at) else snapshot_at,
            'appVersion': VERSION,
            'unit': 'ft',
            'rolls': chosen,
        }
        if set(payload) != set(PAYLOAD_KEYS):
            raise ValueError('Stock summary keys do not match the contract.')
        raw = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) <= MAX_BYTES:
            return payload, fingerprint
        if not chosen:
            raise ValueError('Stock summary is larger than 32 KB.')
        chosen = chosen[:-1]


def _instance_id(directory):
    with telemetry.database(directory) as db:
        return db.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()[0]


def _stamp(directory, fingerprint):
    with telemetry.database(directory) as db:
        row = db.execute('SELECT value FROM metadata WHERE key=?', (STAMP_KEY,)).fetchone()
        state = json.loads(row[0]) if row else {}
        stamps = state.get('stamps') if isinstance(state.get('stamps'), dict) else {}
        if not isinstance(stamps.get(fingerprint), str):
            stamps[fingerprint] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            state = {'stamps': dict(list(stamps.items())[-8:])}
            db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (STAMP_KEY, json.dumps(state)))
        return stamps[fingerprint]


def build_payload(directory, names=None):
    show = _show_names(directory) if names is None else bool(names)
    snapshot = material_inventory.read(directory)
    payload, fingerprint = project_snapshot(
        snapshot, show_names=show, instance_id=_instance_id(directory), snapshot_at=lambda value: _stamp(directory, value))
    return payload, fingerprint


def public_status(directory, names=None):
    """Host preview. The credential is not included."""
    show = _show_names(directory) if names is None else bool(names)
    payload, _fingerprint = build_payload(directory, names=show)
    return {
        'share': _sharing(directory),
        'names': show,
        'paired': _credential(directory) is not None,
        'preview': payload,
    }


def _fail(sched, now):
    delay = sched['backoff']
    sched['not_before'] = now + delay
    sched['backoff'] = min(max(delay * 2, BACKOFF_MIN), BACKOFF_MAX)


def _send(directory, method, payload, token, paused=lambda: False):
    # Recheck at the transport boundary, after projection/debounce. Revoking
    # sharing still permits the pending DELETE that clears the remote copy.
    if paused() or token is None or _credential(directory) != token:
        return False
    if method == 'PUT':
        if not _sharing(directory):
            return False
    elif method != 'DELETE' or not _sched(directory)['delete_pending']:
        return False
    try:
        return deliver(method, endpoint(directory), payload, token) is True
    except Exception:
        return False


def tick(directory, now=None, *, paused=lambda: False):
    """One scheduling step. Returns seconds until the next check."""
    if paused():
        return 30
    now = clock() if now is None else now
    token = _credential(directory)
    share = _sharing(directory)
    with LOCK:
        sched = _sched(directory)
        if sched['delete_pending']:
            if token is None:
                if os.environ.get('EZ_NEST_OUTPUT_UPLOADS') == '0':
                    sched['delete_pending'] = False
                return 30
            if now < sched['not_before']:
                return sched['not_before'] - now
            pending = True
        else:
            pending = False
            if not share or token is None:
                return 30
            if now < sched['not_before']:
                return sched['not_before'] - now
    if pending:
        if _send(directory, 'DELETE', None, token, paused):
            with LOCK:
                sched = _sched(directory)
                if sched['delete_pending']:
                    sched['delete_pending'] = False
                    sched['backoff'] = BACKOFF_MIN
                    sched['not_before'] = now
                    sched['last_success'] = None
                    sched['dirty_at'] = None
            return 30
        with LOCK:
            _fail(_sched(directory), now)
            return _sched(directory)['not_before'] - now
    try:
        payload, fingerprint = build_payload(directory)
    except (OSError, ValueError, TypeError):
        return 30
    with LOCK:
        sched = _sched(directory)
        if not _sharing(directory) or sched['delete_pending']:
            return 30
        if fingerprint == sched.get('sent_fingerprint'):
            sched['dirty_at'] = None
        elif sched['dirty_at'] is None and sched['last_success'] is not None:
            sched['dirty_at'] = now
        start = sched['last_success'] is None
        debounce_due = sched['dirty_at'] is not None and now >= sched['dirty_at'] + DEBOUNCE_SECONDS
        heartbeat_due = (not start) and now >= sched['last_success'] + HEARTBEAT_SECONDS
        if not start and not debounce_due and not heartbeat_due:
            waits = []
            if sched['dirty_at'] is not None:
                waits.append(sched['dirty_at'] + DEBOUNCE_SECONDS - now)
            if sched['last_success'] is not None:
                waits.append(sched['last_success'] + HEARTBEAT_SECONDS - now)
            return max(0, min(waits)) if waits else 30
        if now < sched['not_before']:
            return sched['not_before'] - now
    if _send(directory, 'PUT', payload, token, paused):
        with LOCK:
            sched = _sched(directory)
            if _sharing(directory) and not sched['delete_pending']:
                sched['sent_fingerprint'] = fingerprint
                sched['dirty_at'] = None
                sched['last_success'] = now
                sched['backoff'] = BACKOFF_MIN
                sched['not_before'] = now
                return HEARTBEAT_SECONDS
        # Sharing was turned off while this request was in flight. Clear the copy next.
        return 0
    with LOCK:
        _fail(_sched(directory), now)
        return _sched(directory)['not_before'] - now


def _pause(stop, delay):
    deadline = time.monotonic() + max(delay, 0)
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if WAKE.wait(min(remaining, 1)):
            WAKE.clear()
            return False
    return True


def run(directory, stop, paused=lambda: False):
    while not stop.is_set():
        try:
            delay = tick(directory, paused=paused)
        except Exception:
            delay = BACKOFF_MIN
        if _pause(stop, delay):
            return
