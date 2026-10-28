"""Exchange one OUTPUT pairing code for a shop credential.

Assumed contract, used because ezdesigns/output was not readable from this
workspace on 2026-10-28 (the repository returned 404) and
https://output.jeezlabs.io/api/shop/agent/pair was not published yet.
Adjust this module when docs/ez-nest-pairing.md lands. Do not log the code,
the credential, or the response body.

POST https://output.jeezlabs.io/api/shop/agent/pair
{"code": "<pairing code>", "hostName": "<this computer>", "version": "<ez nest version>"}

200 {"credential": "osa_<43>", "shopName": "<shop>"}

Errors are fixed sentences. A redirect is not followed.
"""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import output_credential
import telemetry_sender
from app_info import VERSION
from shop_deploy import host_name
from telemetry_sender import NoRedirect

ENDPOINT = 'https://output.jeezlabs.io/api/shop/agent/pair'
CODE_RE = re.compile(r'[A-Za-z0-9_-]{4,64}')
OFFLINE = 'OUTPUT could not be reached. Check this computer\'s internet connection and try again.'
DISABLED = 'OUTPUT pairing is turned off on the server.'
REJECTED = 'That pairing code is not valid or has expired. Ask the shop owner for a new code.'
UNAVAILABLE = 'OUTPUT could not complete pairing. Try again in a few minutes.'
UNEXPECTED = 'OUTPUT did not accept the pairing request.'
STORE_FAILED = 'OUTPUT accepted the code, but this computer could not store the credential. Ask the shop owner for a new code.'


class PairingError(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def clean_code(value):
    if not isinstance(value, str) or not CODE_RE.fullmatch(value.strip()):
        raise PairingError('rejected', REJECTED)
    return value.strip()


def clean_host(value):
    if not isinstance(value, str):
        return 'localhost'
    text = ''.join(ch for ch in value if ch.isprintable() and ch not in '\r\n\t').strip()
    return text[:253] or 'localhost'


def clean_version(value):
    text = str(value or '').strip()
    if not re.fullmatch(r'[0-9A-Za-z._+-]{1,40}', text):
        raise PairingError('unexpected', UNEXPECTED)
    return text


def _problem_code(payload):
    if not isinstance(payload, dict):
        return ''
    raw = payload.get('code')
    if not isinstance(raw, str):
        raw = payload.get('error') if isinstance(payload.get('error'), str) else ''
    return raw.strip().lower()


def classify(status, payload):
    code = _problem_code(payload)
    if code == 'api_route_not_found' or any(part in code for part in ('disabled', 'not_enabled', 'notenabled', 'feature_off')):
        return 'disabled'
    if status == 404 and not code:
        return 'disabled'
    if status in (400, 401, 403, 404, 409, 410, 422):
        return 'rejected'
    if status >= 500 or status in (408, 429):
        return 'unavailable'
    return 'unexpected'


def _message(reason):
    return {'offline': OFFLINE, 'disabled': DISABLED, 'rejected': REJECTED, 'unavailable': UNAVAILABLE}.get(reason, UNEXPECTED)


def interpret(status, body):
    if len(body) > 16384:
        raise PairingError('unexpected', UNEXPECTED)
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        raise PairingError(classify(status, None), _message(classify(status, None)))
    if status != 200:
        reason = classify(status, payload)
        raise PairingError(reason, _message(reason))
    record = payload.get('result') if isinstance(payload, dict) and isinstance(payload.get('result'), dict) and 'credential' not in payload else payload
    if not isinstance(record, dict):
        raise PairingError('unexpected', UNEXPECTED)
    credential = record.get('credential')
    shop = record.get('shopName', record.get('shop_name'))
    try:
        if not output_credential.valid_token(credential):
            raise ValueError('credential')
        shop_name = output_credential.clean_shop_name(shop)
    except ValueError:
        raise PairingError('unexpected', UNEXPECTED)
    return {'credential': credential, 'shopName': shop_name}


def _post(raw):
    request = Request(ENDPOINT, data=raw, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
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


def exchange(code, host, version, *, transport=None):
    payload = {'code': clean_code(code), 'hostName': clean_host(host), 'version': clean_version(version)}
    raw = json.dumps(payload, separators=(',', ':')).encode()
    status, body = transport(raw) if transport else _post(raw)
    if not isinstance(status, int) or not isinstance(body, (bytes, bytearray)):
        raise PairingError('unexpected', UNEXPECTED)
    return interpret(status, body)


def _blocked_by_environment():
    uploads = os.environ.get('EZ_NEST_OUTPUT_UPLOADS')
    if uploads == '0':
        raise PairingError('disabled', 'OUTPUT delivery is turned off for this run.')
    if uploads == '1':
        raise PairingError('rejected', 'This computer uses OUTPUT launch settings. A pairing code is not used while those settings are present.')


def connect(directory, code, *, paused=False, transport=None, host=None, version=None):
    if paused:
        raise PairingError('disabled', 'Sharing is paused during installation or recovery. Refresh after the host restarts.')
    _blocked_by_environment()
    # Validate before any network use so a mistyped code is not sent.
    clean_code(code)
    result = exchange(code, host if host is not None else host_name(), version or VERSION, transport=transport)
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
