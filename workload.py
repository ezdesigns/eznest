"""Local workload signals. No artwork, filenames, customer data or network calls."""
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def connect(data_dir):
    db = sqlite3.connect(Path(data_dir) / 'workload.sqlite3', timeout=2)
    db.execute('''CREATE TABLE IF NOT EXISTS events (
        batch_id TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
        pieces INTEGER NOT NULL, width_mm REAL NOT NULL, length_mm REAL NOT NULL,
        material_m2 REAL NOT NULL, artwork_m2 REAL NOT NULL,
        PRIMARY KEY (batch_id, kind))''')
    return db


def record(data_dir, batch_id, kind, result):
    """One observation per frozen pack and event type, including retries."""
    if kind not in ('prepared', 'sent_to_folder', 'removed_from_folder'):
        raise ValueError('Unknown workload event')
    def number(name):
        value = float(result.get(name, 0))
        if not math.isfinite(value) or value < 0:
            raise ValueError('Invalid workload measurement')
        return value
    width, length, area = number('width'), number('usedLength'), number('area')
    now = datetime.now(timezone.utc)
    db = connect(data_dir)
    try:
        with db:
            db.execute('DELETE FROM events WHERE occurred_at < ?',
                       ((now - timedelta(days=90)).isoformat(),))
            db.execute('INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (batch_id, kind, now.isoformat(), len(result.get('placements', [])),
                        width, length, width * length / 1_000_000, area / 1_000_000))
    finally:
        db.close()


def summary(data_dir):
    """Rolling 24-hour activity, not printer utilization or available capacity."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    db = connect(data_dir)
    try:
        rows = db.execute('''SELECT kind, COUNT(*), SUM(pieces), SUM(length_mm),
                            SUM(material_m2) FROM events WHERE occurred_at >= ?
                            GROUP BY kind''', (since,)).fetchall()
    finally:
        db.close()
    totals = {row[0]: {'packs': row[1], 'pieces': row[2], 'lengthMm': row[3],
                       'materialM2': row[4]} for row in rows}
    return {'localOnly': True, 'windowHours': 24, 'retentionDays': 90, 'events': totals}
