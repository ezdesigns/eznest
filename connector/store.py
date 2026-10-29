"""Connector state. Raw log lines, paths, and the salt are not event fields.

The salt lives only in this database. The database mode is private on POSIX.
"""
import json
import os
import secrets
import sqlite3
import uuid
from pathlib import Path


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            os.chmod(self.directory, 0o700)
        self.path = self.directory / 'connector.sqlite3'
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tails (
                    plugin TEXT PRIMARY KEY, offset INTEGER NOT NULL,
                    device INTEGER, inode INTEGER, ready INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS seen (event_id TEXT PRIMARY KEY, plugin TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    event_id TEXT PRIMARY KEY, plugin TEXT NOT NULL,
                    body TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS qty (
                    material_key TEXT PRIMARY KEY, quantity TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plugin_status (
                    name TEXT PRIMARY KEY, last_event_at TEXT, last_read_at TEXT,
                    last_error TEXT, source_state TEXT);
                CREATE TABLE IF NOT EXISTS inventory_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1), seeded INTEGER NOT NULL);
            ''')
            db.execute("INSERT OR IGNORE INTO meta VALUES('instance_id', ?)", (uuid.uuid4().hex,))
            db.execute("INSERT OR IGNORE INTO meta VALUES('salt', ?)", (secrets.token_hex(32),))
            db.execute('INSERT OR IGNORE INTO inventory_meta VALUES(1, 0)')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        if os.name != 'nt' and self.path.exists():
            os.chmod(self.path, 0o600)
        return _Closing(db, self.path)

    def instance_id(self):
        with self._connect() as db:
            return db.execute("SELECT value FROM meta WHERE key='instance_id'").fetchone()[0]

    def salt(self):
        with self._connect() as db:
            return bytes.fromhex(db.execute("SELECT value FROM meta WHERE key='salt'").fetchone()[0])

    def tail(self, plugin):
        with self._connect() as db:
            row = db.execute('SELECT * FROM tails WHERE plugin=?', (plugin,)).fetchone()
            return None if row is None else dict(row)

    def set_tail(self, plugin, offset, device, inode):
        with self._connect() as db:
            db.execute(
                'INSERT OR REPLACE INTO tails VALUES(?,?,?,?,1)',
                (plugin, int(offset), None if device is None else int(device), None if inode is None else int(inode)),
            )

    def seen(self, event_id):
        with self._connect() as db:
            return db.execute('SELECT 1 FROM seen WHERE event_id=?', (event_id,)).fetchone() is not None

    def mark_seen(self, event_id, plugin):
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO seen VALUES(?,?)', (event_id, plugin))

    def enqueue(self, event, plugin, created_at):
        with self._connect() as db:
            db.execute(
                'INSERT OR IGNORE INTO outbox VALUES(?,?,?,?)',
                (event['eventId'], plugin, json.dumps(event, separators=(',', ':')), created_at),
            )

    def outbox(self, limit=20):
        with self._connect() as db:
            rows = db.execute('SELECT body FROM outbox ORDER BY created_at, event_id LIMIT ?', (int(limit),)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def drop_outbox(self, event_id):
        with self._connect() as db:
            db.execute('DELETE FROM outbox WHERE event_id=?', (event_id,))

    def clear_outbox(self):
        with self._connect() as db:
            count = db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
            db.execute('DELETE FROM outbox')
            return count

    def note(self, plugin, *, last_event_at=None, last_read_at=None, last_error=None, source_state=None):
        with self._connect() as db:
            row = db.execute('SELECT * FROM plugin_status WHERE name=?', (plugin,)).fetchone()
            current = dict(row) if row else {
                'last_event_at': None, 'last_read_at': None, 'last_error': None, 'source_state': None,
            }
            if last_event_at is not None:
                current['last_event_at'] = last_event_at
            if last_read_at is not None:
                current['last_read_at'] = last_read_at
            current['last_error'] = last_error
            if source_state is not None:
                current['source_state'] = source_state
            db.execute(
                'INSERT OR REPLACE INTO plugin_status VALUES(?,?,?,?,?)',
                (plugin, current['last_event_at'], current['last_read_at'], current['last_error'], current['source_state']),
            )

    def status_row(self, plugin):
        with self._connect() as db:
            row = db.execute('SELECT * FROM plugin_status WHERE name=?', (plugin,)).fetchone()
            return None if row is None else dict(row)

    def quantity(self, material_key):
        with self._connect() as db:
            row = db.execute('SELECT quantity FROM qty WHERE material_key=?', (material_key,)).fetchone()
            return None if row is None else row[0]

    def set_quantity(self, material_key, quantity):
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO qty VALUES(?,?)', (material_key, quantity))

    def inventory_seeded(self):
        with self._connect() as db:
            return db.execute('SELECT seeded FROM inventory_meta WHERE id=1').fetchone()[0] == 1

    def set_inventory_seeded(self):
        with self._connect() as db:
            db.execute('UPDATE inventory_meta SET seeded=1 WHERE id=1')


class _Closing:
    def __init__(self, db, path):
        self.db = db
        self.path = path

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        self.db.close()
        if os.name != 'nt':
            os.chmod(self.path, 0o600)
        return False
