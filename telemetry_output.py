"""Strict projection of local observations for OUTPUT's eznest-observation/1.

No network, consent state, credential storage or automatic delivery is performed
by this module. Customer data, job codes, roll IDs and exact values stay local.
"""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import telemetry

SCHEMA = 'eznest-observation/1'
BANDS = {
    'lengthMmBand': 250, 'printableWidthMmBand': 100, 'rollWidthMmBand': 100,
    'printableAreaM2Band': .25, 'rollAreaM2Band': .25, 'unusedPrintablePercentBand': 5,
    'pieceCountBand': 10, 'sheetCountBand': 5, 'searchSecondsBand': 15,
    'remainingMmBand': 250, 'reportedRemainingMmBand': 250,
    'availableAfterAllocationMmBand': 250,
}
MATERIALS = ('moto_regular', 'moto_holographic', 'moto_chrome', 'custom', 'unknown')
VERSION = re.compile(r'[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(?:-(?:rc|beta|alpha)\.[0-9]{1,5})?')


def invalid():
    # Never include a private local value in an exception or HTTP response.
    raise ValueError('This local observation does not match the OUTPUT privacy contract.')


def band(value, key):
    if value is None or value == '0':
        return value
    if not isinstance(value, str) or len(value) > 80:
        return invalid()
    match = re.fullmatch(r'\[([0-9]+(?:\.[0-9]+)?(?:e\+[0-9]+)?),([0-9]+(?:\.[0-9]+)?(?:e\+[0-9]+)?)\)', value)
    if not match:
        return invalid()
    try:
        lo, hi = (Decimal(v) for v in match.groups())
        step = Decimal(str(BANDS[key]))
        if hi > Decimal('1e12') + step or hi-lo != step or lo % step or (key == 'unusedPrintablePercentBand' and lo > 100):
            return invalid()
        # Local bands may use scientific notation; the wire format is decimal.
        return '[' + format(lo, 'f') + ',' + format(hi, 'f') + ')'
    except InvalidOperation:
        return invalid()


def project(atom):
    """Project only the explicit wire allowlist; never copy the local payload."""
    if not isinstance(atom, dict) or atom.get('schema') != telemetry.SCHEMA or atom.get('source') != 'eznest':
        return invalid()
    for field, pattern in (('id', r'[0-9a-f]{64}'), ('instanceId', r'[0-9a-f]{32}')):
        if not isinstance(atom.get(field), str) or not re.fullmatch(pattern, atom[field]):
            return invalid()
    kind = atom.get('type')
    if kind not in telemetry.KINDS:
        return invalid()
    nest = atom.get('nestId')
    if kind == 'material.stock_recorded':
        if nest is not None:
            return invalid()
    elif not isinstance(nest, str) or not telemetry.ID.fullmatch(nest):
        return invalid()
    version = atom.get('appVersion')
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        return invalid()
    try:
        timestamp = atom['occurredAt']
        if not isinstance(timestamp, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)', timestamp):
            return invalid()
        occurred = datetime.fromisoformat(timestamp).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, KeyError, TypeError):
        return invalid()
    payload = atom.get('payload')
    if not isinstance(payload, dict):
        return invalid()
    material = payload.get('materialClass')
    if material is not None and material not in MATERIALS:
        return invalid()
    return {
        'schema': SCHEMA,
        'requestId': str(uuid.uuid5(uuid.NAMESPACE_URL, f"eznest:{atom['instanceId']}:{atom['id']}")),
        'kind': kind, 'instanceId': atom['instanceId'], 'nestId': nest,
        'occurredAt': occurred, 'appVersion': version, 'materialClass': material,
        'bands': {key: band(payload.get(key), key) for key in BANDS},
    }
