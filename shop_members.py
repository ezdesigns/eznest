"""One local shop, single-use invitations and revocable browser membership.

Inventory remains in material_inventory's existing database. This is not a cloud
account service. Only the loopback host may manage membership (enforced by HTTP).
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid

DB = 'shop-members.sqlite3'
INVITE_SECONDS = 15 * 60
# Remember this browser for a year, renewed when the person opens Ez Nest.
# The host can still revoke access immediately; expired sessions stay expired.
SESSION_SECONDS = 365 * 24 * 60 * 60
SOURCE_ATTEMPTS = 10
SHARED_ATTEMPTS = 200
COOKIE = 'eznest_member'
RECOVERY_COOKIE = 'eznest_reconnect'
RECOVERY_SECONDS = 15 * 60


@contextmanager
def database(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path / DB, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS shop (singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS members (id TEXT PRIMARY KEY, name TEXT NOT NULL, joined REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS invites (hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, member TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (source TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery (id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL, member TEXT);
            CREATE TABLE IF NOT EXISTS recovery_attempts (source TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
        ''')
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def clean_name(value):
    if not isinstance(value, str):
        raise ValueError('Enter a name between 1 and 80 characters.')
    name = ' '.join(unicodedata.normalize('NFKC', value).split())
    if not 1 <= len(name) <= 80 or any(unicodedata.category(c).startswith('C') for c in name):
        raise ValueError('Enter a name between 1 and 80 characters.')
    return name


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def status(directory, admin=False, include_members=False):
    if not (Path(directory) / DB).exists():
        return {'created': False}
    with database(directory) as db:
        row = db.execute('SELECT id,name FROM shop').fetchone()
        if not row:
            return {'created': False}
        result = {'created': True, **dict(row)}
        if admin:
            result['members'] = [dict(item) for item in db.execute('SELECT id,name,joined FROM members ORDER BY joined')]
            result['accessRequests'] = [dict(item) for item in db.execute(
                "SELECT id,name,source FROM recovery WHERE state='pending' AND expires>? ORDER BY expires", (time.time(),))]
        elif include_members:
            result['members'] = [dict(item) for item in db.execute('SELECT name FROM members ORDER BY joined')]
        return result


def configured(directory):
    return status(directory).get('created') is True


def create(directory, name):
    name = clean_name(name)
    with database(directory) as db:
        if db.execute('SELECT 1 FROM shop').fetchone():
            raise ValueError('This PC already hosts a shop. Its inventory has not changed.')
        db.execute('INSERT INTO shop VALUES (1,?,?)', (uuid.uuid4().hex, name))
    return status(directory, admin=True)


def invite(directory, now=None):
    now = time.time() if now is None else now
    # 80 bits, grouped for typing. Only the digest is persisted.
    raw = secrets.token_hex(10).upper()
    with database(directory) as db:
        if not db.execute('SELECT 1 FROM shop').fetchone():
            raise ValueError('Create your shop first.')
        db.execute('DELETE FROM invites WHERE expires <= ?', (now,))
        if db.execute('SELECT COUNT(*) FROM invites').fetchone()[0] >= 20:
            raise ValueError('Too many active invitations. Cancel them or wait 15 minutes.')
        db.execute('INSERT INTO invites VALUES (?,?)', (digest(raw), now + INVITE_SECONDS))
    return {'code': '-'.join(raw[i:i+5] for i in range(0, 20, 5)), 'expiresIn': INVITE_SECONDS}


def join(directory, code, name, source, now=None):
    now = time.time() if now is None else now
    name = clean_name(name)
    raw = code.replace('-', '').strip().upper() if isinstance(code, str) else ''
    if not re.fullmatch('[0-9A-F]{20}', raw):
        raw = ''
    with database(directory) as db:
        db.execute('DELETE FROM attempts WHERE expires <= ?', (now,))
        db.execute('DELETE FROM sessions WHERE expires <= ?', (now,))
        # Each address has its own limit. The shared count records failed
        # attempts after the invitation is checked, so a matching invitation
        # is still accepted.
        source_key = digest(str(source))
        source_row = db.execute('SELECT count FROM attempts WHERE source=?', (source_key,)).fetchone()
        if source_row and source_row['count'] >= SOURCE_ATTEMPTS:
            return {'error': 'Too many attempts. Wait 15 minutes and ask for a new invitation.', 'status': 429}
        row = db.execute('SELECT hash FROM invites WHERE hash=? AND expires>?', (digest(raw), now)).fetchone()
        if not row:
            shared = db.execute('SELECT count FROM attempts WHERE source=?', ('global',)).fetchone()
            if shared and shared['count'] >= SHARED_ATTEMPTS:
                return {'error': 'Too many attempts. Wait 15 minutes and ask for a new invitation.', 'status': 429}
            expires = now + INVITE_SECONDS
            db.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(source) DO UPDATE SET count=count+1', (source_key, expires))
            db.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(source) DO UPDATE SET count=count+1', ('global', expires))
            return {'error': 'That invitation is invalid, expired, or already used.', 'status': 401}
        if db.execute('SELECT COUNT(*) FROM members').fetchone()[0] >= 100:
            return {'error': 'The shop has 100 members. Ask the host to remove unused access.', 'status': 409}
        member = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM invites WHERE hash=?', (row['hash'],))
        db.execute('INSERT INTO members VALUES (?,?,?)', (member, name, now))
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), member, now + SESSION_SECONDS))
        db.execute('DELETE FROM attempts WHERE source=?', (source_key,))
        return {'token': token, 'member': {'id': member, 'name': name}}


def member(directory, token, now=None, *, renew=False):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token) or not (Path(directory) / DB).exists():
        return None
    now = time.time() if now is None else now
    with database(directory) as db:
        row = db.execute('SELECT m.id,m.name FROM sessions s JOIN members m ON m.id=s.member WHERE s.hash=? AND s.expires>?', (digest(token), now)).fetchone()
        if row and renew:
            db.execute('UPDATE sessions SET expires=? WHERE hash=?', (now + SESSION_SECONDS, digest(token)))
        return dict(row) if row else None


def revoke(directory, member_id):
    if not isinstance(member_id, str) or not re.fullmatch('[0-9a-f]{32}', member_id):
        raise ValueError('Choose a shop member.')
    with database(directory) as db:
        db.execute('DELETE FROM sessions WHERE member=?', (member_id,))
        db.execute('DELETE FROM recovery WHERE member=?', (member_id,))
        db.execute('DELETE FROM members WHERE id=?', (member_id,))
    return status(directory, admin=True)


def cancel_invites(directory):
    with database(directory) as db:
        db.execute('DELETE FROM invites')
    return {'ok': True}


def logout(directory, token):
    if not token or not (Path(directory) / DB).exists():
        return
    with database(directory) as db:
        db.execute('DELETE FROM sessions WHERE hash=?', (digest(token),))


def cookie(token, secure=False):
    age = SESSION_SECONDS if token else 0
    return f'{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}' + ('; Secure' if secure else '')


def recovery_cookie(token, secure=False):
    age = RECOVERY_SECONDS if token else 0
    return f'{RECOVERY_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}' + ('; Secure' if secure else '')


def cancel_recovery(directory, proof):
    if isinstance(proof, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', proof) and (Path(directory) / DB).exists():
        with database(directory) as db:
            db.execute('DELETE FROM recovery WHERE hash=?', (digest(proof),))


def recovery_state(directory, proof, now=None):
    if not isinstance(proof, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', proof) or not (Path(directory) / DB).exists():
        return None
    now = time.time() if now is None else now
    with database(directory) as db:
        row = db.execute('SELECT state FROM recovery WHERE hash=? AND expires>?', (digest(proof), now)).fetchone()
        return row['state'] if row else None


def request_recovery(directory, name, source, proof=None, now=None):
    """Request host approval, without disclosing whether the claimed name exists.

    The browser proof is HttpOnly and only its digest is stored. A name or IP
    never authenticates a person; the host explicitly selects an existing member.
    """
    now = time.time() if now is None else now
    name = clean_name(name)
    with database(directory) as db:
        if not db.execute('SELECT 1 FROM shop').fetchone():
            raise ValueError('Create the shop first.')
        db.execute('DELETE FROM recovery WHERE expires<=?', (now,))
        db.execute('DELETE FROM recovery_attempts WHERE expires<=?', (now,))
        if isinstance(proof, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', proof):
            row = db.execute('SELECT state FROM recovery WHERE hash=?', (digest(proof),)).fetchone()
            if row and row['state'] in ('pending', 'approved'):
                return {'proof': proof, 'state': row['state']}
        source = str(source)
        key = digest(source)
        attempt = db.execute('SELECT count FROM recovery_attempts WHERE source=?', (key,)).fetchone()
        if (attempt and attempt['count'] >= 3) or db.execute('SELECT COUNT(*) FROM recovery').fetchone()[0] >= 20:
            return {'error': 'Too many access requests. Wait 15 minutes and try again.', 'status': 429}
        db.execute('INSERT INTO recovery_attempts VALUES (?,1,?) ON CONFLICT(source) DO UPDATE SET count=count+1', (key, now + RECOVERY_SECONDS))
        proof = secrets.token_urlsafe(32)
        db.execute('INSERT INTO recovery VALUES (?,?,?,?,?,?,NULL)',
                   (uuid.uuid4().hex, digest(proof), name, source, now + RECOVERY_SECONDS, 'pending'))
        return {'proof': proof, 'state': 'pending'}


def decide_recovery(directory, request_id, member_id=None, now=None):
    """Only the host HTTP route may call this. None denies the request."""
    now = time.time() if now is None else now
    if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id):
        raise ValueError('Choose an access request.')
    if member_id is not None and (not isinstance(member_id, str) or not re.fullmatch('[0-9a-f]{32}', member_id)):
        raise ValueError('Choose an existing shop member.')
    with database(directory) as db:
        row = db.execute("SELECT id FROM recovery WHERE id=? AND expires>? AND state='pending'", (request_id, now)).fetchone()
        if not row:
            raise ValueError('This access request has expired or was already handled.')
        if member_id is not None and not db.execute('SELECT 1 FROM members WHERE id=?', (member_id,)).fetchone():
            raise ValueError('Choose an existing shop member.')
        db.execute('UPDATE recovery SET state=?, member=? WHERE id=?',
                   ('approved' if member_id is not None else 'denied', member_id, request_id))
    return {'ok': True}


def finish_recovery(directory, proof, now=None):
    now = time.time() if now is None else now
    if not isinstance(proof, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', proof):
        return {'state': 'expired'}
    with database(directory) as db:
        row = db.execute('SELECT * FROM recovery WHERE hash=? AND expires>?', (digest(proof), now)).fetchone()
        if not row:
            return {'state': 'expired'}
        if row['state'] != 'approved':
            return {'state': row['state']}
        person = db.execute('SELECT id,name FROM members WHERE id=?', (row['member'],)).fetchone()
        db.execute('DELETE FROM recovery WHERE id=?', (row['id'],))
        if not person:
            return {'state': 'expired'}
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), person['id'], now + SESSION_SECONDS))
        return {'state': 'restored', 'token': token, 'member': dict(person)}
