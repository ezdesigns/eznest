"""Read-only parser for an ONYX Thrive JobLog.txt line.

The layout below is taken from shop samples (a verified reference parser dated
2026-10-15), not from ONYX's own documentation. It still needs to be checked
against one real JobLog line before this plug-in is turned on in a shop.

One completed record per line: {{ "field" "field" ... }}. Fields are quoted
and separated by spaces, not commas. At least 20 quoted fields are required.

0-based positions from those samples:
  [0] status, [1] PDF name, [2] title, [3] epoch seconds,
  [5] pixels along the feed (print length), [6] pixels across the roll,
  [9] copies, [10] dpi across, [11] dpi along the feed,
  [13] printer, [14] media profile, [15] print mode, [16] print time HH:MM:SS,
  [17] Quick Set, [18] ink per channel ("K: 0.75 C: 0.80"),
  [19] total ink, last field coverage percent.

In the samples, [6]/[10] stays within the roll width and [5]/[11] is the long
axis, so [6] is across and [5] is the length that uses media. A few rotated
jobs log a long [6]. When the across-roll size is above 64.5 inches and the
feed size is not, the axes are swapped. 64.5 inches is the widest roll in
those samples (S80600 is 64 inches). That limit is inferred, not an ONYX rule.

Status "1" is the only completed print in the samples. "-1" and "0" are sent
as abnormal. Which of those two means aborted versus incomplete is UNVERIFIED.

The PDF name, title, Quick Set, print mode, raw media profile, and the raw
line are not sent. jobId is a salted hash of the name and title.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

from connector.events import INK_CHANNELS, band, percent_band
from connector.parsing import (
    classify_material, decode_line, from_epoch, job_hash, parse_number, parse_seconds,
)

NAME = 'onyx_joblog'
SOURCE = 'printer'
KIND = 'print.completed'
# Inferred from samples. Not confirmed in ONYX documentation.
MAX_ACROSS_IN = Decimal('64.5')
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_INK = re.compile(r'([A-Za-z]+):\s*([\d.]+)')
_CHANNEL = {
    'k': 'k', 'c': 'c', 'm': 'm', 'y': 'y', 'w': 'w',
    'lc': 'lc', 'lm': 'lm', 'lk': 'lk', 'llk': 'llk', 'or': 'or', 'gr': 'gr',
}


def parse_line(raw, options, salt):
    text = decode_line(raw)
    if text is None or '{{' not in text:
        return None
    fields = _QUOTED.findall(text)
    if len(fields) < 20:
        return None
    onyx_status = fields[0].strip()
    if onyx_status == '1':
        status = 'ok'
    elif onyx_status in ('-1', '0'):
        # UNVERIFIED: samples treat both as not completed. ONYX docs do not say
        # which is aborted and which is incomplete.
        status = 'abnormal'
    else:
        return None
    occurred = from_epoch(fields[3])
    feed_px = parse_number(fields[5])
    across_px = parse_number(fields[6])
    if occurred is None or feed_px is None or across_px is None or feed_px <= 0 or across_px <= 0:
        return None
    printer = fields[13]
    allowed = options.get('printers') or []
    if not allowed or printer.strip().casefold() not in {item.strip().casefold() for item in allowed}:
        return None
    dpi_across = parse_number(fields[10]) or Decimal(720)
    dpi_feed = parse_number(fields[11]) or dpi_across
    if dpi_across <= 0 or dpi_feed <= 0:
        return None
    copies = parse_number(fields[9])
    if copies is None or copies <= 0:
        copies = Decimal(1)
    width_in = across_px / dpi_across
    length_in = feed_px / dpi_feed
    axis_swapped = False
    if width_in > MAX_ACROSS_IN and length_in <= MAX_ACROSS_IN:
        width_in, length_in = length_in, width_in
        axis_swapped = True
    width_in = _hundredth(width_in)
    length_in = _hundredth(length_in)
    media_ft = _hundredth(length_in * copies / Decimal(12))
    model = machine_model(printer)
    channels = {}
    for match in _INK.finditer(fields[18]):
        key = _CHANNEL.get(match.group(1).casefold())
        if key not in INK_CHANNELS:
            continue
        measured = band(parse_number(match.group(2)), 1)
        if measured is not None:
            channels[key] = measured
    payload = {
        'status': status,
        'printerClass': model,
        'mediaClass': classify_material(fields[14]),
        'copiesBand': band(copies, 10),
        'inkTotalMlBand': band(_leading_number(fields[19]), 1),
        'inkChannelsMlBand': channels,
        'coveragePercentBand': percent_band(_leading_number(fields[-1])),
        'printTimeSecondsBand': band(parse_seconds(fields[16]), 15),
        'widthMmBand': band(width_in * Decimal('25.4'), 100),
        'lengthMmBand': band(length_in * Decimal('25.4'), 250),
        'jobId': job_hash(salt, [fields[1], fields[2]]),
        'onyxStatus': onyx_status,
        'machineModel': model,
        'mediaUsedFt': format(media_ft, '.2f'),
        'widthIn': format(width_in, '.2f'),
        'axisSwapped': axis_swapped,
    }
    return {'source': SOURCE, 'kind': KIND, 'occurredAt': occurred, 'payload': payload}


def machine_model(text):
    """Coarse class for the printers seen in samples. The raw name is not sent.

    Inferred from model text in those samples, not from an ONYX model list.
    """
    folded = (text or '').casefold()
    compact = folded.replace(' ', '').replace('-', '')
    if 's80600' in compact:
        return 'epson_s80600'
    if 'vs540' in compact:
        return 'roland_vs540'
    if 'latex' in compact and '570' in compact:
        return 'hp_latex_570'
    if '7890' in compact:
        return 'epson_7890'
    return 'unknown'


def _hundredth(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _leading_number(value):
    match = re.match(r'\s*([0-9]+(?:\.[0-9]+)?)', str(value or '').replace(',', '.'))
    if not match:
        return None
    return parse_number(match.group(1))
