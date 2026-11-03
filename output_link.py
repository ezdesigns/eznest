"""Owner-approved OUTPUT connection. The redemption code stays in host memory.

Uses OUTPUT's /api/shop/agent/link contract. No browser callback listener,
credential in a URL, persistent pending secret, or automatic sharing consent.
"""
import hashlib
import json
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import output_pairing
import output_gate
import shop_deploy
from telemetry_sender import NoRedirect

ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
MATCH = re.compile(r'[' + ALPHABET + r']{4}-[' + ALPHABET + r']{4}')
LOCK = threading.RLock()
ATTEMPTS = {}
TTL = 600
INTERVAL = 3


def _key(directory):
    return str(Path(directory).resolve())


def _allowed(paused):
    if paused:
        raise output_pairing.PairingError('disabled', 'Connection setup is paused. Refresh after Ez Nest restarts.')
    output_pairing._blocked_by_environment()


def _post(directory, raw):
    url = shop_deploy.output_base_url(directory) + '/api/shop/agent/link'
    if not shop_deploy.allowed_output_request(url):
        raise output_pairing.PairingError('offline', output_pairing.OFFLINE)
    request = Request(url, data=raw, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            return response.status, response.read(16385)
    except HTTPError as error:
        try:
            return error.code, error.read(16385)
        except (OSError, TimeoutError):
            raise output_pairing.PairingError('offline', output_pairing.OFFLINE) from None
    except (OSError, URLError, TimeoutError):
        raise output_pairing.PairingError('offline', output_pairing.OFFLINE) from None


def _request(directory, body, transport):
    raw = json.dumps(body, separators=(',', ':')).encode()
    status, payload = transport(raw) if transport else _post(directory, raw)
    if status in (404, 405, 503):
        raise output_pairing.PairingError('unavailable', 'Browser connection is not available on OUTPUT yet. You can use a pairing code instead.')
    if status == 429:
        raise output_pairing.PairingError('rate_limited', 'Too many connection attempts. Wait a few minutes before trying again.')
    if status != 200 or not isinstance(payload, (bytes, bytearray)) or len(payload) > 16384:
        raise output_pairing.PairingError('unexpected', 'OUTPUT could not confirm this connection request. Start again.')
    try:
        result = json.loads(payload)['result']
        if not isinstance(result, dict):
            raise ValueError()
        if not output_pairing.UUID_RE.fullmatch(result.get('linkId', '')) or uuid.UUID(result['linkId']).int == 0:
            raise ValueError()
        if not MATCH.fullmatch(result.get('userCode', '')):
            raise ValueError()
        if result.get('state') not in ('pending', 'approved', 'denied', 'expired', 'connected'):
            raise ValueError()
        expiry = datetime.fromisoformat(result['expiresAt'].replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise output_pairing.PairingError('unexpected', 'OUTPUT returned an incomplete connection request. Start again.') from None
    return result, max(0, min(TTL, (expiry - datetime.now(timezone.utc)).total_seconds()))


def _public(attempt):
    return {key: attempt[key] for key in ('attemptId', 'state', 'userCode', 'approvalUrl') if key in attempt} | {
        'expiresIn': max(0, int(attempt['deadline'] - time.monotonic())), 'pollAfter': INTERVAL}


def start(directory, *, paused=False, transport=None, host=None):
    _allowed(paused)
    with LOCK:
        key = _key(directory)
        now = time.monotonic()
        for old in list(ATTEMPTS):
            if ATTEMPTS[old]['deadline'] <= now:
                ATTEMPTS.pop(old)
        attempt = ATTEMPTS.get(key)
        if attempt and attempt['state'] in ('pending', 'connecting') and 'linkId' in attempt:
            return _public(attempt)
        if not attempt or attempt['state'] != 'starting':
            code = ''.join(secrets.choice(ALPHABET) for _ in range(10))
            attempt = {'attemptId': str(uuid.uuid4()), 'code': code,
                       'codeHash': hashlib.sha256(code.encode()).hexdigest(),
                       'deadline': now + TTL, 'state': 'starting', 'nextPoll': 0}
            ATTEMPTS[key] = attempt
        body = {'op': 'start', 'requestId': attempt['attemptId'], 'codeHash': attempt['codeHash'],
                'hostLabel': output_pairing.clean_host_label(host if host is not None else shop_deploy.host_name())}
        result, remaining = _request(directory, body, transport)
        if result['state'] != 'pending' or not remaining:
            ATTEMPTS.pop(key, None)
            raise output_pairing.PairingError('expired', 'This connection request ended. Start again.')
        attempt.update(linkId=result['linkId'], userCode=result['userCode'], state='pending',
                       deadline=min(attempt['deadline'], time.monotonic() + remaining),
                       approvalUrl=shop_deploy.output_base_url(directory) + '/outpost/ez-nest/approve?link=' + result['linkId'])
        return _public(attempt)


def status(directory, attempt_id, *, paused=False, transport=None, pair_transport=None, check_in_transport=None):
    _allowed(paused)
    with LOCK:
        attempt = ATTEMPTS.get(_key(directory))
        if not attempt or attempt['attemptId'] != attempt_id:
            return {'state': 'expired'}
        if attempt['state'] in ('connected', 'denied', 'expired', 'failed'):
            return _public(attempt)
        if attempt['deadline'] <= time.monotonic():
            attempt.update(state='expired', code=None)
            return _public(attempt)
        if 'linkId' not in attempt:
            raise output_pairing.PairingError('unexpected', 'Start the connection request again.')
        if attempt['nextPoll'] > time.monotonic():
            return _public(attempt)
        attempt['nextPoll'] = time.monotonic() + INTERVAL
        result, remaining = _request(directory, {'op': 'status', 'linkId': attempt['linkId'], 'codeHash': attempt['codeHash']}, transport)
        if result['linkId'] != attempt['linkId'] or result['userCode'] != attempt['userCode']:
            raise output_pairing.PairingError('unexpected', 'OUTPUT returned a different request. Cancel and start again.')
        if result['state'] in ('expired', 'denied') or not remaining:
            attempt.update(state='denied' if result['state'] == 'denied' else 'expired', code=None)
        elif attempt['state'] == 'connecting':
            if result['state'] == 'connected':
                attempt['state'] = 'connected'
            else:
                output_gate.check_in(directory, transport=check_in_transport)
        elif result['state'] == 'approved':
            # Consume once. A lost response may have spent the code; never keep
            # redeeming automatically or claim that an approval is a connection.
            code = attempt.pop('code', None)
            attempt['state'] = 'failed'
            output_pairing.connect(directory, code, paused=paused, transport=pair_transport, check_in_transport=check_in_transport)
            # OUTPUT confirms a successful check-in on the next status read.
            attempt['state'] = 'connecting'
        elif result['state'] == 'connected':
            raise output_pairing.PairingError('unexpected', 'This request was completed elsewhere. Check the connection in Settings.')
        return _public(attempt)


def cancel(directory, attempt_id):
    with LOCK:
        key = _key(directory)
        if ATTEMPTS.get(key, {}).get('attemptId') == attempt_id:
            ATTEMPTS.pop(key)
    return {'state': 'cancelled'}
