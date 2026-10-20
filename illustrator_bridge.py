"""Loopback-only Illustrator handoff. Files stay in the local app data directory."""
import base64
import hashlib
import json
import math
import re
from pathlib import Path

IDENT = re.compile(r'^[a-f0-9]{32}$')


def root(data_dir):
    folder = Path(data_dir) / 'illustrator'
    folder.mkdir(exist_ok=True)
    return folder


def clean_id(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError('Invalid Illustrator handoff ID.')
    return value


def accept(data_dir, data):
    ident = clean_id(data.get('requestId'))
    if data.get('material') != 'regular':
        raise ValueError('Only Regular is configured for this pilot.')
    settings = {}
    for key, low, high in [('widthIn', 1, 196), ('sets', 1, 100), ('bleedMm', 0, 25)]:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid Illustrator ' + key)
        settings[key] = value
    if int(settings['sets']) != settings['sets']:
        raise ValueError('Kit quantity must be a whole number.')
    source = data.get('sourceKey')
    if not isinstance(source, str) or not 1 <= len(source) <= 4096:
        raise ValueError('A source document reference is required.')
    content = data.get('content')
    if not isinstance(content, str) or len(content) > 27_000_000:
        raise ValueError('Use a production PDF smaller than 20 MB.')
    try:
        raw = base64.b64decode(content, validate=True)
    except ValueError:
        raise ValueError('Invalid PDF encoding.') from None
    if not raw.startswith(b'%PDF-') or len(raw) > 20_000_000:
        raise ValueError('Use a production PDF smaller than 20 MB.')
    meta = {'id': ident, 'sourceId': hashlib.sha256(source.encode()).hexdigest(),
            'revision': hashlib.sha256(raw).hexdigest(), 'material': 'regular', **settings}
    directory = root(data_dir)
    target = directory / (ident + '.json')
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != meta:
            raise ValueError('This handoff ID already belongs to another export.')
        return meta
    (directory / (ident + '.pdf')).write_bytes(raw)
    temp = directory / (ident + '.tmp')
    temp.write_text(json.dumps(meta), encoding='utf-8')
    temp.replace(target)
    return meta


def read(data_dir, ident):
    ident = clean_id(ident)
    directory = root(data_dir)
    meta = json.loads((directory / (ident + '.json')).read_text(encoding='utf-8'))
    raw = (directory / (ident + '.pdf')).read_bytes()
    if hashlib.sha256(raw).hexdigest() != meta['revision']:
        raise ValueError('The saved Illustrator PDF changed. Export again.')
    return {**meta, 'content': base64.b64encode(raw).decode('ascii')}


def tracking_id(job, fallback):
    bridge = job.get('illustrator')
    if not bridge:
        return fallback
    # Layout improvements are one attempt; quantity/material changes are distinct.
    clean_id(bridge['id'])
    settings = {k: v for k, v in job.get('settings', {}).items() if k not in ('seed', 'seconds')}
    signature = [bridge['id'], sorted((p['id'], p['quantity']) for p in job['parts']),
                 settings, job.get('media', {})]
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:32]
