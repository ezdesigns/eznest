"""Adapt local Ez Nest telemetry into nest.completed.

Reads telemetry.sqlite3 with query_only. The first poll records the current
sequence and sends nothing. Later polls project new rows through the existing
eznest-observation/1 allow-list. This plug-in does not write that database.
"""
import json
import sqlite3
from pathlib import Path

import telemetry_output

NAME = 'eznest'
SOURCE = 'eznest'
KIND = 'nest.completed'
DEFAULT_KINDS = ('nest.printed',)


def parse_atom(atom, options):
    if not isinstance(atom, dict):
        return None
    kinds = tuple(options.get('kinds') or DEFAULT_KINDS)
    if atom.get('type') not in kinds:
        return None
    try:
        projected = telemetry_output.project(atom)
    except (TypeError, ValueError):
        return None
    occurred = projected.get('occurredAt')
    if not isinstance(occurred, str):
        return None
    if occurred.endswith('+00:00'):
        occurred = occurred[:-6] + 'Z'
    identity = atom.get('id')
    if not isinstance(identity, str):
        return None
    return {
        'source': SOURCE,
        'kind': KIND,
        'occurredAt': occurred,
        'payload': projected,
        'line': b'eznest-event:' + identity.encode('utf-8'),
    }


def open_database(path):
    """Open the telemetry file read-only. Missing files are not created."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)
    from connector.readfiles import OPENED
    OPENED.append(str(target.resolve()))
    uri = target.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only = ON')
    return db


def max_sequence(db):
    row = db.execute('SELECT COALESCE(MAX(seq), 0) FROM events').fetchone()
    return int(row[0] if row else 0)


def rows_after(db, seq):
    return list(db.execute(
        'SELECT seq, atom FROM events WHERE seq > ? ORDER BY seq', (int(seq),),
    ))


def load_atom(raw):
    try:
        atom = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return atom if isinstance(atom, dict) else None
