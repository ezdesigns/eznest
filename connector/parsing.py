"""Shared parsers. Free text is classified or hashed here and then dropped."""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from connector.events import MATERIALS, salted_hash

IDENTITY_COLUMNS = frozenset({
    'email', 'phone', 'address', 'price', 'cost', 'customer', 'filename', 'file',
    'title', 'order', 'order_id', 'ip', 'path', 'raw', 'quick_set', 'print_mode',
})
# job_name, source_filename and title are read only so they can be hashed.
HASH_COLUMNS = frozenset({'job_name', 'source_filename', 'title'})


def split_fields(text, delimiter):
    """Split one delimited record. Quotes can hold the delimiter."""
    if delimiter not in (',', ';', '\t'):
        raise ValueError('delimiter')
    fields = []
    buf = []
    quoted = False
    i = 0
    while i < len(text):
        ch = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                quoted = False
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            quoted = True
            i += 1
            continue
        if ch == delimiter:
            fields.append(''.join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quoted:
        raise ValueError('unclosed')
    fields.append(''.join(buf).strip())
    return fields


def map_columns(fields, columns):
    """Map configured column names. Identity columns are not returned as values."""
    mapped = {}
    job_parts = []
    for index, name in enumerate(columns):
        if index >= len(fields) or not name or name == '-':
            continue
        key = str(name).strip()
        value = fields[index]
        # Job name, title, and source file are hashed and then dropped.
        if key in HASH_COLUMNS or key.casefold() in HASH_COLUMNS:
            if value:
                job_parts.append(value)
            continue
        if key.casefold() in IDENTITY_COLUMNS:
            continue
        mapped[key] = value
    return mapped, job_parts


def classify_material(text):
    folded = (text or '').casefold()
    if not folded:
        return 'unknown'
    if 'holo' in folded:
        return 'moto_holographic'
    if 'chrome' in folded or 'mirror' in folded:
        return 'moto_chrome'
    if any(word in folded for word in ('gloss', 'vinyl', 'regular', 'matte', 'banner')):
        return 'moto_regular'
    if folded in MATERIALS:
        return folded
    return 'custom'


def classify_printer(text):
    folded = (text or '').casefold().replace(' ', '')
    if 's80600' in folded:
        return 'epson_s80600'
    return 'unknown'


def classify_status(text):
    value = (text or '').strip()
    if value == '1':
        return 'ok'
    if value in ('0', '-1'):
        return 'abnormal'
    return None


def parse_number(value):
    if value is None:
        return None
    text = str(value).strip().replace(' ', '').rstrip('%')
    if not text:
        return None
    if text.count(',') == 1 and '.' not in text:
        text = text.replace(',', '.')
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number


def parse_length_mm(value, unit):
    text = str(value or '').strip().casefold()
    if not text:
        return None
    match = re.fullmatch(r'([0-9]+(?:[.,][0-9]+)?)\s*(mm|cm|in|inch|inches)?', text)
    if not match:
        return None
    number = parse_number(match.group(1))
    if number is None:
        return None
    chosen = match.group(2) or unit
    if chosen == 'mm':
        return number
    if chosen == 'cm':
        return number * 10
    if chosen in ('in', 'inch', 'inches'):
        return number * Decimal('25.4')
    return None


def pixels_to_mm(pixels, dpi):
    width = parse_number(pixels)
    dots = parse_number(dpi)
    if width is None or dots is None or dots <= 0:
        return None
    return width / dots * Decimal('25.4')


def parse_seconds(value):
    number = parse_number(value)
    if number is not None:
        return number
    text = str(value or '').strip()
    parts = text.split(':')
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    else:
        hours, minutes, seconds = numbers
    if minutes > 59 or seconds > 59:
        return None
    return Decimal(hours * 3600 + minutes * 60 + seconds)


_DATE_FORMATS = {
    'ymd': ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'),
    'dmy': ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y'),
    'mdy': ('%m/%d/%Y', '%m-%d-%Y'),
}


def parse_date(value, order):
    text = str(value or '').strip()
    formats = _DATE_FORMATS.get(order, ()) + _DATE_FORMATS['ymd']
    seen = []
    for fmt in formats:
        if fmt not in seen:
            seen.append(fmt)
    for fmt in seen:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_clock(value):
    text = str(value or '').strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def combine(day, clock):
    if day is None or clock is None:
        return None
    return datetime(day.year, day.month, day.day, clock.hour, clock.minute, clock.second, tzinfo=timezone.utc)


def as_utc_z(moment):
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def from_epoch(value):
    number = parse_number(value)
    if number is None:
        return None
    if number > Decimal('100000000000'):
        number = number / Decimal(1000)
    if number < Decimal('1000000000') or number > Decimal('4000000000'):
        return None
    moment = datetime.fromtimestamp(int(number), timezone.utc)
    return as_utc_z(moment)


def duration_seconds(start, end):
    if start is None or end is None:
        return None
    if end < start:
        end = end + timedelta(days=1)
    seconds = Decimal(int((end - start).total_seconds()))
    if seconds < 0 or seconds > Decimal(86400 * 2):
        return None
    return seconds


def job_hash(salt, parts):
    text = ' '.join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    if not text:
        return None
    return salted_hash(salt, 'job', text)


def decode_line(raw):
    if isinstance(raw, str):
        return raw
    for encoding in ('utf-8', 'cp1252'):
        try:
            return bytes(raw).decode(encoding)
        except UnicodeDecodeError:
            continue
    return None
