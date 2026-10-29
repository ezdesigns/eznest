"""Exchange one OUTPUT pairing code for a scoped shop key.

POST the pair endpoint. The default host is https://output.jeezlabs.io.
EZ_NEST_OUTPUT_URL overrides shop.json outputUrl, which overrides that default.
The value must be an https origin with no path, query, user, or password.
Redirects are not followed. Sharing stays off until on-screen consent.

{"code":"7K4NP-QRX2M","requestId":"<uuid>","hostLabel":"<computer name>","hostRef":"<32 lowercase hex, optional>"}

hostLabel is this computer's name. On Windows that is the computer name.
hostRef is the installation id. It is sent only when that id is 32 lowercase
hex characters.

The first success returns result.token (an osa_ shop key; the protocol treats
it as valid for 90 days) exactly once. Persist it before any other work. A
later POST with the same requestId returns outcome "replay" and no token.
Create requestId once per attempt and reuse it only when the network attempt
itself fails.

Do not log the code, the shop key, or the response body. This module does
not change the eznest-observation/1 telemetry projection. Events stay off
until on-screen consent.
"""
import json
import os
import re
import sqlite3
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import output_credential
import shop_deploy
import telemetry
import telemetry_sender
from shop_deploy import host_name
from telemetry_sender import NoRedirect

ENDPOINT = shop_deploy.DEFAULT_OUTPUT_URL + '/api/shop/agent/pair'
_PAIR_DIRECTORY = None
CODE_BODY = re.compile(r'[A-Z0-9]{10}')
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
HOST_REF_RE = re.compile(r'[0-9a-f]{32}')
NETWORK_ATTEMPTS = 2

OFFLINE = 'OUTPUT could not be reached. Check this computer\'s internet connection and try again.'
DISABLED = "OUTPUT isn't turned on yet for this shop. Ask the admin."
INVALID_CODE = 'That pairing code is not valid. Ask the shop owner for a new code.'
EXPIRED = 'That pairing code has expired. Ask the shop owner for a new code.'
CONSUMED = 'That pairing code was already used. Ask the shop owner for a new code.'
RATE_LIMITED = 'OUTPUT is busy. Wait a moment and try this code again.'
LIMIT = 'This shop already has the maximum connected computers. Ask the shop owner to remove one in OUTPUT.'
REPLAY = 'OUTPUT already finished this pairing attempt, but this computer did not receive the credential. Ask the shop owner for a new code.'
UNEXPECTED = 'OUTPUT did not accept the pairing request.'
STORE_FAILED = 'OUTPUT accepted the code, but this computer could not store the credential. Ask the shop owner for a new code.'

MESSAGES = {
    'disabled': DISABLED,
    'invalid_code': INVALID_CODE,
    'expired': EXPIRED,
    'consumed': CONSUMED,
    'rate_limited': RATE_LIMITED,
    'limit': LIMIT,
    'replay': REPLAY,
    'offline': OFFLINE,
    'unexpected': UNEXPECTED,
}
STATUS_REASONS = {503: 'disabled', 404: 'invalid_code', 401: 'expired', 429: 'rate_limited'}


class PairingError(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def normalize_code(value):
    """Trim, uppercase, and accept the hyphen as optional. Wire form is 7K4NP-QRX2M."""
    if not isinstance(value, str):
        raise PairingError('invalid_code', INVALID_CODE)
    compact = ''.join(ch for ch in value.upper() if ch not in ' \t\r\n-')
    if not CODE_BODY.fullmatch(compact):
        raise PairingError('invalid_code', INVALID_CODE)
    return compact[:5] + '-' + compact[5:]


def clean_host_label(value):
    if not isinstance(value, str):
        return 'localhost'
    text = ''.join(ch for ch in value if ch.isprintable() and ch not in '\r\n\t').strip()
    return text[:80] or 'localhost'


def host_ref(directory):
    """Stable installation id. Omitted when it is not 32 lowercase hex."""
    try:
        with telemetry.database(directory) as db:
            value = db.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()[0]
    except (OSError, sqlite3.Error, TypeError, IndexError, ValueError):
        return None
    if isinstance(value, str) and HOST_REF_RE.fullmatch(value):
        return value
    return None


def _problem_code(payload):
    """OUTPUT errors are {"error":{"code":"invalid_code",...}}. Older bodies use a string."""
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


def classify(status, payload):
    code = _problem_code(payload)
    if code == 'api_route_not_found':
        return 'disabled'
    if code in MESSAGES and code not in ('offline', 'replay', 'unexpected'):
        return code
    if status == 409:
        return 'unexpected'
    return STATUS_REASONS.get(status, 'unexpected')


def interpret(status, body):
    if not isinstance(body, (bytes, bytearray)) or len(body) > 16384:
        raise PairingError('unexpected', UNEXPECTED)
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        reason = classify(status, None)
        raise PairingError(reason, MESSAGES.get(reason, UNEXPECTED))
    if status != 200:
        reason = classify(status, payload if isinstance(payload, dict) else None)
        raise PairingError(reason, MESSAGES.get(reason, UNEXPECTED))
    if not isinstance(payload, dict):
        raise PairingError('unexpected', UNEXPECTED)
    outcome = payload.get('outcome')
    result = payload.get('result') if isinstance(payload.get('result'), dict) else {}
    token = result.get('token')
    # A replay has no token. If a real token is present, keep it: it will not be sent again.
    if not output_credential.valid_token(token):
        if outcome == 'replay':
            raise PairingError('replay', REPLAY)
        raise PairingError('unexpected', UNEXPECTED)
    # Success carries result.outpostId, not a shop name. Do not present that id as a name.
    shop = result.get('shopName') if isinstance(result.get('shopName'), str) else None
    try:
        shop_name = output_credential.clean_shop_name(shop) if shop else None
    except ValueError:
        shop_name = None
    return {'credential': token, 'shopName': shop_name}


def pair_endpoint(directory=None):
    return shop_deploy.output_base_url(directory) + '/api/shop/agent/pair'


def _post(raw):
    request = Request(pair_endpoint(_PAIR_DIRECTORY), data=raw, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            return response.status, response.read(16385)
    except HTTPError as error:
        try:
            detail = error.read(16385)
        except Exception:
            detail = b''
        return error.code, detail
    except (OSError, URLError, TimeoutError):
        raise PairingError('offline', OFFLINE)


def _payload(code, request_id, host_label, host_reference):
    body = {'code': code, 'requestId': request_id, 'hostLabel': host_label}
    if host_reference:
        body['hostRef'] = host_reference
    return json.dumps(body, separators=(',', ':')).encode()


def exchange(code, *, host_label, host_ref=None, transport=None, attempts=NETWORK_ATTEMPTS):
    """One attempt. requestId is minted here and reused only for network retries."""
    normalized = normalize_code(code)
    label = clean_host_label(host_label)
    reference = host_ref if isinstance(host_ref, str) and HOST_REF_RE.fullmatch(host_ref) else None
    request_id = str(uuid.uuid4())
    if not UUID_RE.fullmatch(request_id):
        raise PairingError('unexpected', UNEXPECTED)
    raw = _payload(normalized, request_id, label, reference)
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise PairingError('unexpected', UNEXPECTED)
    for attempt in range(attempts):
        try:
            status, body = transport(raw) if transport else _post(raw)
        except PairingError as error:
            if error.reason == 'offline' and attempt + 1 < attempts:
                continue
            raise
        if not isinstance(status, int) or not isinstance(body, (bytes, bytearray)):
            raise PairingError('unexpected', UNEXPECTED)
        return interpret(status, body)
    raise PairingError('offline', OFFLINE)


def _blocked_by_environment():
    uploads = os.environ.get('EZ_NEST_OUTPUT_UPLOADS')
    if uploads == '0':
        raise PairingError('disabled', 'OUTPUT delivery is turned off for this run.')
    if uploads == '1':
        raise PairingError('rejected', 'This computer uses OUTPUT launch settings. A pairing code is not used while those settings are present.')


def connect(directory, code, *, paused=False, transport=None, host=None):
    if paused:
        raise PairingError('disabled', 'Sharing is paused during installation or recovery. Refresh after the host restarts.')
    _blocked_by_environment()
    # Validate before any network use so a mistyped code is not sent.
    normalize_code(code)
    reference = host_ref(directory)
    global _PAIR_DIRECTORY
    previous = _PAIR_DIRECTORY
    _PAIR_DIRECTORY = directory
    try:
        result = exchange(code, host_label=host if host is not None else host_name(), host_ref=reference, transport=transport)
    finally:
        _PAIR_DIRECTORY = previous
    # The token is returned once. Write it before status, consent, or another request.
    try:
        output_credential.save(directory, result['credential'], result['shopName'])
    except PairingError:
        raise
    except (OSError, ValueError):
        raise PairingError('unexpected', STORE_FAILED) from None
    return telemetry_sender.status(directory)


def disconnect(directory, *, paused=False):
    if paused:
        raise PairingError('disabled', 'Sharing is paused during installation or recovery. Refresh after the host restarts.')
    uploads = os.environ.get('EZ_NEST_OUTPUT_UPLOADS')
    if uploads == '1':
        raise PairingError('rejected', 'This computer uses OUTPUT launch settings. Remove those settings to disconnect.')
    if not output_credential.path(directory).is_file():
        raise PairingError('rejected', 'This computer is not connected with a pairing code.')
    telemetry_sender.revoke(directory)
    output_credential.clear(directory)
    return telemetry_sender.status(directory)
