"""Shop Connector privacy, parsing, file access, and write-only delivery."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request

import output_credential
import telemetry_sender
from connector import client, readfiles, runtime
from connector.cli import main
from connector.config import ConfigError, RolePaths, load_settings
from connector.events import ENVELOPE, KINDS, SCHEMA, build_event, event_id_for, request_id_for
from connector.parsing import job_hash
from connector.plugins import eznest, inventory, onyx_joblog, summa_joblog
from connector.readfiles import FileContended, complete_lines, open_shared_read, read_bytes
from connector.store import Store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'connector' / 'fixtures'
TOKEN = 'osa_' + 'C' * 43
SECRETS = (
    'FAKE-CUSTOMER-ART.PDF', 'FAKE-JOB-TITLE-ZEBRA', 'jane.doe@example.invalid',
    '555-0148', '123 Fake Street', '$49.95', 'ORDER-88421', 'FAKE-QUICK-SET-NAME',
    'FAKE-GLOSS-PROFILE', 'FAKE-PRINTER-A', '10.9.8.7', '/other/not-a-log.txt',
    'FAKE-CUSTOMER-CUT-ZEBRA', 'FAKE-VINYL-GLOSS', 'FAKE-JOB-SECOND',
    'order@example.invalid', '555-0199', 'FAKE-CHROME-SHEET', 'FAKE-ROLL-ORAJET',
    'FAKE-INV-CUSTOMER', '555-0177', 'inv@example.invalid', '49.95',
    'FAKE-EZ-CUSTOMER', 'FAKE-ART.PDF', 'EZ-999999', 'FAKE-SHOULD-NOT-EXPORT-CREATED',
    'FAKE-PARTIAL-ONYX-LINE', 'FAKE-FILTERED-PRINTER-TITLE', 'FAKE-NOT-A-RECORD',
    'FAKE-ABNORMAL-TITLE', '15234', '0.37', '22.4', '1372', '2480', '4.6', '1.25',
    '720-8c',
)


def public_text(value):
    """Text a receiver can read. Hashes and ids are skipped so digit bands are not confused with them."""
    parts = []

    def walk(item):
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            if len(item) in (32, 36, 64) and all(ch in '0123456789abcdef-' for ch in item):
                return
            parts.append(item)

    walk(value)
    return '\n'.join(parts)


def onyx_line(title, printer='FAKE-PRINTER-A', status='1', epoch='1712345678'):
    return (
        '{{%s,"art.pdf","%s",%s,14000,4800,7,720,"%s","FAKE-GLOSS-PROFILE",'
        '"720-8c",640,"FAKE-QUICK-SET-NAME",1.25,0.8,0.7,1.1,0.4,0.2,0.15,4.6,22.4}}'
        % (status, title, epoch, printer)
    )


class TempCase(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restore_env)
        self.root = Path(self.tmp.name)
        os.environ.pop('EZ_NEST_OUTPUT_UPLOADS', None)
        os.environ.pop('EZ_NEST_OUTPUT_TOKEN', None)
        os.environ.pop('EZ_NEST_OUTPUT_URL', None)
        os.environ['EZ_NEST_CONNECTOR_DATA'] = str(self.root / 'data')
        readfiles.OPENED.clear()

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)

    def store(self):
        return Store(self.root / 'data')

    def write_config(self, plugins):
        path = self.root / 'connector.json'
        path.write_text(json.dumps({'version': 1, 'plugins': plugins}), encoding='utf-8')
        return path


class ParserTests(TempCase):
    def test_summa_columns_match_the_confirmed_order(self):
        self.assertEqual(summa_joblog.DEFAULT_COLUMNS, (
            'date', 'job_name', 'start', 'end', 'material', 'thickness',
            'job_count', 'job_size_x', 'job_size_y', 'copies', 'copy_size_x', 'copy_size_y',
        ))
        example = json.loads((ROOT / 'connector' / 'config.example.json').read_text(encoding='utf-8'))
        for name, body in example['plugins'].items():
            self.assertIs(body['enabled'], False)
        self.assertEqual(tuple(example['plugins']['summa_joblog']['columns']), summa_joblog.DEFAULT_COLUMNS)
        self.assertEqual(example['plugins']['summa_joblog']['delimiter'], ';')

    def test_summa_header_is_skipped_and_columns_can_be_remapped(self):
        store = self.store()
        header = 'Date;Job name;Start time;End time;Material name'
        self.assertIsNone(summa_joblog.parse_line(header, {}, store.salt()))
        line = '28/10/2026;SECRET-NAME;10:00:00;10:04:05;FAKE-VINYL-GLOSS;0.37;23;1372;2480;7;317;189'
        swapped = '28/10/2026;10:00:00;10:04:05;FAKE-VINYL-GLOSS;0.37;23;1372;2480;7;317;189;SECRET-NAME'
        columns = (
            'date', 'start', 'end', 'material', 'thickness', 'job_count',
            'job_size_x', 'job_size_y', 'copies', 'copy_size_x', 'copy_size_y', 'job_name',
        )
        normal = summa_joblog.parse_line(line, {}, store.salt())
        moved = summa_joblog.parse_line(swapped, {'columns': columns}, store.salt())
        self.assertEqual(normal['payload']['jobId'], job_hash(store.salt(), ['SECRET-NAME']))
        self.assertEqual(moved['payload']['jobId'], normal['payload']['jobId'])
        self.assertNotIn('SECRET-NAME', json.dumps(moved))
        self.assertEqual(moved['payload']['durationSecondsBand'], '[240,255)')
        self.assertEqual(tuple(moved['payload']), (
            'materialClass', 'thicknessMmBand', 'jobCountBand', 'copiesBand',
            'jobSizeXMmBand', 'jobSizeYMmBand', 'copySizeXMmBand', 'copySizeYMmBand',
            'durationSecondsBand', 'jobId',
        ))

    def test_onyx_status_printer_class_and_ignored_identity_column(self):
        store = self.store()
        options = {'printers': ['FAKE-PRINTER-A']}
        ok = onyx_joblog.parse_line(onyx_line('Job A'), options, store.salt())
        abnormal = onyx_joblog.parse_line(onyx_line('Job B', status='0', epoch='1712345800'), options, store.salt())
        skipped = onyx_joblog.parse_line(onyx_line('Job C', status='2', epoch='1712345900'), options, store.salt())
        other = onyx_joblog.parse_line(onyx_line('Job D', printer='FAKE-PRINTER-B', epoch='1712346000'), options, store.salt())
        empty = onyx_joblog.parse_line(onyx_line('Job E'), {'printers': []}, store.salt())
        self.assertEqual(ok['payload']['status'], 'ok')
        self.assertEqual(abnormal['payload']['status'], 'abnormal')
        self.assertIsNone(skipped)
        self.assertIsNone(other)
        self.assertIsNone(empty)
        model = onyx_line('Job F', printer='Epson SureColor S80600', epoch='1712346100')
        classified = onyx_joblog.parse_line(model, {'printers': ['Epson SureColor S80600']}, store.salt())
        self.assertEqual(classified['payload']['printerClass'], 'epson_s80600')
        self.assertNotIn('SureColor', json.dumps(classified))
        emailed = (
            '28/10/2026;person@example.invalid;10:00:00;10:01:00;vinyl;0.2;1;100;200;1;50;60'
        )
        parsed = summa_joblog.parse_line(emailed, {'columns': [
            'date', 'email', 'start', 'end', 'material', 'thickness', 'job_count',
            'job_size_x', 'job_size_y', 'copies', 'copy_size_x', 'copy_size_y',
        ]}, store.salt())
        self.assertIsNotNone(parsed)
        self.assertNotIn('person@example.invalid', json.dumps(parsed))
        self.assertNotIn('email', parsed['payload'])

    def test_inventory_ignores_cost_and_emits_only_qty_changes(self):
        store = self.store()
        salt = store.salt()
        rows = [
            {'name': 'FAKE-ROLL-ORAJET', 'category': 'gloss', 'qty_on_hand': 10, 'unit': 'each',
             'reorder_threshold': 4, 'updated_at': '2026-10-28T15:00:00Z', 'cost': 49.95,
             'customer': 'FAKE-INV-CUSTOMER', 'order_id': 'ORDER-1', 'phone': '555-0177'},
            {'name': 'FAKE-ROLL-ORAJET', 'category': 'gloss', 'qty_on_hand': 10, 'unit': 'each',
             'reorder_threshold': 4, 'updated_at': '2026-10-28T15:10:00Z', 'price': '$12'},
            {'name': 'FAKE-ROLL-ORAJET', 'category': 'gloss', 'qty_on_hand': 18, 'unit': 'each',
             'reorder_threshold': 4, 'updated_at': '2026-10-28T16:00:00Z'},
        ]
        seeded = inventory.fold(rows, store, salt, replay=False)
        self.assertEqual(seeded, [])
        self.assertTrue(store.inventory_seeded())
        again = inventory.fold(rows[-1:], store, salt, replay=False)
        self.assertEqual(again, [])
        changed = inventory.fold([{**rows[-1], 'qty_on_hand': 30, 'updated_at': '2026-10-28T17:00:00Z'}], store, salt, replay=False)
        self.assertEqual(len(changed), 1)
        blob = json.dumps([item['payload'] for item in changed])
        self.assertNotIn('FAKE-ROLL-ORAJET', blob)
        self.assertNotIn('49.95', blob)
        self.assertNotIn('FAKE-INV-CUSTOMER', blob)
        self.assertNotIn('ORDER-1', blob)
        self.assertEqual(changed[0]['payload']['source'], 'view')
        self.assertEqual(changed[0]['payload']['unit'], 'each')
        memory = inventory.MemoryQty()
        preview = inventory.fold(rows, memory, salt, replay=True)
        self.assertEqual(len(preview), 1)
        self.assertNotEqual(store.quantity(preview[0]['payload']['materialKey']), None)

    def test_partial_inventory_snapshot_does_not_seed(self):
        self.assertRaises(inventory.PartialView, inventory.load_rows, b'[{"name": "x"')
        rows = inventory.load_rows(FIXTURES.joinpath('inventory.json').read_bytes())
        self.assertEqual(len(rows), 2)
        self.assertNotIn('cost', inventory.pick(rows[0]))


class PrivacyReplayTests(TempCase):
    def test_replay_hides_identity_and_does_not_use_the_network(self):
        store = self.store()
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            events = runtime.replay(FIXTURES, store)
        self.assertEqual(sorted(event['kind'] for event in events), [
            'cut.completed', 'cut.completed', 'inventory.observed', 'nest.completed',
            'print.completed', 'print.completed',
        ])
        raw = json.dumps(events)
        self.assertNotIn(store.salt().hex(), raw)
        blob = public_text(events)
        for secret in SECRETS:
            self.assertNotIn(secret, blob, secret)
        self.assertFalse(any('decoy-not-a-log' in path for path in readfiles.OPENED))
        self.assertFalse(any('evil.example' in path for path in readfiles.OPENED))
        kinds = {event['kind'] for event in events}
        self.assertEqual(kinds, set(KINDS))
        for event in events:
            self.assertEqual(tuple(event), ENVELOPE)
            self.assertEqual(event['schema'], SCHEMA)

    def test_schema_document_matches_the_envelope(self):
        text = (ROOT / 'connector' / 'CONTRACT.md').read_text(encoding='utf-8')
        raw = text.split('```json\n', 1)[1].split('\n```', 1)[0]
        schema = json.loads(raw)
        self.assertEqual(schema['$id'], SCHEMA)
        self.assertEqual(schema['properties']['kind']['enum'], list(KINDS))
        self.assertEqual(schema['required'], list(ENVELOPE))

    def test_idempotent_ids_and_duplicate_lines(self):
        store = self.store()
        line = onyx_line('Same Job').encode()
        first = build_event(store.instance_id(), 'onyx_joblog', line, 'printer', 'print.completed',
                            '2026-10-28T00:00:00Z', onyx_joblog.parse_line(line, {'printers': ['FAKE-PRINTER-A']}, store.salt())['payload'])
        second = build_event(store.instance_id(), 'onyx_joblog', line, 'printer', 'print.completed',
                             '2026-10-28T00:00:00Z', first['payload'])
        self.assertEqual(first['eventId'], second['eventId'])
        self.assertEqual(first['requestId'], second['requestId'])
        self.assertEqual(first['requestId'], request_id_for(store.instance_id(), event_id_for('onyx_joblog', line)))
        options = {'printers': ['FAKE-PRINTER-A']}
        left = onyx_joblog.parse_line(onyx_line('Alpha', epoch='1712345678'), options, store.salt())
        right = onyx_joblog.parse_line(onyx_line('Beta', epoch='1712349999'), options, store.salt())
        self.assertNotEqual(left['payload']['jobId'], right['payload']['jobId'])
        self.assertNotIn('Alpha', json.dumps(left))
        self.assertNotIn('Beta', json.dumps(right))


class FileAccessTests(TempCase):
    def test_shared_read_allows_a_writer_and_is_not_a_write_handle(self):
        path = self.root / 'JobLog.txt'
        path.write_bytes(b'start\n')
        seen = []
        real = os.open

        def spy(file, flags, mode=0o777, *, dir_fd=None):
            seen.append(flags)
            return real(file, flags, mode)

        with patch('os.open', spy):
            with open_shared_read(path) as handle:
                with open(path, 'ab') as writer:
                    writer.write(b'more\n')
                handle.seek(0)
                data = handle.read()
        self.assertIn(b'more\n', data)
        flags = seen[0]
        self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
        for bit in (os.O_WRONLY, os.O_RDWR, os.O_APPEND, os.O_CREAT, getattr(os, 'O_TRUNC', 0)):
            self.assertFalse(flags & bit)
        access, share, _disposition = readfiles.windows_open_arguments()
        self.assertEqual(access, readfiles.GENERIC_READ)
        self.assertFalse(access & readfiles.GENERIC_WRITE)
        self.assertTrue(share & readfiles.FILE_SHARE_READ)
        self.assertTrue(share & readfiles.FILE_SHARE_WRITE)
        self.assertTrue(share & readfiles.FILE_SHARE_DELETE)

    def test_reader_does_not_move_or_truncate_and_falls_back_to_a_copy(self):
        path = self.root / 'JobLog.txt'
        original = b'line-one\nline-two\n'
        path.write_bytes(original)

        def forbid(name):
            def guard(*_args, **_kwargs):
                raise AssertionError(name)
            return guard

        with patch('os.rename', forbid('rename')), patch('os.replace', forbid('replace')), patch('os.truncate', forbid('truncate')):
            self.assertEqual(read_bytes(path, 0, self.root / 'data'), original)
        self.assertEqual(path.read_bytes(), original)
        with patch('connector.readfiles._read_once', side_effect=FileContended('busy')):
            copied = read_bytes(path, 0, self.root / 'data')
        self.assertEqual(copied, original)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list((self.root / 'data').glob('read-*')), [])

    def test_half_written_line_is_not_consumed(self):
        lines, offset = complete_lines(b'full\npartial', 5)
        self.assertEqual(lines, [b'full'])
        self.assertEqual(offset, 10)
        lines, offset = complete_lines(b'partial', 0)
        self.assertEqual(lines, [])
        self.assertEqual(offset, 0)

    def test_future_only_watermark_and_unpaired_lines_are_not_stored(self):
        folder = self.root / 'FAKE-CUSTOMER-DIR'
        folder.mkdir()
        path = folder / 'JobLog.txt'
        path.write_text(onyx_line('OLD-SECRET-TITLE-ZEBRA') + '\n', encoding='utf-8')
        config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': str(path)},
            'printers': ['FAKE-PRINTER-A'],
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        runtime.poll(specs, store, send=False)
        self.assertEqual(store.outbox(), [])
        self.assertNotIn(b'OLD-SECRET-TITLE-ZEBRA', (self.root / 'data' / 'connector.sqlite3').read_bytes())
        path.write_text(path.read_text(encoding='utf-8') + onyx_line('WHILE-UNPAIRED-TITLE', epoch='1712345700') + '\n', encoding='utf-8')
        runtime.poll(specs, store, send=False)
        self.assertEqual(store.outbox(), [])
        blob = (self.root / 'data' / 'connector.sqlite3').read_bytes()
        self.assertNotIn(b'WHILE-UNPAIRED-TITLE', blob)
        self.assertNotIn(b'FAKE-CUSTOMER-DIR', blob)
        output_credential.save(store.directory, TOKEN, 'North Shop')
        path.write_text(path.read_text(encoding='utf-8') + onyx_line('AFTER-PAIR-TITLE', epoch='1712345800') + '\n', encoding='utf-8')
        runtime.poll(specs, store, send=False)
        events = store.outbox()
        self.assertEqual(len(events), 1)
        saved = (self.root / 'data' / 'connector.sqlite3').read_bytes()
        for secret in (b'OLD-SECRET-TITLE-ZEBRA', b'WHILE-UNPAIRED-TITLE', b'AFTER-PAIR-TITLE', b'FAKE-CUSTOMER-DIR', b'art.pdf'):
            self.assertNotIn(secret, saved)

    def test_duplicate_line_is_sent_once(self):
        path = self.root / 'JobLog.txt'
        path.write_bytes(b'')
        config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': str(path)},
            'printers': ['FAKE-PRINTER-A'],
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        output_credential.save(store.directory, TOKEN)
        runtime.poll(specs, store, send=False)
        line = onyx_line('Repeat Job', epoch='1712345678') + '\n'
        path.write_text(line + line, encoding='utf-8')
        runtime.poll(specs, store, send=False)
        events = store.outbox()
        self.assertEqual(len(events), 1)
        runtime.poll(specs, store, send=False)
        self.assertEqual(len(store.outbox()), 1)

    def test_paths_are_config_locked_and_logs_stop_at_two_files(self):
        log = self.root / 'JobLog.txt'
        other = self.root / 'not-a-log.txt'
        third = self.root / 'third.log'
        for path in (log, other, third):
            path.write_text(onyx_line('X') + '\n', encoding='utf-8')
        config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': str(log)},
            'printers': ['FAKE-PRINTER-A'],
        }, 'summa_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': str(self.root / 'Joblog.csv')},
        }})
        (self.root / 'Joblog.csv').write_text('28/10/2026;Name;10:00:00;10:01:00;vinyl;0.2;1;10;20;1;5;6\n', encoding='utf-8')
        specs, _directory = load_settings(config)
        roles = RolePaths((log.resolve(), (self.root / 'Joblog.csv').resolve()), None, None)
        with self.assertRaises(PermissionError):
            roles.open_log(other)
        with self.assertRaises(ConfigError):
            RolePaths((log.resolve(), other.resolve(), third.resolve()), None, None)
        bad = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': 'https://evil.example/JobLog.txt'},
        }})
        with self.assertRaises(ConfigError):
            load_settings(bad)
        unc = self.write_config({'summa_joblog': {
            'enabled': True, 'source': {'type': 'mounted', 'path': '\\\\server\\share\\Joblog.csv'},
        }})
        with self.assertRaises(ConfigError):
            load_settings(unc)
        listed = self.write_config({'onyx_joblog': {'enabled': True, 'paths': [str(log)], 'source': {'type': 'file', 'path': str(log)}}})
        with self.assertRaises(ConfigError):
            load_settings(listed)
        readfiles.OPENED.clear()
        store = self.store()
        log.write_text(onyx_line('Inside') + ',"' + str(other) + '"}}\n', encoding='utf-8')
        # The line above is not a valid record; write a valid line that mentions the other path.
        log.write_text(onyx_line('Inside')[:-2] + ',"' + str(other) + '"}}\n', encoding='utf-8')
        runtime.poll(specs, store, send=False)
        opened = set(readfiles.OPENED)
        self.assertIn(str(log.resolve()), opened)
        self.assertIn(str((self.root / 'Joblog.csv').resolve()), opened)
        self.assertNotIn(str(other.resolve()), opened)
        self.assertNotIn(str(third.resolve()), opened)

    def test_stdin_and_mounted_sources_do_not_open_the_original_log(self):
        original = self.root / 'original.txt'
        original.write_text(onyx_line('ORIGINAL-SECRET') + '\n', encoding='utf-8')
        mounted = self.root / 'mounted.txt'
        mounted.write_text('', encoding='utf-8')
        config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'mounted', 'path': str(mounted)},
            'printers': ['FAKE-PRINTER-A'],
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        output_credential.save(store.directory, TOKEN)
        readfiles.OPENED.clear()
        runtime.poll(specs, store, send=False)
        self.assertNotIn(str(original.resolve()), readfiles.OPENED)
        mounted.write_text(mounted.read_text(encoding='utf-8') + onyx_line('MOUNTED-JOB', epoch='1712346200') + '\n', encoding='utf-8')
        runtime.poll(specs, store, send=False)
        self.assertEqual(len(store.outbox()), 1)
        self.assertNotIn('MOUNTED-JOB', json.dumps(store.outbox()))
        stdin_config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'stdin'}, 'printers': ['FAKE-PRINTER-A'],
        }})
        specs, _directory = load_settings(stdin_config)
        before = len(store.outbox())
        stream = runtime.StdinSource(io.BytesIO((onyx_line('STDIN-OLD-SECRET') + '\n').encode()))
        readfiles.OPENED.clear()
        runtime.poll(specs, store, stdin=stream, send=False)
        self.assertEqual(readfiles.OPENED, [])
        self.assertEqual(len(store.outbox()), before)
        stream.stream = io.BytesIO((onyx_line('STDIN-NEW-JOB', epoch='1712346300') + '\n').encode())
        runtime.poll(specs, store, stdin=stream, send=False)
        self.assertEqual(len(store.outbox()), before + 1)
        titles = json.dumps(store.outbox())
        self.assertNotIn('STDIN-OLD-SECRET', titles)
        self.assertNotIn('STDIN-NEW-JOB', titles)

    def test_status_does_not_open_logs(self):
        path = self.root / 'JobLog.txt'
        path.write_text(onyx_line('STATUS-SECRET') + '\n', encoding='utf-8')
        config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': str(path)},
            'printers': ['FAKE-PRINTER-A'],
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        readfiles.OPENED.clear()
        text = runtime.format_status(specs, store)
        self.assertEqual(readfiles.OPENED, [])
        self.assertNotIn('STATUS-SECRET', text)
        self.assertNotIn(str(path), text)
        self.assertIn('onyx_joblog', text)
        self.assertIn('idle', text)
        self.assertIn('not paired', text)


class InventoryLiveTests(TempCase):
    def test_live_view_seeds_without_sending_history(self):
        path = self.root / 'stock.json'
        path.write_text(FIXTURES.joinpath('inventory.json').read_text(encoding='utf-8'), encoding='utf-8')
        config = self.write_config({'inventory': {
            'enabled': True, 'source': {'type': 'file', 'path': str(path)},
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        output_credential.save(store.directory, TOKEN)
        runtime.poll(specs, store, send=False)
        self.assertEqual(store.outbox(), [])
        self.assertTrue(store.inventory_seeded())
        body = json.loads(path.read_text(encoding='utf-8'))
        body[1]['qty_on_hand'] = 12000
        body[1]['updated_at'] = '2026-10-28T18:00:00Z'
        path.write_text(json.dumps(body), encoding='utf-8')
        runtime.poll(specs, store, send=False)
        events = store.outbox()
        self.assertEqual(len(events), 1)
        blob = json.dumps(events)
        self.assertNotIn('FAKE-ROLL-ORAJET', blob)
        self.assertNotIn('49.95', blob)
        self.assertNotIn('FAKE-INV-CUSTOMER', blob)
        self.assertEqual(events[0]['payload']['quantityBand'], '[12000,12250)')


class EznestReadOnlyTests(TempCase):
    def test_telemetry_is_query_only_and_future_only(self):
        db_path = self.root / 'telemetry.sqlite3'
        db = sqlite3.connect(db_path)
        db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, kind TEXT, occurred_at TEXT, atom TEXT, acknowledged INTEGER)')
        atom = json.loads(FIXTURES.joinpath('eznest_events.jsonl').read_text(encoding='utf-8').splitlines()[0])
        db.execute('INSERT INTO events(id, kind, occurred_at, atom, acknowledged) VALUES(?,?,?,?,0)',
                   (atom['id'], atom['type'], atom['occurredAt'], json.dumps(atom)))
        db.commit()
        db.close()
        opened = eznest.open_database(db_path)
        with self.assertRaises(sqlite3.OperationalError):
            opened.execute('CREATE TABLE hack (id INTEGER)')
        opened.close()
        before = db_path.read_bytes()
        config = self.write_config({'eznest': {
            'enabled': True, 'source': {'type': 'file', 'path': str(self.root)},
            'kinds': ['nest.printed'],
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        output_credential.save(store.directory, TOKEN)
        runtime.poll(specs, store, send=False)
        self.assertEqual(store.outbox(), [])
        self.assertEqual(db_path.read_bytes(), before)
        fresh = json.loads(json.dumps(atom))
        fresh['id'] = 'cd' * 32
        fresh['customer'] = 'FAKE-EZ-CUSTOMER'
        db = sqlite3.connect(db_path)
        db.execute('INSERT INTO events(id, kind, occurred_at, atom, acknowledged) VALUES(?,?,?,?,0)',
                   (fresh['id'], fresh['type'], fresh['occurredAt'], json.dumps(fresh)))
        db.commit()
        db.close()
        runtime.poll(specs, store, send=False)
        events = store.outbox()
        self.assertEqual(len(events), 1)
        blob = json.dumps(events) + (self.root / 'data' / 'connector.sqlite3').read_bytes().decode('utf-8', 'ignore')
        self.assertNotIn('FAKE-EZ-CUSTOMER', blob)
        self.assertNotIn('FAKE-ART.PDF', json.dumps(events))
        self.assertEqual(events[0]['payload']['kind'], 'nest.printed')


class DeliveryTests(TempCase):
    def _event(self):
        store = self.store()
        payload = onyx_joblog.parse_line(onyx_line('Delivery'), {'printers': ['FAKE-PRINTER-A']}, store.salt())['payload']
        return store, build_event(store.instance_id(), 'onyx_joblog', onyx_line('Delivery').encode(),
                                  'printer', 'print.completed', '2024-04-05T19:34:38Z', payload)

    def test_post_is_write_only_and_ignores_urls_in_the_ack(self):
        source = (ROOT / 'connector' / 'client.py').read_text(encoding='utf-8')
        self.assertNotIn("method='GET'", source)
        self.assertNotIn('method="GET"', source)
        _store, event = self._event()
        calls = []

        def transport(url, raw, headers):
            calls.append((url, headers, json.loads(raw)))
            body = {'outcome': 'created', 'result': {
                'schema': SCHEMA, 'requestId': event['requestId'],
                'download': 'https://evil.example/secret', 'path': '/etc/passwd',
            }, 'events': [{'customer': 'hidden'}]}
            return 200, {}, json.dumps(body).encode()

        readfiles.OPENED.clear()
        self.assertTrue(client.deliver(event, TOKEN, transport=transport, sleep=lambda _seconds: None))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith('/api/shop/telemetry'))
        self.assertEqual(calls[0][1]['Authorization'], 'Bearer ' + TOKEN)
        self.assertEqual(readfiles.OPENED, [])
        with patch('connector.client.build_opener') as opener:
            response = Mock()
            response.status = 200
            response.read.return_value = b'{}'
            response.headers = {}
            opener.return_value.open.return_value.__enter__.return_value = response
            client._https_post(client.url_for('event'), b'{}', {})
            self.assertIsInstance(opener.call_args.args[0], telemetry_sender.NoRedirect)
            request = opener.return_value.open.call_args.args[0]
            self.assertIsInstance(request, Request)
            self.assertEqual(request.get_method(), 'POST')
        with self.assertRaises(client.ClientError):
            client.url_for('read')

    def test_retry_is_idempotent_and_honors_retry_after(self):
        _store, event = self._event()
        calls = []

        def transport(url, raw, headers):
            body = json.loads(raw)
            calls.append(body['requestId'])
            if len(calls) == 1:
                return None, {}, b''
            return 200, {}, json.dumps({'outcome': 'replay', 'result': {'schema': SCHEMA, 'requestId': body['requestId']}}).encode()

        sleeps = []
        self.assertTrue(client.deliver(event, TOKEN, transport=transport, sleep=sleeps.append, attempts=3))
        self.assertEqual(calls[0], calls[1])
        self.assertTrue(sleeps)
        limited = []

        def rate(url, raw, headers):
            limited.append(1)
            if len(limited) == 1:
                return 429, {'Retry-After': '3'}, b''
            body = json.loads(raw)
            return 200, {}, json.dumps({'outcome': 'created', 'result': {'schema': SCHEMA, 'requestId': body['requestId']}}).encode()

        waits = []
        self.assertTrue(client.deliver(event, TOKEN, transport=rate, sleep=waits.append, attempts=3))
        self.assertEqual(waits, [3])
        capped = []

        def huge(url, raw, headers):
            capped.append(1)
            if len(capped) == 1:
                return 429, {'Retry-After': '5000'}, b''
            body = json.loads(raw)
            return 200, {}, json.dumps({'outcome': 'created', 'result': {'schema': SCHEMA, 'requestId': body['requestId']}}).encode()

        long_waits = []
        self.assertTrue(client.deliver(event, TOKEN, transport=huge, sleep=long_waits.append, attempts=3))
        self.assertEqual(long_waits, [900])

    def test_redirect_is_not_followed(self):
        _store, event = self._event()
        calls = []

        def transport(url, raw, headers):
            calls.append(url)
            return 302, {'Location': 'https://evil.example/steal'}, b''

        self.assertFalse(client.deliver(event, TOKEN, transport=transport, sleep=lambda _seconds: None))
        self.assertEqual(len(calls), 1)

    def test_pair_stores_the_key_and_disconnect_clears_it(self):
        store = self.store()
        seen = []

        def transport(raw):
            seen.append(json.loads(raw))
            body = {'outcome': 'created', 'result': {'token': TOKEN, 'shopName': 'North Shop'}}
            return 200, json.dumps(body).encode()

        stdout = io.StringIO()
        with patch('sys.stdout', stdout):
            result = client.pair(store.directory, '7k4npqrx2m', transport=transport, host_label='SHOP-PC', host_ref=store.instance_id())
        self.assertEqual(result['shopName'], 'North Shop')
        self.assertNotIn(TOKEN, stdout.getvalue())
        self.assertEqual(seen[0]['code'], '7K4NP-QRX2M')
        self.assertEqual(seen[0]['hostRef'], store.instance_id())
        self.assertEqual(output_credential.load(store.directory), TOKEN)
        target = output_credential.path(store.directory)
        if os.name != 'nt':
            self.assertEqual(target.stat().st_mode & 0o077, 0)
        store.enqueue({'eventId': 'a' * 64, 'schema': SCHEMA}, 'onyx_joblog', '2026-10-28T00:00:00Z')
        # enqueue validates? it stores whatever dict we pass. The row is unsent.
        self.assertEqual(store.clear_outbox(), 1)
        os.environ['EZ_NEST_OUTPUT_UPLOADS'] = '0'
        with self.assertRaises(Exception):
            client.pair(store.directory, '7k4npqrx2m', transport=transport, host_label='SHOP-PC', host_ref=store.instance_id())
        os.environ.pop('EZ_NEST_OUTPUT_UPLOADS')
        stdout = io.StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', io.StringIO()):
            code = main(['disconnect'])
        self.assertEqual(code, 0)
        self.assertIsNone(output_credential.load(store.directory))
        self.assertNotIn(TOKEN, stdout.getvalue())

    def test_replay_send_requires_pairing(self):
        with patch('connector.client._https_post', side_effect=AssertionError('network')):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
                code = main(['replay', '--fixtures', str(FIXTURES)])
            self.assertEqual(code, 0)
            self.assertIn('nothing sent', stderr.getvalue())
            shown = public_text(json.loads(stdout.getvalue()))
            for secret in SECRETS:
                self.assertNotIn(secret, shown, secret)
            with patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()) as err:
                code = main(['replay', '--fixtures', str(FIXTURES), '--send'])
            self.assertEqual(code, 1)
            self.assertIn('Pair this computer', err.getvalue())


if __name__ == '__main__':
    unittest.main()
