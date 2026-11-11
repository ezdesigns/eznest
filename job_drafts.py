"""Private, atomic pre-nest drafts. Artwork is kept on the shop host only."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

FIELDS = set(('material unit preset-name roll width nest-width mark-margin gap margin rotations '
              'sheet print-layout roll-length roll-cost available-length low-stock auto-bleed bleed '
              'cost sets nesting-effort generic-cut thru-name kiss-name cut-preset draw-marks').split())


class Conflict(ValueError):
    pass


def atomic(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read(root):
    path = Path(root)/'draft.json'
    if not path.exists():
        return {'revision': None, 'draft': None, 'runId': None}
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(result, dict) or not re.fullmatch('[a-f0-9]{32}', result['revision']):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError) as error:
        raise OSError('Your saved draft could not be read. It has been kept on this PC.') from error


def check(root, revision):
    saved = read(root)
    if revision != saved['revision']:
        raise Conflict('This job changed in another tab. Refresh to load the latest saved job.')
    return saved


def key(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid saved artwork reference.')
    return value


def validate_artwork(root, data, role):
    if not isinstance(data, dict) or data.get('format') not in ('pdf', 'svg'):
        raise ValueError('Invalid draft artwork.')
    parts = data.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 5000:
        raise ValueError('Invalid draft pieces.')
    if any(not isinstance(p, dict) or not isinstance(p.get('id'), str) for p in parts):
        raise ValueError('Invalid draft piece.')
    if len({p['id'] for p in parts}) != len(parts):
        raise ValueError('Duplicate draft pieces.')
    if data['format'] == 'svg':
        if not isinstance(data.get('svgSource'), dict):
            raise ValueError('SVG artwork is missing.')
        return
    ident = key(data.get('documentId'))
    folder = Path(root)/'documents'
    if not (folder/(ident+'.pdf')).is_file():
        raise ValueError('This artwork is not in your workspace. Upload it again.')
    meta = json.loads((folder/(ident+'.json')).read_text(encoding='utf-8'))
    expected = {p['id']: p for p in meta['pieces']}
    selected = data.get('selectedPieceIds')
    if selected is not None:
        if (role != 'fill' or not isinstance(selected, list) or not selected
                or any(not isinstance(s, str) for s in selected)
                or len(set(selected)) != len(selected) or not set(selected) <= expected.keys()):
            raise ValueError('Invalid saved sticker selection.')
        expected = {ident: expected[ident] for ident in selected}
    if {p.get('pdfPieceId') for p in parts} != expected.keys() or len(parts) != len(expected):
        raise ValueError('Saved pieces do not match the imported artwork.')
    for part in parts:
        if part.get('documentId') != ident or part.get('points') != expected[part['pdfPieceId']]['points']:
            raise ValueError('Saved geometry does not match the imported artwork.')


def save(root, payload):
    check(root, payload.get('revision'))
    entries, fields, supplied = payload.get('entries'), payload.get('fields'), payload.get('assets', {})
    if not isinstance(entries, list) or not 1 <= len(entries) <= 5800:
        raise ValueError('Add a file before saving a draft.')
    if not isinstance(fields, dict) or not fields.keys() <= FIELDS:
        raise ValueError('Invalid draft settings.')
    if any(not isinstance(v, (str, bool)) or len(str(v)) > 512 for v in fields.values()):
        raise ValueError('Invalid draft setting.')
    if not isinstance(supplied, dict) or len(supplied) > len(entries):
        raise ValueError('Invalid draft artwork.')
    folder = Path(root)/'draft-artwork'; folder.mkdir(exist_ok=True)
    assets, clean, seen = {}, [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid draft entry.')
        ident = entry.get('id')
        if not isinstance(ident, str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}', ident) or ident in seen:
            raise ValueError('Invalid draft identity.')
        seen.add(ident)
        role = entry.get('role')
        if role not in ('required', 'fill') or type(entry.get('sets')) is not int or not 1 <= entry['sets'] <= 5000:
            raise ValueError('Enter a whole quantity from 1 to 5000 to save this draft.')
        asset = key(entry.get('dataKey'))
        if asset not in assets:
            if asset in supplied:
                raw = supplied[asset]
                if not isinstance(raw, str) or hashlib.sha256(raw.encode('utf-8')).hexdigest() != asset:
                    raise ValueError('Saved artwork checksum does not match.')
                assets[asset] = json.loads(raw)
            else:
                try: assets[asset] = json.loads((folder/(asset+'.json')).read_text(encoding='utf-8'))
                except FileNotFoundError: raise ValueError('Draft artwork is missing. Upload it again.') from None
        validate_artwork(root, assets[asset], role)
        item = {k: entry[k] for k in ('id', 'role', 'sets', 'dataKey')}
        for name in ('name', 'sourceFile', 'revision'):
            value = entry.get(name, '')
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError('Invalid draft file name.')
            item[name] = value
        item['unresolved'] = entry.get('unresolved') is True
        clean.append(item)
    if not any(e['role'] == 'required' for e in clean) or set(supplied)-assets.keys():
        raise ValueError('Invalid draft files.')
    handoff = payload.get('illustrator')
    if handoff is not None:
        if not isinstance(handoff, dict) or not re.fullmatch('[a-f0-9]{32}', str(handoff.get('id', ''))):
            raise ValueError('Invalid Illustrator draft.')
        import illustrator_bridge
        illustrator_bridge.read(root, handoff['id'])
        handoff = {'id': handoff['id'], 'documentId': key(handoff.get('documentId'))}
    # Assets are immutable and deduplicated. An interrupted save leaves the old
    # draft intact; originals and PDF bleed are never rewritten here.
    for asset, data in assets.items():
        if not (folder/(asset+'.json')).exists(): atomic(folder/(asset+'.json'), data)
    record = {'revision': uuid.uuid4().hex, 'runId': None,
              'draft': {'entries': clean, 'fields': fields, 'illustrator': handoff}}
    atomic(Path(root)/'draft.json', record)
    return {'revision': record['revision']}


def public(root):
    record = read(root)
    if record['draft']:
        assets = {}
        for entry in record['draft']['entries']:
            ident = key(entry['dataKey'])
            if ident not in assets:
                assets[ident] = json.loads((Path(root)/'draft-artwork'/(ident+'.json')).read_text(encoding='utf-8'))
            validate_artwork(root, assets[ident], entry['role'])
        record['assets'] = assets
    return record


def bind(root, run_id):
    record = read(root)
    if record['draft']:
        record.update(revision=uuid.uuid4().hex, runId=run_id)
        atomic(Path(root)/'draft.json', record)
    return record['revision']


def clear(root):
    record = {'revision': uuid.uuid4().hex, 'draft': None, 'runId': None}
    atomic(Path(root)/'draft.json', record)
    return record['revision']
