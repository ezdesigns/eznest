"""Opt-in, future-only OUTPUT sender.

A paired credential may be stored by output_credential. Launch environment
settings still win: EZ_NEST_OUTPUT_UPLOADS=1 uses EZ_NEST_OUTPUT_TOKEN, and
EZ_NEST_OUTPUT_UPLOADS=0 disables delivery (including --shop-test). Neither
path sends anything without the on-screen consent. The credential is not
written to the telemetry database, logs, or API responses.
"""
import hashlib
import json
import os
import re
import threading
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler
import output_credential
import telemetry
from telemetry_output import SCHEMA, BANDS, project

ENDPOINT = 'https://output.jeezlabs.io/api/shop/telemetry'
CONSENT_VERSION = 'eznest-output-consent/1'
LOCK = threading.RLock()
CONTROL_LOCK = threading.Lock()
REVOKING = set()
KEY = 'output_consent'
ERROR = 'OUTPUT did not confirm receipt. Nothing was acknowledged; delivery will retry.'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _env_token():
    token = os.environ.get('EZ_NEST_OUTPUT_TOKEN', '')
    if isinstance(token, str) and re.fullmatch(r'osa_[A-Za-z0-9_-]{43}', token):
        return token
    return None


def connection(directory):
    """Credential used for delivery. Environment settings take precedence."""
    uploads = os.environ.get('EZ_NEST_OUTPUT_UPLOADS')
    if uploads == '0':
        return {'token': None, 'source': 'disabled', 'shopName': None}
    if uploads == '1':
        token = _env_token()
        return {'token': token, 'source': 'environment' if token else 'environment-invalid', 'shopName': None}
    saved = output_credential.describe(directory)
    if saved['credential']:
        return {'token': saved['credential'], 'source': 'paired', 'shopName': saved['shopName']}
    return {'token': None, 'source': None, 'shopName': None}


def configuration(directory):
    return connection(directory)['token']


def fingerprint(token):
    return hashlib.sha256((ENDPOINT + '\0' + token).encode()).hexdigest()


def read(db):
    db.execute('CREATE TABLE IF NOT EXISTS output_rejections (event_id TEXT PRIMARY KEY, contract TEXT NOT NULL, rejected_at TEXT NOT NULL)')
    row = db.execute('SELECT value FROM metadata WHERE key=?', (KEY,)).fetchone()
    return json.loads(row[0]) if row else {'enabled': False, 'revision': 0, 'cutoff': 0}


def write(db, value):
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (KEY, json.dumps(value)))


def effective(consent, token):
    return bool(token and consent.get('enabled') is True
                and consent.get('version') == CONSENT_VERSION
                and consent.get('credential') == fingerprint(token))


def read_active(db, token):
    current = read(db)
    if current.get('enabled') is True and not effective(current, token):
        # A detected mismatch permanently ends this consent. Restoring an old
        # token, gate or version must not resurrect permission or its backlog.
        current.update(enabled=False, revision=current['revision']+1,
                       lastError='Delivery settings changed. Review sharing and consent again.')
        write(db, current)
    return current


def status(directory, *, paused=lambda: False):
    with LOCK, telemetry.database(directory) as db:
        info = connection(directory)
        token = info['token']
        suspended = paused()
        # A candidate service may be rolled back with its data snapshot. Do not
        # change consent while installation has closed operation admission.
        consent = read(db) if suspended else read_active(db, token)
        enabled = effective(consent, token)
        instance = db.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()[0]
        pending = db.execute('SELECT count(*) FROM events WHERE seq>? AND acknowledged=0 AND id NOT IN (SELECT event_id FROM output_rejections)', (consent['cutoff'],)).fetchone()[0] if enabled else 0
        return {'configured': token is not None, 'configurationId': fingerprint(token) if token else None, 'enabled': enabled, 'paused': suspended,
                'requiresConsent': bool(token and not enabled),
                'connection': info['source'], 'shopName': info['shopName'],
                'revision': consent['revision'], 'consentVersion': CONSENT_VERSION,
                'endpoint': ENDPOINT, 'schema': SCHEMA, 'instanceId': instance, 'appVersion': telemetry.VERSION,
                'eventTypes': list(telemetry.KINDS), 'bands': BANDS,
                'pendingEvents': pending, 'withheldEvents': db.execute('SELECT count(*) FROM output_rejections').fetchone()[0], 'consentedAt': consent.get('at'),
                'lastDeliveredAt': consent.get('lastDeliveredAt'), 'lastError': consent.get('lastError')}


def consent(directory, *, revision, version, configurationId, confirmed):
    if confirmed is not True or version != CONSENT_VERSION or type(revision) is not int:
        raise ValueError('Review the current sharing disclosure and explicitly agree.')
    with LOCK, telemetry.database(directory) as db:
        old = read(db)
        token = configuration(directory)
        if token is None:
            raise ValueError('OUTPUT delivery is not configured on this host.')
        if configurationId != fingerprint(token):
            raise ValueError('The shop credential changed. Review sharing again.')
        if old['revision'] != revision:
            raise ValueError('Sharing settings changed. Review them again.')
        # Database ordering avoids wall-clock races and excludes every old event,
        # including previously consented-but-unsent data after disabling/re-enabling.
        cutoff = db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]
        write(db, {'enabled': True, 'revision': revision+1, 'version': version,
                   'credential': fingerprint(token), 'cutoff': cutoff, 'at': telemetry.now()})
        with CONTROL_LOCK:
            REVOKING.discard(str(Path(directory).resolve()))
    return status(directory)


def revoke(directory):
    # Wait for an already-started bounded request; after this returns no new
    # request can start until a new explicit consent. Do not claim remote deletion.
    with CONTROL_LOCK:
        REVOKING.add(str(Path(directory).resolve()))
    with LOCK, telemetry.database(directory) as db:
        old = read(db)
        old.update(enabled=False, revision=old['revision']+1)
        write(db, old)
    return status(directory)


def _emit_https(payload, token):
    raw = json.dumps(payload, separators=(',', ':')).encode()
    if len(raw) > 12000:
        return False
    request = Request(ENDPOINT, data=raw, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
        'Accept': 'application/json'}, method='POST')
    # Never forward shop credentials to a redirect target. HTTPS validates the
    # platform trust store; no bypass, arbitrary destination or fallback exists.
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            body = response.read(16385)
            if response.status != 200 or len(body) > 16384:
                return False
            result = json.loads(body)
    except (OSError, URLError, HTTPError, ValueError):
        return False
    if not isinstance(result, dict) or result.get('outcome') not in ('created', 'replay'):
        return False
    receipt = result.get('result')
    return (isinstance(receipt, dict) and receipt.get('schema') == SCHEMA
            and receipt.get('requestId') == payload['requestId'])


def worker_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--telemetry-worker']
    return [sys.executable, str(Path(__file__).resolve()), '--telemetry-worker']


def emit(payload, token):
    # A socket timeout only bounds inactivity, not slow headers/body or DNS.
    # An isolated child gives the entire operation a deadline. subprocess.run
    # kills and waits for that child on timeout, before releasing the consent
    # lock; no abandoned request can later resume after revocation.
    env = {key: os.environ[key] for key in
           ('PATH', 'HOME', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR') if key in os.environ}
    try:
        result = subprocess.run(worker_command(), input=json.dumps({'payload':payload, 'token':token}).encode(),
                                capture_output=True, timeout=10, env=env)
        return result.returncode == 0 and result.stdout.strip() == b'true'
    except (OSError, subprocess.TimeoutExpired):
        return False


def worker():
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError('Request too large')
        request = json.loads(raw)
        if set(request) != {'payload', 'token'} or not isinstance(request['token'],str) or not re.fullmatch(r'osa_[A-Za-z0-9_-]{43}',request['token']):
            raise ValueError('Invalid request')
        accepted = _emit_https(request['payload'], request['token'])
    except Exception:
        accepted = False
    print('true' if accepted else 'false')


def tick(directory, stop=None, *, limit=10, paused=lambda: False):
    """Bounded at-least-once delivery. The receiver deduplicates stable UUIDs."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Choose a delivery batch from 1 to 100.')
    count = 0
    for _ in range(limit):
        with LOCK:
            with CONTROL_LOCK:
                if str(Path(directory).resolve()) in REVOKING:
                    break
            if stop is not None and stop.is_set():
                break
            if paused():
                break
            token = configuration(directory)
            with telemetry.database(directory) as db:
                current = read_active(db, token)
                if not effective(current, token):
                    break
                row = db.execute('SELECT id,atom FROM events WHERE seq>? AND acknowledged=0 AND id NOT IN (SELECT event_id FROM output_rejections) ORDER BY seq LIMIT 1', (current['cutoff'],)).fetchone()
            if row is None:
                break
            try:
                payload = project(json.loads(row['atom']))
            except (ValueError, TypeError, KeyError):
                # Preserve malformed local records unacknowledged, but do not
                # let one unsafe record block every later valid observation.
                with telemetry.database(directory) as db:
                    db.execute('INSERT OR IGNORE INTO output_rejections VALUES(?,?,?)',
                               (row['id'], CONSENT_VERSION, telemetry.now()))
                continue
            if paused():
                break
            sent = emit(payload, token) is True
            with telemetry.database(directory) as db:
                # No SQLite transaction is held over network IO. The sender lock
                # serializes consent/revocation with this exact acknowledgment.
                current = read(db)
                if sent:
                    db.execute('UPDATE events SET acknowledged=1 WHERE id=?', (row['id'],))
                    current.update(lastDeliveredAt=telemetry.now(), lastError=None)
                else:
                    current['lastError'] = ERROR
                write(db, current)
            if not sent:
                break
            count += 1
    return count


def run(directory, stop, paused=lambda: False):
    try:
        status(directory, paused=paused)  # Invalidate only after update admission opens.
    except Exception:
        pass
    delay = 5
    while not stop.wait(delay):
        try:
            tick(directory, stop, paused=paused)
            info = status(directory, paused=paused)
            delay = min(max(delay*2, 30), 900) if info['lastError'] else 30
        except Exception:
            # Local disk/database trouble must neither disclose private error
            # contents nor interrupt nesting. Retry with a bounded backoff.
            delay = min(max(delay*2, 30), 900)


if __name__ == '__main__':
    if sys.argv[1:] != ['--telemetry-worker']:
        raise SystemExit('Internal telemetry transport worker only.')
    worker()
