"""Watch plug-ins, keep watermarks, and hand events to the write-only client.

Replay previews fixture lines. It does not move the live watermarks.
A live connect records the end of each log and does not parse older bytes.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from connector import client
from connector.config import PLUGIN_NAMES, roles_for
from connector.events import ContractError, build_event, event_id_for
from connector.plugins import eznest, inventory, onyx_joblog, summa_joblog
from connector.readfiles import READ_WINDOW, complete_lines, file_size, read_bytes

LOG_PARSERS = {'onyx_joblog': onyx_joblog, 'summa_joblog': summa_joblog}
FIXTURE_FILES = ('onyx_joblog.txt', 'summa_joblog.csv', 'inventory.json', 'eznest_events.jsonl')


def now_z():
    return datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')


def poll(specs, store, *, stdin=None, send=False, transport=None, sleep=None, attempts=5, output_host=None):
    """One live pass. History already in a file at connect time is not parsed."""
    roles = roles_for(specs)
    token = client.token_for(store.directory)
    for name in PLUGIN_NAMES:
        spec = specs[name]
        if not spec.enabled:
            continue
        try:
            if _poll_plugin(spec, store, roles, token, stdin):
                store.note(name, last_read_at=now_z(), last_error=None, source_state='connected')
        except PermissionError:
            store.note(name, last_error='blocked', source_state='idle')
        except FileNotFoundError:
            store.note(name, last_error='missing', source_state='idle')
        except OSError:
            store.note(name, last_error='unreadable', source_state='idle')
    if send and token:
        _flush(store, token, transport=transport, sleep=sleep, attempts=attempts, output_host=output_host)
    return store.outbox()


def _poll_plugin(spec, store, roles, token, stdin):
    if spec.name in LOG_PARSERS:
        return _poll_log(spec, store, roles, token, stdin)
    if spec.name == 'inventory':
        return _poll_inventory(spec, store, roles, token)
    if spec.name == 'eznest':
        return _poll_eznest(spec, store, roles, token)
    return False


def _poll_log(spec, store, roles, token, stdin):
    parser = LOG_PARSERS[spec.name]
    if spec.source_type == 'stdin':
        source = stdin
        if source is None:
            store.note(spec.name, last_error='missing', source_state='idle')
            return False
        data, fresh, dropped = source.read_chunk()
        if dropped:
            store.add_dropped(spec.name, dropped)
        if fresh:
            # Connect time: drop whatever is already buffered. Do not parse it.
            return True
        lines, _offset, dropped, _skipping = complete_lines(data, 0)
        if dropped:
            store.add_dropped(spec.name, dropped)
        _accept_lines(spec, parser, lines, store, token)
        return True
    if spec.path is None:
        store.note(spec.name, last_error='missing', source_state='idle')
        return False
    roles.open_log(spec.path).close()
    size, stat = file_size(spec.path)
    cursor = store.tail(spec.name)
    identity = (stat.st_dev, stat.st_ino)
    if cursor is None or (cursor['device'], cursor['inode']) != identity or size < cursor['offset']:
        store.set_tail(spec.name, size, stat.st_dev, stat.st_ino)
        return True
    if size == cursor['offset']:
        return True
    data = read_bytes(spec.path, cursor['offset'], store.directory, READ_WINDOW)
    lines, new_offset, dropped, skipping = complete_lines(
        data, cursor['offset'], skipping=bool(cursor.get('skip_line')),
    )
    store.set_tail(spec.name, new_offset, stat.st_dev, stat.st_ino, skip_line=skipping)
    if dropped:
        store.add_dropped(spec.name, dropped)
    _accept_lines(spec, parser, lines, store, token)
    return True


def _accept_lines(spec, parser, lines, store, token):
    for raw in lines:
        event_id = event_id_for(spec.name, raw)
        if store.seen(event_id):
            continue
        store.mark_seen(event_id, spec.name)
        if not token:
            # Unpaired lines are not stored and will not be sent later.
            continue
        try:
            observation = parser.parse_line(raw, spec.options, store.salt())
        except (TypeError, ValueError):
            observation = None
        if observation is None:
            continue
        _enqueue(store, spec.name, raw, observation)


def _poll_inventory(spec, store, roles, token):
    if spec.path is None:
        store.note(spec.name, last_error='missing', source_state='idle')
        return False
    roles.open_view(spec.path).close()
    try:
        data = read_bytes(spec.path, 0, store.directory, READ_WINDOW + 1)
        if len(data) > READ_WINDOW:
            store.add_dropped(spec.name, 1)
            store.note(spec.name, last_error='oversize', source_state='idle')
            return False
        rows = inventory.load_rows(data)
    except inventory.PartialView:
        store.note(spec.name, last_error='partial', source_state='idle')
        return False
    observations = inventory.fold(rows, store, store.salt(), replay=False)
    if token:
        for observation in observations:
            line = observation.get('line') or b''
            _enqueue(store, spec.name, line, observation)
    return True


def _poll_eznest(spec, store, roles, token):
    path = roles.telemetry_file()
    if path is None or not path.is_file():
        store.note(spec.name, last_error='missing', source_state='idle')
        return False
    try:
        db = eznest.open_database(path)
    except sqlite3.Error:
        store.note(spec.name, last_error='unreadable', source_state='idle')
        return False
    try:
        cursor = store.tail(spec.name)
        if cursor is None:
            store.set_tail(spec.name, eznest.max_sequence(db), 0, 0)
            return True
        rows = eznest.rows_after(db, cursor['offset'])
    except sqlite3.Error:
        store.note(spec.name, last_error='unreadable', source_state='idle')
        return False
    finally:
        db.close()
    last = cursor['offset']
    for row in rows:
        last = int(row['seq'])
        atom = eznest.load_atom(row['atom'])
        observation = eznest.parse_atom(atom, spec.options) if atom else None
        if observation is None:
            continue
        line = observation['line']
        event_id = event_id_for(spec.name, line)
        if store.seen(event_id):
            continue
        store.mark_seen(event_id, spec.name)
        if token:
            _enqueue(store, spec.name, line, observation)
    store.set_tail(spec.name, last, 0, 0)
    return True


def _enqueue(store, plugin, line, observation):
    try:
        event = build_event(
            store.instance_id(), plugin, line, observation['source'], observation['kind'],
            observation['occurredAt'], observation['payload'],
        )
    except ContractError:
        store.note(plugin, last_error='withheld')
        return
    store.enqueue(event, plugin, event['occurredAt'])
    store.note(plugin, last_event_at=event['occurredAt'])


def _flush(store, token, *, transport, sleep, attempts, output_host=None):
    pending = store.outbox()
    if not pending or not token:
        return 0
    kwargs = {'transport': transport, 'attempts': attempts, 'output_host': output_host}
    if sleep is not None:
        kwargs['sleep'] = sleep
    sent_ids = []
    count = 0
    for event in pending[:20]:
        if client.deliver(event, token, **kwargs) is not True:
            break
        sent_ids.append(event['eventId'])
        count += 1
    for event_id in sent_ids:
        store.drop_outbox(event_id)
    return count


def replay(fixtures, store, options=None):
    """Parse synthetic fixtures from the start and return the events. No network."""
    root = Path(fixtures).resolve()
    spec = {}
    replay_path = root / 'replay.json'
    if replay_path.is_file():
        loaded = json.loads(replay_path.read_text(encoding='utf-8'))
        if isinstance(loaded, dict):
            for key in ('printers', 'eznestKinds', 'columns', 'delimiter', 'dateOrder', 'sizeUnit'):
                if key in loaded:
                    spec[key] = loaded[key]
    if options:
        spec.update(options)
    onyx_options = {
        'printers': spec.get('printers') or [],
        'columns': spec.get('onyxColumns') or spec.get('columns'),
        'delimiter': spec.get('onyxDelimiter') or ',',
    }
    summa_options = {
        'columns': spec.get('summaColumns'),
        'delimiter': spec.get('delimiter') or ';',
        'dateOrder': spec.get('dateOrder') or 'dmy',
        'sizeUnit': spec.get('sizeUnit') or 'mm',
    }
    eznest_options = {'kinds': spec.get('eznestKinds') or ['nest.printed']}
    events = []
    seen = set()
    salt = store.salt()
    instance = store.instance_id()
    _replay_lines(root / 'onyx_joblog.txt', 'onyx_joblog', onyx_joblog, onyx_options, salt, instance, seen, events)
    _replay_lines(root / 'summa_joblog.csv', 'summa_joblog', summa_joblog, summa_options, salt, instance, seen, events)
    _replay_inventory(root / 'inventory.json', salt, instance, seen, events)
    _replay_eznest(root / 'eznest_events.jsonl', eznest_options, instance, seen, events)
    return events


def _fixture(root, name):
    path = (root / name).resolve()
    if path.parent != root.resolve():
        raise PermissionError('Replay only opens files inside the fixture folder.')
    if name not in FIXTURE_FILES and name != 'replay.json':
        raise PermissionError('Replay does not open that file.')
    return path


def _replay_lines(path, plugin, parser, options, salt, instance, seen, events):
    if not path.is_file():
        return
    _fixture(path.parent, path.name)
    data = read_bytes(path, 0, path.parent, READ_WINDOW)
    lines, _offset, _dropped, _skipping = complete_lines(data, 0)
    for raw in lines:
        event_id = event_id_for(plugin, raw)
        if event_id in seen:
            continue
        seen.add(event_id)
        observation = parser.parse_line(raw, options, salt)
        if observation is None:
            continue
        try:
            events.append(build_event(
                instance, plugin, raw, observation['source'], observation['kind'],
                observation['occurredAt'], observation['payload'],
            ))
        except ContractError:
            continue


def _replay_inventory(path, salt, instance, seen, events):
    if not path.is_file():
        return
    _fixture(path.parent, path.name)
    data = read_bytes(path, 0, path.parent, READ_WINDOW + 1)
    if len(data) > READ_WINDOW:
        return
    try:
        rows = inventory.load_rows(data)
    except inventory.PartialView:
        return
    state = inventory.MemoryQty()
    for observation in inventory.fold(rows, state, salt, replay=True):
        line = observation.get('line') or b''
        event_id = event_id_for('inventory', line)
        if event_id in seen:
            continue
        seen.add(event_id)
        try:
            events.append(build_event(
                instance, 'inventory', line, observation['source'], observation['kind'],
                observation['occurredAt'], observation['payload'],
            ))
        except ContractError:
            continue


def _replay_eznest(path, options, instance, seen, events):
    if not path.is_file():
        return
    _fixture(path.parent, path.name)
    data = read_bytes(path, 0, path.parent, READ_WINDOW)
    lines, _offset, _dropped, _skipping = complete_lines(data, 0)
    for raw in lines:
        event_id = event_id_for('eznest', raw)
        if event_id in seen:
            continue
        seen.add(event_id)
        try:
            atom = json.loads(raw)
        except ValueError:
            continue
        observation = eznest.parse_atom(atom, options)
        if observation is None:
            continue
        try:
            events.append(build_event(
                instance, 'eznest', observation['line'], observation['source'], observation['kind'],
                observation['occurredAt'], observation['payload'],
            ))
        except ContractError:
            continue


def status_snapshot(specs, store):
    paired = client.token_for(store.directory) is not None
    rows = []
    for name in PLUGIN_NAMES:
        spec = specs[name]
        saved = store.status_row(name) or {}
        if not spec.enabled:
            label = 'disabled'
        elif saved.get('source_state') == 'connected' and not saved.get('last_error'):
            label = 'connected'
        elif spec.source_type == 'stdin' and spec.enabled:
            label = 'idle'
        elif spec.path is not None and Path(spec.path).exists() and saved.get('last_read_at') and not saved.get('last_error'):
            label = 'connected'
        else:
            label = 'idle'
        rows.append({
            'plugin': name,
            'state': label,
            'lastEventAt': saved.get('last_event_at'),
        })
    return {'paired': paired, 'plugins': rows}


def format_status(specs, store, output_host=None):
    snap = status_snapshot(specs, store)
    lines = [
        'Shop Connector 0.1.0',
        'OUTPUT: ' + ('paired' if snap['paired'] else 'not paired'),
        'Delivery: write-only POST ' + client.url_for('event', output_host),
        '',
    ]
    for row in snap['plugins']:
        when = row['lastEventAt'] or '—'
        dropped = ''
        saved = store.status_row(row['plugin']) or {}
        count = int(saved.get('dropped') or 0)
        if count:
            dropped = f' ({count} oversize lines dropped)'
        lines.append(f"{row['plugin']:<16} {row['state']:<12} last event {when}{dropped}")
    return '\n'.join(lines)


class StdinSource:
    """Lines from a stream. The first read is the connect-time discard."""

    def __init__(self, stream):
        self.stream = stream
        self.connected = False
        self.pending = b''
        self.skipping = False

    def read_chunk(self):
        chunk = self.stream.read(READ_WINDOW)
        if chunk:
            self.pending += chunk
        if not self.connected:
            self.connected = True
            self.pending = b''
            self.skipping = False
            return b'', True, 0
        data = self.pending
        lines, offset, dropped, self.skipping = complete_lines(data, 0, skipping=self.skipping)
        self.pending = data[offset:]
        payload = b''.join(line + b'\n' for line in lines)
        return payload, False, dropped
