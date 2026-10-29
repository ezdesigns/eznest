"""Read-only parser for a Summa GoProduce Joblog.csv line.

The file is semicolon-separated and has no header. Confirmed column order:

Date; Job name; Start time; End time; Material name; Material thickness;
Number of jobs; Job size X; Job size Y; Copies per job; Copy size X; Copy size Y.

Only the job name can carry a customer identity. It is hashed and the raw
text is dropped. `columns` can still be reordered if a shop export differs.
"""
from connector.events import band
from connector.parsing import (
    as_utc_z, classify_material, combine, decode_line, duration_seconds, job_hash,
    map_columns, parse_clock, parse_date, parse_length_mm, parse_number, split_fields,
)

NAME = 'summa_joblog'
SOURCE = 'cutter'
KIND = 'cut.completed'
DEFAULT_COLUMNS = (
    'date', 'job_name', 'start', 'end', 'material', 'thickness',
    'job_count', 'job_size_x', 'job_size_y', 'copies', 'copy_size_x', 'copy_size_y',
)


def parse_line(raw, options, salt):
    text = decode_line(raw)
    if text is None:
        return None
    stripped = text.strip()
    if not stripped or stripped.startswith('{{'):
        return None
    delimiter = options.get('delimiter') or ';'
    order = options.get('dateOrder') or 'dmy'
    unit = options.get('sizeUnit') or 'mm'
    columns = tuple(options.get('columns') or DEFAULT_COLUMNS)
    try:
        fields = split_fields(stripped, delimiter)
        mapped, job_parts = map_columns(fields, columns)
    except ValueError:
        return None
    day = parse_date(mapped.get('date'), order)
    start = combine(day, parse_clock(mapped.get('start')))
    end = combine(day, parse_clock(mapped.get('end')))
    occurred = as_utc_z(end)
    if occurred is None:
        return None
    payload = {
        'materialClass': classify_material(mapped.get('material')),
        'thicknessMmBand': band(parse_length_mm(mapped.get('thickness'), 'mm'), '0.1'),
        'jobCountBand': band(parse_number(mapped.get('job_count')), 10),
        'copiesBand': band(parse_number(mapped.get('copies')), 10),
        'jobSizeXMmBand': band(parse_length_mm(mapped.get('job_size_x'), unit), 100),
        'jobSizeYMmBand': band(parse_length_mm(mapped.get('job_size_y'), unit), 100),
        'copySizeXMmBand': band(parse_length_mm(mapped.get('copy_size_x'), unit), 100),
        'copySizeYMmBand': band(parse_length_mm(mapped.get('copy_size_y'), unit), 100),
        'durationSecondsBand': band(duration_seconds(start, end), 15),
        'jobId': job_hash(salt, job_parts),
    }
    return {'source': SOURCE, 'kind': KIND, 'occurredAt': occurred, 'payload': payload}
