"""Read-only parser for an ONYX JobLog.txt line.

The shop file is one {{ ... }} record per line. The column order below is a
placeholder until a real JobLog is confirmed. Configure `columns` to match
the file. Only timing, material class, dimensions, counts, status, and banded
ink/coverage leave this parser. The printer filter is exact and case-insensitive.
An empty filter sends nothing.
"""
from connector.events import INK_CHANNELS, band, percent_band
from connector.parsing import (
    classify_material, classify_printer, classify_status, decode_line,
    job_hash, map_columns, parse_number, parse_seconds, pixels_to_mm, split_fields,
    from_epoch,
)

NAME = 'onyx_joblog'
SOURCE = 'printer'
KIND = 'print.completed'
DEFAULT_DELIMITER = ','
DEFAULT_COLUMNS = (
    'status', 'source_filename', 'title', 'end_epoch', 'length_px', 'width_px',
    'copies', 'dpi', 'printer', 'media', 'print_mode', 'print_time_s', 'quick_set',
    'ink_c_ml', 'ink_m_ml', 'ink_y_ml', 'ink_k_ml', 'ink_lc_ml', 'ink_lm_ml',
    'ink_lk_ml', 'ink_total_ml', 'coverage_pct',
)
_CHANNEL_COLUMNS = {
    'ink_c_ml': 'c', 'ink_m_ml': 'm', 'ink_y_ml': 'y', 'ink_k_ml': 'k',
    'ink_lc_ml': 'lc', 'ink_lm_ml': 'lm', 'ink_lk_ml': 'lk', 'ink_llk_ml': 'llk',
    'ink_or_ml': 'or', 'ink_gr_ml': 'gr', 'ink_w_ml': 'w',
}


def parse_line(raw, options, salt):
    text = decode_line(raw)
    if text is None:
        return None
    stripped = text.strip()
    if not (stripped.startswith('{{') and stripped.endswith('}}')):
        return None
    delimiter = options.get('delimiter') or DEFAULT_DELIMITER
    columns = tuple(options.get('columns') or DEFAULT_COLUMNS)
    try:
        fields = split_fields(stripped[2:-2].strip(), delimiter)
        mapped, job_parts = map_columns(fields, columns)
    except ValueError:
        return None
    status = classify_status(mapped.get('status'))
    occurred = from_epoch(mapped.get('end_epoch'))
    if status is None or occurred is None:
        return None
    printer = mapped.get('printer') or ''
    allowed = options.get('printers') or []
    if not allowed or printer.strip().casefold() not in {item.strip().casefold() for item in allowed}:
        return None
    dpi = mapped.get('dpi')
    channels = {}
    for column, name in _CHANNEL_COLUMNS.items():
        if name not in INK_CHANNELS:
            continue
        measured = band(parse_number(mapped.get(column)), 1)
        if measured is not None and column in mapped and str(mapped.get(column)).strip() != '':
            channels[name] = measured
    payload = {
        'status': status,
        'printerClass': classify_printer(printer),
        'mediaClass': classify_material(mapped.get('media')),
        'copiesBand': band(parse_number(mapped.get('copies')), 10),
        'inkTotalMlBand': band(parse_number(mapped.get('ink_total_ml')), 1),
        'inkChannelsMlBand': channels,
        'coveragePercentBand': percent_band(parse_number(mapped.get('coverage_pct'))),
        'printTimeSecondsBand': band(parse_seconds(mapped.get('print_time_s')), 15),
        'widthMmBand': band(pixels_to_mm(mapped.get('width_px'), dpi), 100),
        'lengthMmBand': band(pixels_to_mm(mapped.get('length_px'), dpi), 250),
        'jobId': job_hash(salt, job_parts),
    }
    return {'source': SOURCE, 'kind': KIND, 'occurredAt': occurred, 'payload': payload}
