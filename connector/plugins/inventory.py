"""Read-only inventory view.

Input fields are name or material, category, qty_on_hand, unit,
reorder_threshold, and updated_at. Cost, customer, and order fields are not
read. An observation is emitted only when the quantity changes after the
connect-time baseline.
"""
import json
from decimal import Decimal

from connector.events import UNITS, band, salted_hash
from connector.parsing import as_utc_z, classify_material, decode_line, parse_number

NAME = 'inventory'
SOURCE = 'inventory'
KIND = 'inventory.observed'
_INPUT = ('material', 'name', 'category', 'qty_on_hand', 'unit', 'reorder_threshold', 'updated_at')
_STEPS = {'mm': 250, 'm': 1, 'ml': 1, 'sheets': 10, 'rolls': 10, 'each': 10}


class PartialView(ValueError):
    pass


def load_rows(data):
    """Parse a JSON snapshot or JSON lines. A torn snapshot raises PartialView.

    JSON lines use the shared newline rule: the last line is kept only when it
    already ends with a newline.
    """
    raw = data if isinstance(data, bytes) else str(data).encode('utf-8')
    text = decode_line(raw)
    if text is None:
        raise PartialView('undecodable')
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped.startswith('[') or (stripped.startswith('{') and '"rows"' in stripped.split('\n', 1)[0]):
        if not _balanced(stripped):
            raise PartialView('partial')
        try:
            body = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise PartialView('partial') from error
        rows = body.get('rows') if isinstance(body, dict) else body
        if not isinstance(rows, list):
            raise PartialView('partial')
        return [_with_line(row) for row in rows]
    from connector.readfiles import complete_lines
    lines, _offset, _dropped, _skipping = complete_lines(raw, 0)
    rows = []
    for line in lines:
        decoded = decode_line(line)
        if decoded is None:
            continue
        try:
            rows.append(_with_line(json.loads(decoded), line))
        except json.JSONDecodeError:
            continue
    return rows


def _balanced(text):
    sample = text.rstrip()
    if sample.startswith('['):
        return sample.endswith(']')
    if sample.startswith('{'):
        return sample.endswith('}')
    return False


def pick(raw):
    """Copy only the allow-listed view fields. Everything else is ignored."""
    if not isinstance(raw, dict):
        return None
    label = _text(raw.get('material')) or _text(raw.get('name'))
    if not label:
        return None
    quantity = parse_number(raw.get('qty_on_hand'))
    unit = (_text(raw.get('unit')) or '').casefold()
    if quantity is None or unit not in UNITS:
        return None
    moment = _moment(raw.get('updated_at'))
    if moment is None:
        return None
    threshold = parse_number(raw.get('reorder_threshold')) if 'reorder_threshold' in raw else None
    line = raw.get('_line')
    if not isinstance(line, (bytes, bytearray)):
        line = json.dumps(
            {key: raw.get(key) for key in _INPUT if key in raw}, separators=(',', ':'), sort_keys=True,
        ).encode()
    return {
        'label': label,
        'category': _text(raw.get('category')) or '',
        'quantity': _canonical(quantity),
        'unit': unit,
        'threshold': None if threshold is None else _canonical(threshold),
        'occurredAt': moment,
        'line': bytes(line),
    }


class MemoryQty:
    """Replay baseline. It is not the live shop watermark."""

    def __init__(self):
        self.values = {}
        self.seeded = False

    def quantity(self, key):
        return self.values.get(key)

    def set_quantity(self, key, quantity):
        self.values[key] = quantity

    def inventory_seeded(self):
        return self.seeded

    def set_inventory_seeded(self):
        self.seeded = True


def fold(rows, state, salt, *, replay):
    """Seed on connect. After that, emit a row only when qty_on_hand changes.

    A live connect remembers the latest quantity in the current view and sends
    nothing. Replay walks the sample in order so a later different quantity is
    visible, and it does not write the live watermark.
    """
    parsed = [item for item in (pick(row) for row in rows) if item is not None]
    if replay:
        observations = []
        for item in parsed:
            key = _key(salt, item['label'])
            previous = state.quantity(key)
            state.set_quantity(key, item['quantity'])
            if previous is None or previous == item['quantity']:
                continue
            observations.append(_observation(item, key))
        return observations
    latest = {}
    for item in parsed:
        latest[_key(salt, item['label'])] = item
    if not state.inventory_seeded():
        for key, item in latest.items():
            state.set_quantity(key, item['quantity'])
        state.set_inventory_seeded()
        return []
    observations = []
    for key, item in latest.items():
        previous = state.quantity(key)
        if previous == item['quantity']:
            continue
        state.set_quantity(key, item['quantity'])
        if previous is None or previous != item['quantity']:
            observations.append(_observation(item, key))
    return observations


def _observation(item, key):
    step = _STEPS[item['unit']]
    payload = {
        'materialClass': classify_material(item['category'] or item['label']),
        'materialKey': key,
        'quantityBand': band(Decimal(item['quantity']), step),
        'unit': item['unit'],
        'reorderThresholdBand': None if item['threshold'] is None else band(Decimal(item['threshold']), step),
        'source': 'view',
    }
    return {
        'source': SOURCE, 'kind': KIND, 'occurredAt': item['occurredAt'],
        'payload': payload, 'line': item['line'],
    }


def _with_line(row, line=None):
    if isinstance(row, dict):
        row = dict(row)
        row['_line'] = line if line is not None else json.dumps(
            {key: row.get(key) for key in _INPUT if key in row}, separators=(',', ':'), sort_keys=True,
        ).encode()
    return row


def _key(salt, label):
    return salted_hash(salt, 'material', label)


def _text(value):
    if not isinstance(value, str):
        return None
    text = ' '.join(value.split())
    return text or None


def _canonical(number):
    return format(number, 'f')


def _moment(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        from datetime import datetime
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return as_utc_z(moment)
