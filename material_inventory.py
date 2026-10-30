"""Local shop inventory. Transactions, not browser preferences, own stock.

No artwork, filenames or customer identifiers are stored here. Reservations
survive workspace resets; only explicit use confirmation deducts physical stock.
"""
from contextlib import contextmanager
import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

FIELDS = set(('preset-name unit width roll gap margin sheet mark-margin rotations '
              'auto-bleed bleed cost roll-length roll-cost available-length low-stock print-layout').split())
FACTORS = {'in': 25.4, 'cm': 10, 'mm': 1}


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', value):
        raise ValueError('Invalid material or reservation reference.')
    return value


# Plain names for error messages; raw field keys are never shown to people.
LABELS = {
    'width': ('Width you can print on', '54'), 'roll': ('Roll width', '54'),
    'gap': ('Gap between pieces', '0.25'), 'margin': ('Margin', '0.5'),
    'mark-margin': ('Cut-mark margin', '0.5'), 'bleed': ('Bleed', '0.125'),
    'cost': ('Material cost', '1.25'), 'roll-length': ('Length of a new roll', '150'),
    'roll-cost': ('Roll price', '8.50'), 'available-length': ('Length left on roll', '75'),
    'low-stock': ('Low-stock warning', '10'), 'sheet': ('Sheet length', '24'),
}
MAX_NUMBER = 100_000_000


def number(value, label, minimum=0):
    name, example = LABELS.get(label, (label, '8.50'))
    problem = ValueError(f'{name} looks wrong. Enter a number like {example}.')
    if isinstance(value, bool):
        raise problem
    text = value if isinstance(value, str) else str(value) if isinstance(value, (int, float)) else None
    # Same rule as the browser: plain 0-9 digits with one optional point. No other scripts'
    # digits, no underscores, no exponents.
    if text is None or not re.fullmatch(r'\s*\+?(?:\d+(?:\.\d*)?|\.\d+)\s*', text, re.ASCII):
        if not (isinstance(value, (int, float)) and not isinstance(value, bool)):
            raise problem
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise problem from None
    if not math.isfinite(result) or result < minimum or result > MAX_NUMBER:
        raise problem
    return result


def clean_name(value):
    """Same-looking names become the same text: NFKC, no invisible or direction-changing
    characters, single spaces."""
    text = unicodedata.normalize('NFKC', str(value))
    text = ''.join(c for c in text if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Co', 'Cn') or c in ' \t\n')
    return ' '.join(text.split())


# Letters from other alphabets that look the same as Latin ones, plus Turkish i forms.
# Used only for the duplicate check; the name people see is not changed.
LOOK_ALIKES = str.maketrans({
    'а': 'a', 'в': 'b', 'е': 'e', 'ё': 'e', 'к': 'k', 'м': 'm', 'н': 'h', 'о': 'o', 'р': 'p', 'с': 'c',
    'т': 't', 'у': 'y', 'х': 'x', 'і': 'i', 'ї': 'i', 'ј': 'j', 'ѕ': 's', 'ԁ': 'd', 'ӏ': 'l', 'ԛ': 'q', 'ԝ': 'w',
    'α': 'a', 'β': 'b', 'ε': 'e', 'η': 'n', 'ι': 'i', 'κ': 'k', 'ν': 'v', 'ο': 'o', 'ρ': 'p', 'τ': 't',
    'υ': 'u', 'χ': 'x', 'ζ': 'z', 'μ': 'u', 'ı': 'i', '\u0307': None,
})


def name_key(value):
    return clean_name(value).casefold().translate(LOOK_ALIKES)


def profile(values):
    if not isinstance(values, dict) or values.get('unit') not in FACTORS:
        raise ValueError('Choose material units.')
    clean = {key: str(values.get(key, '')) for key in FIELDS}
    clean['preset-name'] = clean_name(clean['preset-name'])
    if any(len(v) > 120 or any(ord(c) < 32 for c in v) for v in clean.values()):
        raise ValueError('Material settings contain invalid text.')
    if not clean['preset-name']:
        raise ValueError('Enter a material name.')
    if clean['rotations'] not in ('free', '0', '0,180', '0,90,180,270'):
        raise ValueError('Choose a supported rotation mode.')
    if clean['print-layout'] not in ('continuous', 'sections') or clean['auto-bleed'] not in ('0', '0.0625', '0.125'):
        raise ValueError('Choose supported layout and bleed settings.')
    for key in ('width', 'roll'):
        number(clean[key], key, .001)
    if float(clean['width']) > float(clean['roll']):
        raise ValueError('Printable width cannot exceed roll width.')
    for key in ('gap', 'margin', 'mark-margin', 'bleed', 'cost', 'roll-length', 'roll-cost', 'available-length', 'low-stock', 'sheet'):
        if clean[key].strip():
            number(clean[key], key)
    clean['drawMarks'] = values.get('drawMarks') is True
    factor = FACTORS[clean['unit']]
    stock = number(clean['available-length'], 'available-length') * factor if clean['available-length'].strip() else None
    full = number(clean['roll-length'], 'roll-length') * factor if clean['roll-length'].strip() else None
    if stock is not None and full is not None and stock > full:
        raise ValueError('Stock cannot exceed the full roll length.')
    if clean['roll-cost'].strip() and not full:
        raise ValueError('Enter full roll length before its cost.')
    if full and clean['low-stock'].strip() and float(clean['low-stock']) * factor > full:
        raise ValueError('Low-stock threshold cannot exceed full roll length.')
    return clean, stock


@contextmanager
def database(directory):
    connection = sqlite3.connect(directory / 'materials.sqlite3', timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.executescript('''
          CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY, profile TEXT NOT NULL, stock REAL,
            revision INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS reservations (
            id TEXT PRIMARY KEY, material TEXT NOT NULL REFERENCES materials(id),
            length REAL NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
            created TEXT NOT NULL, updated TEXT NOT NULL);
        ''')
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def reserved(db, material):
    return db.execute("SELECT COALESCE(SUM(length),0) FROM reservations WHERE material=? AND status='reserved'", (material,)).fetchone()[0]


def snapshot(db):
    materials = []
    for row in db.execute('SELECT * FROM materials ORDER BY id'):
        held = reserved(db, row['id'])
        materials.append({'id': row['id'], 'profile': json.loads(row['profile']), 'revision': row['revision'],
                          'onHandMm': row['stock'], 'reservedMm': held,
                          'availableMm': None if row['stock'] is None else max(0, row['stock'] - held)})
    # Never hide an outstanding reservation behind the history limit.
    rows = db.execute("SELECT * FROM reservations WHERE status='reserved' ORDER BY created DESC").fetchall()
    rows += db.execute("SELECT * FROM reservations WHERE status!='reserved' ORDER BY updated DESC LIMIT 50").fetchall()
    return {'materials': materials, 'reservations': [dict(row) for row in rows]}


def read(directory):
    with database(directory) as db:
        return snapshot(db)


def save(directory, key, values, revision):
    key = ident(key)
    values, stock = profile(values)
    with database(directory) as db:
        previous = db.execute('SELECT * FROM materials WHERE id=?', (key,)).fetchone()
        expected = previous['revision'] if previous else 0
        if type(revision) is not int or revision != expected:
            raise ValueError('This material changed on another screen. Close and reopen Edit to use the latest stock.')
        wanted = name_key(values['preset-name'])
        # A roll saved before this check existed keeps its name when edited; a new or renamed
        # roll may not look the same as another one.
        kept = previous is not None and name_key(json.loads(previous['profile'])['preset-name']) == wanted
        if not kept:
            for other in db.execute('SELECT id, profile FROM materials WHERE id!=?', (key,)):
                if name_key(json.loads(other['profile'])['preset-name']) == wanted:
                    raise ValueError('A material with this name already exists.')
        held = reserved(db, key)
        if held and (stock is None or stock + 1e-6 < held):
            raise ValueError('Release outstanding reservations before reducing stock below the reserved amount.')
        if held:
            old = json.loads(previous['profile'])
            for field in ('unit', 'width', 'roll'):
                if old[field] != values[field]:
                    raise ValueError('Release reservations before changing material dimensions or units.')
        db.execute('INSERT INTO materials VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET profile=excluded.profile, stock=excluded.stock, revision=excluded.revision',
                   (key, json.dumps(values), stock, expected + 1))
        return snapshot(db)


def reserve(directory, key, run, length, width, fingerprint):
    key, run = ident(key), ident(run)
    length, width = number(length, 'Layout length', .001), number(width, 'Layout width', .001)
    with database(directory) as db:
        old = db.execute('SELECT * FROM reservations WHERE id=?', (run,)).fetchone()
        if old:
            if old['material'] != key or old['fingerprint'] != fingerprint or abs(old['length'] - length) > 1e-6:
                raise ValueError('This layout already has a different material reservation. Release it and calculate a new layout.')
            if old['status'] == 'cancelled':
                raise ValueError('This reservation was released. Calculate a new layout before reserving again.')
            return snapshot(db)
        material = db.execute('SELECT * FROM materials WHERE id=?', (key,)).fetchone()
        if not material:
            raise ValueError('Save this material to shop inventory first.')
        values = json.loads(material['profile'])
        if width > float(values['width']) * FACTORS[values['unit']] + .05:
            raise ValueError('This layout is wider than the material. Choose the correct roll and nest again.')
        if material['stock'] is None:
            raise ValueError('Enter measured stock on the roll before reserving material.')
        if length > material['stock'] - reserved(db, key) + 1e-6:
            raise ValueError('Not enough unreserved material on this roll. Update stock or choose another roll.')
        now = datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?)', (run, key, length, fingerprint, 'reserved', now, now))
        db.execute('UPDATE materials SET revision=revision+1 WHERE id=?', (key,))
        return snapshot(db)


def transition(directory, run, action):
    run = ident(run)
    target = {'use': 'used', 'cancel': 'cancelled'}.get(action)
    if not target:
        raise ValueError('Unknown inventory action.')
    with database(directory) as db:
        row = db.execute('SELECT * FROM reservations WHERE id=?', (run,)).fetchone()
        if not row:
            raise ValueError('Reservation not found.')
        if row['status'] == target:
            return snapshot(db)
        if row['status'] != 'reserved':
            raise ValueError('Only a pending reservation can be changed. Used material is not returned by cancelling.')
        if action == 'use':
            db.execute('UPDATE materials SET stock=stock-? WHERE id=?', (row['length'], row['material']))
        db.execute('UPDATE reservations SET status=?, updated=? WHERE id=?', (target, datetime.now(timezone.utc).isoformat(), run))
        db.execute('UPDATE materials SET revision=revision+1 WHERE id=?', (row['material'],))
        return snapshot(db)


def remove(directory, key, revision):
    """Delete one roll. Outstanding reservations must be released first.

    Finished usage rows for the roll are deleted with it; they only make sense
    against that roll.
    """
    key = ident(key)
    with database(directory) as db:
        row = db.execute('SELECT revision FROM materials WHERE id=?', (key,)).fetchone()
        if not row:
            raise ValueError('This roll was already removed.')
        if type(revision) is not int or revision != row['revision']:
            raise ValueError('This material changed on another screen. Close and reopen Inventory to use the latest stock.')
        if reserved(db, key):
            raise ValueError('Release reserved jobs on this roll before removing it.')
        db.execute('DELETE FROM reservations WHERE material=?', (key,))
        db.execute('DELETE FROM materials WHERE id=?', (key,))
        return snapshot(db)
