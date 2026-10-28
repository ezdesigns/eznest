"""Local observations and a dormant, injectable atom adapter. No network client.

The proposal schema is NOT Ez Ink's registered shared contract. Exact measurements
stay local; the outbox contains only codes, opaque identifiers and numeric bands.
"""
import hashlib
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app_info import VERSION

SCHEMA = 'eznest.telemetry.proposal.v1'
CODE = re.compile(r'EZ-[0-9]{4,12}')
ID = re.compile(r'[a-f0-9]{32}')
KINDS = ('nest.created', 'nest.waste', 'nest.linked', 'nest.committed',
         'material.allocated', 'nest.queued', 'nest.sent_to_print',
         'nest.exported', 'nest.removed_from_folder', 'nest.printed',
         'nest.cancelled', 'material.stock_recorded')


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Use an opaque 32-character identifier.')
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1e12:
        raise ValueError('Use a finite, nonnegative measurement.')
    return value


def codes(values):
    if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or not CODE.fullmatch(v) for v in values):
        raise ValueError('Job codes must look like EZ-1234; do not send names or filenames.')
    return sorted(set(values))


@contextmanager
def database(directory):
    db = sqlite3.connect(Path(directory) / 'telemetry.sqlite3', timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS nests (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, snapshot TEXT NOT NULL,
                roll_id TEXT, committed INTEGER NOT NULL DEFAULT 0,
                printed_at TEXT, updated_at TEXT NOT NULL,
                context_revision INTEGER NOT NULL DEFAULT 0, printed_sequence INTEGER);
            CREATE TABLE IF NOT EXISTS rolls (
                id TEXT PRIMARY KEY, material_key TEXT NOT NULL, remaining_mm REAL NOT NULL,
                revision INTEGER NOT NULL, measured_at TEXT NOT NULL, reading_sequence INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL, occurred_at TEXT NOT NULL, atom TEXT NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('instance_id', uuid.uuid4().hex))
            yield db
    finally:
        db.close()


def band(value, step):
    if value is None:
        return None
    value = number(value)
    if value == 0:
        return '0'
    lo = math.floor(value / step) * step
    decimal = lambda value: f'{value:.2f}'.rstrip('0').rstrip('.')
    return f'[{decimal(lo)},{decimal(lo + step)})'


def next_sequence(db):
    # A database order, not wall-clock time, reconciles prints with stock readings.
    db.execute("INSERT OR IGNORE INTO metadata VALUES('observation_sequence','0')")
    db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='observation_sequence'")
    return int(db.execute("SELECT value FROM metadata WHERE key='observation_sequence'").fetchone()[0])


def measurements(job, result):
    width = number(result['width'])
    length = number(result['usedLength'])
    area = number(result['area'])
    if width <= 0 or length <= 0 or area > width * length + .01:
        raise ValueError('Telemetry requires a valid finished layout.')
    roll_width = job.get('settings', {}).get('rollWidth')
    if roll_width is not None and number(roll_width) < width:
        raise ValueError('Roll width cannot be smaller than printable width.')
    source_codes = []
    for source in job.get('productionJobs', []):
        for field in ('order', 'code'):
            value = source.get(field)
            if isinstance(value, str) and CODE.fullmatch(value):
                source_codes.append(value)
    material = job.get('webOptions', {}).get('material') or job.get('materialId')
    # Arbitrary preset names/IDs are never stored verbatim in telemetry.
    material_key = hashlib.sha256(str(material).encode()).hexdigest()[:32] if material else None
    material_class = {'white-gloss': 'moto_regular', 'holographic': 'moto_holographic', 'chrome': 'moto_chrome'}.get(material, 'custom' if material else 'unknown')
    return {'jobCodes': codes(source_codes), 'materialKey': material_key, 'materialClass': material_class,
            'printableWidthMm': width, 'rollWidthMm': roll_width, 'lengthMm': length,
            'printableAreaM2': width * length / 1e6,
            'rollAreaM2': roll_width * length / 1e6 if roll_width is not None else None,
            'protectedArtworkAreaM2': area / 1e6,
            'unusedPrintablePercent': max(0, 100 * (1 - area / (width * length))),
            'pieceCount': len(result.get('placements', [])),
            'sheetCount': len(result.get('sheets') or [None]),
            'searchSeconds': number(result['elapsed']) if result.get('elapsed') is not None else None}


def payload(snapshot, roll_id=None):
    return {'jobCodes': snapshot['jobCodes'], 'materialKey': snapshot['materialKey'],
            'materialClass': snapshot['materialClass'],
            'rollId': roll_id,
            'lengthMmBand': band(snapshot['lengthMm'], 250),
            'printableWidthMmBand': band(snapshot['printableWidthMm'], 100),
            'rollWidthMmBand': band(snapshot['rollWidthMm'], 100),
            'printableAreaM2Band': band(snapshot['printableAreaM2'], .25),
            'rollAreaM2Band': band(snapshot['rollAreaM2'], .25),
            'unusedPrintablePercentBand': band(snapshot['unusedPrintablePercent'], 5),
            'pieceCountBand': band(snapshot['pieceCount'], 10),
            'sheetCountBand': band(snapshot['sheetCount'], 5),
            'searchSecondsBand': band(snapshot['searchSeconds'], 15)}


def event(db, identity, kind, nest_id, body):
    if kind not in KINDS:
        raise ValueError('Unknown telemetry event.')
    event_id = hashlib.sha256(f'{identity}:{kind}'.encode()).hexdigest()
    timestamp = now()
    atom = {'schema': SCHEMA, 'id': event_id, 'type': kind, 'source': 'eznest',
            'instanceId': db.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()[0],
            'appVersion': VERSION, 'occurredAt': timestamp, 'nestId': nest_id, 'payload': body}
    db.execute('INSERT OR IGNORE INTO events(id,kind,occurred_at,atom) VALUES(?,?,?,?)',
               (event_id, kind, timestamp, json.dumps(atom)))
    # Keep pending data until delivered; acknowledged observations expire in 90 days.
    db.execute('DELETE FROM events WHERE acknowledged=1 AND occurred_at < ?',
               ((datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),))


def get_nest(db, nest_id):
    row = db.execute('SELECT * FROM nests WHERE id=?', (identifier(nest_id),)).fetchone()
    if row is None:
        raise ValueError('No recorded layout with that ID.')
    return row


def observe(directory, nest_id, job, result, kind='nest.created'):
    """Called after successful app operations; callers isolate tracking failures."""
    identifier(nest_id)
    if kind not in ('nest.created', 'nest.committed', 'nest.exported',
                    'nest.sent_to_print', 'nest.removed_from_folder'):
        raise ValueError('Unknown automatic observation.')
    snapshot = measurements(job, result)
    with database(directory) as db:
        row = db.execute('SELECT * FROM nests WHERE id=?', (nest_id,)).fetchone()
        if row is None:
            db.execute('INSERT INTO nests(id,status,snapshot,updated_at) VALUES(?,?,?,?)',
                       (nest_id, 'nested', json.dumps(snapshot), now()))
            body = payload(snapshot)
            event(db, nest_id, 'nest.created', nest_id, dict(body, evidence='validated_layout'))
            event(db, nest_id, 'nest.waste', nest_id, dict(body, basis='protected_artwork_envelopes', estimate=True))
        row = get_nest(db, nest_id)
        snapshot = json.loads(row['snapshot'])
        body = payload(snapshot, row['roll_id'])
        if kind == 'nest.committed' and not row['committed']:
            db.execute('UPDATE nests SET committed=1,status=?,updated_at=? WHERE id=?', ('prepared', now(), nest_id))
            event(db, nest_id, kind, nest_id, dict(body, evidence='frozen_pack'))
            balance = roll_balance(db, row['roll_id']) if row['roll_id'] else None
            event(db, nest_id, 'material.allocated', nest_id,
                  dict(body, basis='planned_roll_length', consumed=False,
                       reportedRemainingMmBand=band(balance['remaining_mm'], 250) if balance else None,
                       availableAfterAllocationMmBand=band(balance['availableToAllocateMm'], 250) if balance else None,
                       stockKnown=balance is not None))
        elif kind in ('nest.exported', 'nest.sent_to_print', 'nest.removed_from_folder'):
            if not row['committed']:
                raise ValueError('Freeze the layout before recording delivery.')
            evidence = {'nest.exported': 'local_file_saved', 'nest.sent_to_print': 'configured_hot_folder_write',
                        'nest.removed_from_folder': 'explicit_folder_removal'}[kind]
            event(db, nest_id, kind, nest_id, dict(body, evidence=evidence))
            if kind == 'nest.sent_to_print' and row['status'] not in ('printed', 'cancelled'):
                db.execute('UPDATE nests SET status=?,updated_at=? WHERE id=?', ('sent_to_print', now(), nest_id))
            # Folder removal is not proof that a RIP stopped printing; keep allocation.


def link(directory, nest_id, job_codes, roll_id=None):
    """Explicit local connector context, immutable once the pack is committed."""
    job_codes = codes(job_codes)
    if roll_id is not None:
        identifier(roll_id)
    with database(directory) as db:
        row = get_nest(db, nest_id)
        snapshot = json.loads(row['snapshot'])
        if snapshot['jobCodes'] == job_codes and row['roll_id'] == roll_id:
            return
        if row['committed']:
            raise ValueError('Link job codes and a roll before committing the layout.')
        if roll_id:
            roll = db.execute('SELECT * FROM rolls WHERE id=?', (roll_id,)).fetchone()
            if roll is None or roll['material_key'] != snapshot['materialKey']:
                raise ValueError('Choose a recorded roll of the same material.')
        snapshot['jobCodes'] = job_codes
        revision = row['context_revision'] + 1
        db.execute('UPDATE nests SET snapshot=?,roll_id=?,updated_at=?,context_revision=? WHERE id=?',
                   (json.dumps(snapshot), roll_id, now(), revision, nest_id))
        event(db, f'{nest_id}:link:{revision}', 'nest.linked', nest_id, payload(snapshot, roll_id))


def transition(directory, nest_id, action):
    """Explicit confirmation from an operator/connector, never inferred from save."""
    states = {'queue': ('queued', 'nest.queued'), 'printed': ('printed', 'nest.printed'),
              'cancel': ('cancelled', 'nest.cancelled')}
    if action not in states:
        raise ValueError('Choose queue, printed or cancel.')
    target, kind = states[action]
    with database(directory) as db:
        row = get_nest(db, nest_id)
        if row['status'] == target:
            return
        if not row['committed'] or row['status'] in ('printed', 'cancelled'):
            raise ValueError('This layout cannot make that transition.')
        if action == 'queue' and row['status'] != 'prepared':
            raise ValueError('Only a prepared layout can enter the queue.')
        if action == 'printed' and row['status'] not in ('queued', 'sent_to_print'):
            raise ValueError('Queue or send the layout before confirming printing.')
        timestamp = now()
        db.execute('UPDATE nests SET status=?,printed_at=?,updated_at=?,printed_sequence=? WHERE id=?',
                   (target, timestamp if target == 'printed' else None, timestamp,
                    next_sequence(db) if target == 'printed' else None, nest_id))
        event(db, nest_id, kind, nest_id,
              dict(payload(json.loads(row['snapshot']), row['roll_id']), evidence='explicit_confirmation'))


def record_stock(directory, roll_id, material_key, remaining_mm, request_id, expected_revision):
    """Authoritative measured stock; optimistic revision + request ID prevents replay."""
    for value in (roll_id, material_key, request_id):
        identifier(value)
    number(remaining_mm)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('Supply the current roll revision (zero for a new roll).')
    fingerprint = hashlib.sha256(json.dumps([roll_id, material_key, remaining_mm, expected_revision]).encode()).hexdigest()
    with database(directory) as db:
        receipt = db.execute('SELECT fingerprint FROM receipts WHERE id=?', (request_id,)).fetchone()
        if receipt:
            if receipt[0] != fingerprint:
                raise ValueError('That request ID was already used with different stock data.')
            return
        row = db.execute('SELECT * FROM rolls WHERE id=?', (roll_id,)).fetchone()
        if (row['revision'] if row else 0) != expected_revision:
            raise ValueError('Stock changed; read the roll and retry with its new revision.')
        if row and row['material_key'] != material_key:
            raise ValueError('A roll cannot change material identity.')
        timestamp = now()
        db.execute('INSERT OR REPLACE INTO rolls VALUES(?,?,?,?,?,?)',
                   (roll_id, material_key, remaining_mm, expected_revision + 1, timestamp, next_sequence(db)))
        db.execute('INSERT INTO receipts VALUES(?,?)', (request_id, fingerprint))
        event(db, request_id, 'material.stock_recorded', None,
              {'jobCodes': [], 'rollId': roll_id, 'materialKey': material_key,
               'remainingMmBand': band(remaining_mm, 250), 'basis': 'reported_measurement'})


def roll_balance(db, roll_id):
    row = db.execute('SELECT * FROM rolls WHERE id=?', (roll_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown roll.')
    reserved = consumed = 0
    for nest in db.execute('SELECT status,snapshot,printed_sequence FROM nests WHERE roll_id=? AND committed=1', (roll_id,)):
        length = json.loads(nest['snapshot'])['lengthMm']
        if nest['status'] not in ('printed', 'cancelled'):
            reserved += length
        if nest['printed_sequence'] is not None and nest['printed_sequence'] > row['reading_sequence']:
            consumed += length
    estimated = row['remaining_mm'] - consumed
    return dict(row, reservedMm=reserved, confirmedPlannedUseSinceReadingMm=consumed,
                estimatedRemainingMm=max(0, estimated), availableToAllocateMm=max(0, estimated - reserved),
                shortfallMm=max(0, reserved - estimated), estimate=True)


def status(directory):
    with database(directory) as db:
        nests = [dict(r) for r in db.execute('SELECT * FROM nests ORDER BY updated_at DESC LIMIT 100')]
        for nest in nests:
            nest['snapshot'] = json.loads(nest['snapshot'])
        rolls = [roll_balance(db, row[0]) for row in db.execute('SELECT id FROM rolls ORDER BY id')]
        pending = db.execute('SELECT COUNT(*) FROM events WHERE acknowledged=0').fetchone()[0]
        return {'schema': SCHEMA, 'localOnly': True, 'hubConnected': False,
                'pendingEvents': pending, 'nests': nests, 'rolls': rolls,
                'totalNests': db.execute('SELECT COUNT(*) FROM nests').fetchone()[0]}


def pending(directory, limit=100):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Choose a batch size from 1 to 500.')
    with database(directory) as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT atom FROM events WHERE acknowledged=0 ORDER BY seq LIMIT ?', (limit,))]


def dispatch(directory, emit, *, enabled=False, registered_schema=None, limit=100):
    """At-least-once delivery, stable IDs. Receiver must dedupe before acknowledging.

    Not called by the server. Wiring a real hub requires its registered contract,
    an approved translator if different, and separate explicit connection opt-in.
    """
    if not enabled:
        return 0
    if registered_schema != SCHEMA:
        raise ValueError('Register the contract before enabling the adapter.')
    delivered = 0
    for atom in pending(directory, limit):
        # No transaction held while the consumer runs. Failure leaves it pending.
        if emit(atom) is not True:
            break
        with database(directory) as db:
            db.execute('UPDATE events SET acknowledged=1 WHERE id=?', (atom['id'],))
        delivered += 1
    return delivered
