"""Set up your shop: connect this computer to OUTPUT from the browser.

1. start() makes a one-time pairing code on this computer. The code stays in
   this process. OUTPUT receives only sha256(code) and the computer name, and
   answers with a link id and a short match code.
2. The local page opens OUTPUT's approve page with the link id. The signed-in
   shop owner checks the match code and approves.
3. check() asks OUTPUT about this request (link id plus code hash). Once it is
   approved, the code is redeemed through output_pairing.connect, which stores
   the shop key with the existing protected storage.

Never log the code, its hash, the shop key, or a response body.
"""
import hashlib
import json
import secrets
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import output_pairing
import output_remote
import shop_deploy
from shop_deploy import host_name
from telemetry_sender import NoRedirect

ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
LIFETIME_SECONDS = 10 * 60
USER_CODE_CHARS = set(ALPHABET + '-')

START_FAILED = 'Shop setup could not start. Check the internet connection and try again.'
EXPIRED = 'This setup request timed out. Click Connect to try again.'
DENIED = 'The request was turned down in OUTPUT. Click Connect to try again.'
NOT_STARTED = 'Click Connect first.'

_LOCK = threading.Lock()
_PENDING = {}


class LinkError(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def new_code():
    return ''.join(secrets.choice(ALPHABET) for _ in range(10))


def code_hash(compact):
    return hashlib.sha256(compact.encode('utf-8')).hexdigest()


def link_endpoint(directory=None):
    return shop_deploy.output_base_url(directory) + '/api/shop/agent/link'


def approve_url(directory, link_id):
    return shop_deploy.output_base_url(directory) + '/outpost/ez-nest/approve?link=' + link_id


def _post(directory, payload):
    url = link_endpoint(directory)
    if not shop_deploy.allowed_output_request(url):
        raise LinkError('offline', START_FAILED)
    raw = json.dumps(payload, separators=(',', ':')).encode()
    request = Request(url, data=raw, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            return response.status, response.read(16385)
    except HTTPError as error:
        try:
            return error.code, error.read(16385)
        except Exception:
            return error.code, b''
    except (OSError, URLError, TimeoutError):
        raise LinkError('offline', output_pairing.OFFLINE)


def _result(status, body):
    try:
        payload = json.loads(body) if isinstance(body, (bytes, bytearray)) and len(body) <= 16384 else None
    except (ValueError, TypeError):
        payload = None
    if status == 503:
        raise LinkError('disabled', output_pairing.DISABLED)
    if status == 429 or output_pairing._problem_code(payload) == 'rate_limited':
        raise LinkError('rate_limited', 'Too many tries from this computer. Wait a few minutes and try again.')
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get('result'), dict):
        raise LinkError('unexpected', START_FAILED)
    return payload['result']


def _valid_user_code(value):
    return isinstance(value, str) and len(value) == 9 and value[4] == '-' and set(value) <= USER_CODE_CHARS


def start(directory, *, paused=False, transport=None, host=None, now=time.time):
    if not output_remote.READY:
        raise LinkError('disabled', 'Browser approval is not available yet.')
    if paused:
        raise LinkError('disabled', 'Sharing is paused during installation or recovery. Refresh after the host restarts.')
    try:
        output_pairing._blocked_by_environment()
    except output_pairing.PairingError as error:
        raise LinkError(error.reason, str(error)) from None
    compact = new_code()
    digest = code_hash(compact)
    payload = {'op': 'start', 'requestId': str(uuid.uuid4()), 'codeHash': digest,
               'hostLabel': output_pairing.clean_host_label(host if host is not None else host_name())}
    status, body = (transport or (lambda p: _post(directory, p)))(payload)
    result = _result(status, body)
    link_id = result.get('linkId')
    user_code = result.get('userCode')
    if not isinstance(link_id, str) or not output_pairing.UUID_RE.fullmatch(link_id) or not _valid_user_code(user_code):
        raise LinkError('unexpected', START_FAILED)
    with _LOCK:
        _PENDING.clear()
        _PENDING[str(directory)] = {'linkId': link_id, 'code': compact, 'hash': digest,
                                    'userCode': user_code, 'expires': now() + LIFETIME_SECONDS}
    return {'userCode': user_code, 'approveUrl': approve_url(directory, link_id), 'expiresIn': LIFETIME_SECONDS}


def cancel(directory):
    with _LOCK:
        _PENDING.pop(str(directory), None)
    return {'state': 'cancelled'}


def check(directory, *, paused=False, transport=None, pair_transport=None, now=time.time):
    """One status check. Returns state pending, connected, expired, or denied."""
    with _LOCK:
        item = dict(_PENDING.get(str(directory)) or {})
    if not item:
        raise LinkError('not_started', NOT_STARTED)
    if now() >= item['expires']:
        cancel(directory)
        return {'state': 'expired', 'message': EXPIRED}
    if not output_remote.READY:
        raise LinkError('disabled', 'Browser approval is not available yet.')
    payload = {'op': 'status', 'linkId': item['linkId'], 'codeHash': item['hash']}
    status, body = (transport or (lambda p: _post(directory, p)))(payload)
    if status == 404:
        cancel(directory)
        return {'state': 'expired', 'message': EXPIRED}
    state = _result(status, body).get('state')
    if state == 'pending':
        return {'state': 'pending', 'userCode': item['userCode']}
    if state in ('expired', 'denied'):
        cancel(directory)
        return {'state': state, 'message': EXPIRED if state == 'expired' else DENIED}
    if state != 'approved':
        raise LinkError('unexpected', START_FAILED)
    # Approved: redeem this computer's own code through the existing pairing path.
    cancel(directory)
    try:
        result = output_pairing.connect(directory, item['code'], paused=paused, transport=pair_transport)
    except output_pairing.PairingError as error:
        raise LinkError(error.reason, str(error)) from None
    return {'state': 'connected', 'status': result}
