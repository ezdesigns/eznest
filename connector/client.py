"""Write-only OUTPUT client.

Pairing and delivery are POST requests to the two paths already used by
output_pairing.py and telemetry_sender.py. Nothing is read back. A response
is checked for the ack and then discarded. Redirects are not followed.
"""
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

import output_credential
import output_pairing
import telemetry_sender
from shop_deploy import host_name

from connector.events import SCHEMA, validate_event

PAIR_PATH = urlparse(output_pairing.ENDPOINT).path
EVENT_PATH = urlparse(telemetry_sender.ENDPOINT).path
PINNED_HOST = 'output.jeezlabs.io'
DEFAULT_BASE = 'https://output.jeezlabs.io'
MAX_BODY = 12000
MAX_WAIT = 900


class ClientError(ValueError):
    pass


def normalize_output_base(value=None):
    """Https host only. The default is output.jeezlabs.io. Environment variables are ignored.

    `value` must come from the config file. None or blank keeps the pinned host.
    A path, user, query, or fragment is rejected. Redirects are not followed later.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_BASE
    if not isinstance(value, str):
        raise ClientError('OUTPUT host must be an https URL in the config file.')
    parsed = urlparse(value.strip())
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        raise ClientError('OUTPUT host must be https without a user name.')
    if parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ClientError('OUTPUT host must be a host only, not a path.')
    if not parsed.hostname:
        raise ClientError('OUTPUT host is missing a host name.')
    port = f':{parsed.port}' if parsed.port else ''
    return f'https://{parsed.hostname}{port}'


def url_for(role, output_host=None):
    if role == 'pair':
        path = PAIR_PATH
    elif role == 'event':
        path = EVENT_PATH
    else:
        raise ClientError('The connector has one write-only event endpoint.')
    base = normalize_output_base(output_host)
    url = base + path
    parsed = urlparse(url)
    pinned = urlparse(base)
    if parsed.scheme != 'https' or parsed.hostname != pinned.hostname or parsed.port != pinned.port:
        raise ClientError('Refusing a request outside the configured OUTPUT host.')
    if parsed.path not in (PAIR_PATH, EVENT_PATH):
        raise ClientError('Refusing a request outside the pairing and event paths.')
    return url


def post_json(body, token, *, role, transport=None, output_host=None):
    """POST one JSON body. There is no GET helper in this module."""
    url = url_for(role, output_host)
    raw = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, separators=(',', ':')).encode()
    if len(raw) > MAX_BODY:
        return 413, {}, b''
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if transport is not None:
        return transport(url, bytes(raw), headers)
    return _https_post(url, bytes(raw), headers)


def _https_post(url, raw, headers):
    # method is fixed. A 3xx is returned to the caller and not followed.
    request = Request(url, data=raw, headers=headers, method='POST')
    try:
        with build_opener(telemetry_sender.NoRedirect()).open(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read(16385)
    except HTTPError as error:
        try:
            detail = error.read(16385)
        except Exception:
            detail = b''
        return error.code, dict(error.headers or {}), detail
    except (OSError, URLError, TimeoutError):
        return None, {}, b''


def pairing_transport_for(output_host=None):
    def transport(raw):
        status, _headers, body = post_json(raw, None, role='pair', output_host=output_host)
        if status is None:
            raise output_pairing.PairingError('offline', output_pairing.OFFLINE)
        return status, body
    return transport


def pair(directory, code, *, transport=None, host_label=None, host_ref=None, output_host=None):
    output_pairing._blocked_by_environment()
    result = output_pairing.exchange(
        code,
        host_label=host_label if host_label is not None else host_name(),
        host_ref=host_ref,
        transport=transport or pairing_transport_for(output_host),
    )
    output_credential.save(directory, result['credential'], result['shopName'])
    return {'shopName': result['shopName']}


def disconnect(directory):
    if os.environ.get('EZ_NEST_OUTPUT_UPLOADS') == '1':
        raise output_pairing.PairingError(
            'rejected',
            'This computer uses OUTPUT launch settings. Remove those settings to disconnect.',
        )
    had = output_credential.path(directory).is_file()
    output_credential.clear(directory)
    return had


def token_for(directory):
    info = telemetry_sender.connection(str(directory))
    if info.get('source') == 'disabled':
        return None
    return info.get('token')


def deliver(event, token, *, transport=None, sleep=time.sleep, attempts=5, now=None, output_host=None):
    """POST one event. Retry network failures. Honor Retry-After on 429."""
    validate_event(event)
    delay = 1
    for _attempt in range(attempts):
        status, headers, body = post_json(event, token, role='event', transport=transport, output_host=output_host)
        if status == 200 and _accepted(body, event):
            return True
        if status == 429:
            wait = min(_retry_after(headers, now) or delay, MAX_WAIT)
            sleep(wait)
            delay = min(max(delay * 2, wait), MAX_WAIT)
            continue
        if status is None or (isinstance(status, int) and status >= 500):
            sleep(delay)
            delay = min(delay * 2, 60)
            continue
        return False
    return False


def send_many(events, token, **kwargs):
    """Send up to 20 events, one POST each. Stop the batch on the first failure."""
    sent = 0
    for event in list(events)[:20]:
        if deliver(event, token, **kwargs) is not True:
            break
        sent += 1
    return sent


def _accepted(body, event):
    """Ack check only. Extra fields, URLs, and records in the body are ignored."""
    if not isinstance(body, (bytes, bytearray)) or len(body) > 16384:
        return False
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get('outcome') not in ('created', 'replay'):
        return False
    receipt = payload.get('result')
    return (
        isinstance(receipt, dict)
        and receipt.get('schema') == SCHEMA
        and receipt.get('requestId') == event['requestId']
    )


def _retry_after(headers, now):
    if not headers:
        return None
    raw = None
    for key, value in headers.items():
        if str(key).lower() == 'retry-after':
            raw = value
    if raw is None:
        return None
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    base = now or datetime.now(timezone.utc)
    return max(0, (when - base).total_seconds())
