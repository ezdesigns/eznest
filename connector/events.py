"""shop-connector-event/1 envelopes, bands, and the privacy allow-list.

Numeric bands follow docs/telemetry-contract.md: a string "[lower,upper)",
or "0" when the measurement is exactly zero. Unknown stays null.
"""
import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation, ROUND_FLOOR

SCHEMA = 'shop-connector-event/1'
VERSION = '0.1.0'
SOURCES = ('eznest', 'printer', 'cutter', 'inventory')
KINDS = ('nest.completed', 'print.completed', 'cut.completed', 'inventory.observed')
MATERIALS = ('moto_regular', 'moto_holographic', 'moto_chrome', 'custom', 'unknown')
UNITS = ('mm', 'm', 'ml', 'sheets', 'rolls', 'each')
INK_CHANNELS = ('c', 'm', 'y', 'k', 'lc', 'lm', 'lk', 'llk', 'or', 'gr', 'w')
PRINTER_CLASSES = ('epson_s80600', 'roland_vs540', 'hp_latex_570', 'epson_7890', 'unknown')

ENVELOPE = (
    'schema', 'eventId', 'requestId', 'source', 'instanceId',
    'occurredAt', 'connectorVersion', 'kind', 'payload',
)
PRINT_KEYS = (
    'status', 'printerClass', 'mediaClass', 'copiesBand', 'inkTotalMlBand',
    'inkChannelsMlBand', 'coveragePercentBand', 'printTimeSecondsBand',
    'widthMmBand', 'lengthMmBand', 'jobId', 'onyxStatus', 'machineModel',
    'mediaUsedFt', 'widthIn', 'axisSwapped',
)
CUT_KEYS = (
    'materialClass', 'thicknessMmBand', 'jobCountBand', 'copiesBand',
    'jobSizeXMmBand', 'jobSizeYMmBand', 'copySizeXMmBand', 'copySizeYMmBand',
    'durationSecondsBand', 'jobId',
)
INVENTORY_KEYS = (
    'materialClass', 'materialKey', 'quantityBand', 'unit',
    'reorderThresholdBand', 'source',
)

_BAND = re.compile(r'^(?:0|\[[0-9]+(?:\.[0-9]+)?,[0-9]+(?:\.[0-9]+)?\))$')
_MEASURE = re.compile(r'^[0-9]+(?:\.[0-9]{1,2})?$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_INSTANCE = re.compile(r'^[0-9a-f]{32}$')
_UUID5 = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
_TIME = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')
_VERSION = re.compile(r'^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}$')
_CLASS = re.compile(r'^[a-z][a-z0-9_]{0,40}$')
_EMAIL = re.compile(r'[^@\s]+@[^@\s]+')
_IPV4 = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_IDENTITY_KEYS = {
    'filename', 'file', 'filepath', 'path', 'title', 'job', 'jobname', 'job_name',
    'customer', 'customername', 'phone', 'email', 'address', 'price', 'cost',
    'order', 'orderid', 'order_id', 'ip', 'ipaddress', 'raw', 'line', 'quickset',
    'quick_set', 'name',
}


class ContractError(ValueError):
    """Raised when an event would leave the allow-list. The message stays generic."""


def band(value, step):
    """Round a measurement into a half-open band. None when it is not usable."""
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
        width = Decimal(str(step))
    except (InvalidOperation, ValueError):
        return None
    if width <= 0 or number < 0 or number > Decimal('1e12'):
        return None
    if number == 0:
        return '0'
    lo = (number / width).to_integral_value(rounding=ROUND_FLOOR) * width
    return f'[{_decimal(lo)},{_decimal(lo + width)})'


def percent_band(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if number < 0 or number > 100:
        return None
    return band(number, 5)


def _decimal(value):
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text or '0'


def event_id_for(plugin, line):
    """Stable id from the plug-in name and the exact source line (no newline)."""
    if isinstance(line, str):
        line = line.encode('utf-8')
    raw = plugin.encode('utf-8') + b'\n' + bytes(line).rstrip(b'\r\n')
    return hashlib.sha256(raw).hexdigest()


def request_id_for(instance_id, event_id):
    """UUIDv5 so a retry of the same event is the same POST, matching OUTPUT."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'shop-connector:{instance_id}:{event_id}'))


def salted_hash(salt, kind, text):
    """Hash a local label. The salt stays on this computer."""
    if not isinstance(salt, (bytes, bytearray)) or not salt:
        raise ContractError('withheld')
    if not isinstance(text, str) or not text.strip():
        return None
    normalized = ' '.join(text.split()).casefold().encode('utf-8')
    return hashlib.sha256(bytes(salt) + b'\0' + kind.encode('utf-8') + b'\0' + normalized).hexdigest()


def build_event(instance_id, plugin, line, source, kind, occurred_at, payload):
    event_id = event_id_for(plugin, line)
    event = {
        'schema': SCHEMA,
        'eventId': event_id,
        'requestId': request_id_for(instance_id, event_id),
        'source': source,
        'instanceId': instance_id,
        'occurredAt': occurred_at,
        'connectorVersion': VERSION,
        'kind': kind,
        'payload': payload,
    }
    validate_event(event)
    return event


def validate_event(event):
    if not isinstance(event, dict) or tuple(event) != ENVELOPE:
        raise ContractError('withheld')
    if event['schema'] != SCHEMA or event['connectorVersion'] != VERSION:
        raise ContractError('withheld')
    if event['kind'] not in KINDS or event['source'] not in SOURCES:
        raise ContractError('withheld')
    for field, pattern in (
        ('eventId', _HASH), ('requestId', _UUID5), ('instanceId', _INSTANCE), ('occurredAt', _TIME),
    ):
        if not isinstance(event[field], str) or not pattern.fullmatch(event[field]):
            raise ContractError('withheld')
    if not _VERSION.fullmatch(event['connectorVersion']):
        raise ContractError('withheld')
    payload = event['payload']
    if event['kind'] == 'nest.completed':
        if event['source'] != 'eznest':
            raise ContractError('withheld')
        _validate_nest(payload)
    elif event['kind'] == 'print.completed':
        if event['source'] != 'printer':
            raise ContractError('withheld')
        _validate_print(payload)
    elif event['kind'] == 'cut.completed':
        if event['source'] != 'cutter':
            raise ContractError('withheld')
        _validate_cut(payload)
    else:
        if event['source'] != 'inventory':
            raise ContractError('withheld')
        _validate_inventory(payload)
    _reject_identity(event)
    return event


def _band_or_null(value):
    if value is None:
        return
    if not isinstance(value, str) or not _BAND.fullmatch(value):
        raise ContractError('withheld')


def _hash_or_null(value):
    if value is None:
        return
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ContractError('withheld')


def _validate_print(payload):
    if not isinstance(payload, dict) or tuple(payload) != PRINT_KEYS:
        raise ContractError('withheld')
    if payload['status'] not in ('ok', 'abnormal'):
        raise ContractError('withheld')
    if payload['printerClass'] not in PRINTER_CLASSES:
        raise ContractError('withheld')
    if payload['mediaClass'] not in MATERIALS:
        raise ContractError('withheld')
    for key in (
        'copiesBand', 'inkTotalMlBand', 'coveragePercentBand', 'printTimeSecondsBand',
        'widthMmBand', 'lengthMmBand',
    ):
        _band_or_null(payload[key])
    _hash_or_null(payload['jobId'])
    if payload['onyxStatus'] not in ('1', '-1', '0'):
        raise ContractError('withheld')
    if payload['machineModel'] not in PRINTER_CLASSES or payload['printerClass'] != payload['machineModel']:
        raise ContractError('withheld')
    for key in ('mediaUsedFt', 'widthIn'):
        if not isinstance(payload[key], str) or not _MEASURE.fullmatch(payload[key]):
            raise ContractError('withheld')
    if type(payload['axisSwapped']) is not bool:
        raise ContractError('withheld')
    channels = payload['inkChannelsMlBand']
    if not isinstance(channels, dict) or any(name not in INK_CHANNELS for name in channels):
        raise ContractError('withheld')
    for value in channels.values():
        _band_or_null(value)
        if value is None:
            raise ContractError('withheld')


def _validate_cut(payload):
    if not isinstance(payload, dict) or tuple(payload) != CUT_KEYS:
        raise ContractError('withheld')
    if payload['materialClass'] not in MATERIALS:
        raise ContractError('withheld')
    for key in (
        'thicknessMmBand', 'jobCountBand', 'copiesBand', 'jobSizeXMmBand', 'jobSizeYMmBand',
        'copySizeXMmBand', 'copySizeYMmBand', 'durationSecondsBand',
    ):
        _band_or_null(payload[key])
    _hash_or_null(payload['jobId'])


def _validate_inventory(payload):
    if not isinstance(payload, dict) or tuple(payload) != INVENTORY_KEYS:
        raise ContractError('withheld')
    if payload['materialClass'] not in MATERIALS or payload['unit'] not in UNITS:
        raise ContractError('withheld')
    if payload['source'] != 'view':
        raise ContractError('withheld')
    _band_or_null(payload['quantityBand'])
    _band_or_null(payload['reorderThresholdBand'])
    if not isinstance(payload['materialKey'], str) or not _HASH.fullmatch(payload['materialKey']):
        raise ContractError('withheld')


def _validate_nest(payload):
    import telemetry
    import telemetry_output
    if not isinstance(payload, dict):
        raise ContractError('withheld')
    allowed = {
        'schema', 'requestId', 'kind', 'instanceId', 'nestId', 'occurredAt',
        'appVersion', 'materialClass', 'bands',
    }
    if set(payload) != allowed or payload.get('schema') != telemetry_output.SCHEMA:
        raise ContractError('withheld')
    if payload.get('kind') not in telemetry.KINDS:
        raise ContractError('withheld')
    if not _INSTANCE.fullmatch(payload.get('instanceId') or ''):
        raise ContractError('withheld')
    nest = payload.get('nestId')
    if nest is not None and not _INSTANCE.fullmatch(nest):
        raise ContractError('withheld')
    if not _UUID5.fullmatch(payload.get('requestId') or ''):
        raise ContractError('withheld')
    if not isinstance(payload.get('occurredAt'), str) or not payload['occurredAt'].endswith('Z'):
        raise ContractError('withheld')
    material = payload.get('materialClass')
    if material is not None and material not in MATERIALS:
        raise ContractError('withheld')
    version = payload.get('appVersion')
    if not isinstance(version, str) or not telemetry_output.VERSION.fullmatch(version):
        raise ContractError('withheld')
    bands = payload.get('bands')
    if not isinstance(bands, dict) or set(bands) != set(telemetry_output.BANDS):
        raise ContractError('withheld')
    for value in bands.values():
        if value is None:
            continue
        if not isinstance(value, str) or not _BAND.fullmatch(value):
            raise ContractError('withheld')


def _reject_identity(event):
    blob = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
    if _EMAIL.search(blob) or _IPV4.search(blob):
        raise ContractError('withheld')
    if '$@' in blob or '$' in blob or '\\\\' in blob:
        raise ContractError('withheld')
    _walk(event)


def _walk(value, key=''):
    if isinstance(value, dict):
        for name, item in value.items():
            if name.casefold().replace('-', '') in _IDENTITY_KEYS and name not in ('jobId', 'materialKey'):
                raise ContractError('withheld')
            _walk(item, name)
        return
    if isinstance(value, list):
        for item in value:
            _walk(item, key)
        return
    if isinstance(value, str) and key not in ('schema', 'occurredAt', 'appVersion'):
        if any(token in value.casefold() for token in ('.pdf', '.csv', '.txt', '.ai', '://')):
            raise ContractError('withheld')
        if '\\' in value or (key != 'schema' and '/' in value and key != 'kind'):
            # kind has no slash. schema is the only field allowed to contain '/'.
            if key != 'schema':
                raise ContractError('withheld')
