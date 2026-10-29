"""Shop Connector privacy, parsing, file access, and write-only delivery."""
import opt_out
import io
import json
import os
import sqlite3
import subprocess
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
from connector.readfiles import READ_WINDOW, FileContended, complete_lines, open_shared_read, read_bytes
from connector.store import Store, windows_acl_commands

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
    '720-8c', 'SYNTH_CUSTOMER_A.PDF', 'SYNTH_CUSTOMER_B.PDF', 'SYNTH_CUSTOMER_C.PDF',
    'SYNTH_CUSTOMER_D.PDF', 'SYNTH_CUSTOMER_E.PDF', 'Synthetic Title A',
    'Synthetic Title B', 'Synthetic Title C', 'Synthetic Title D', 'Synthetic Title E',
    'SYNTH_QUICKSET_A', 'SYNTH_QUICKSET_B', 'SYNTH_QUICKSET_C', 'SYNTH_QUICKSET_D',
    'SYNTH_QUICKSET_E', 'IJ35-10(Graphic Film White) [3M]',
    '8150 Clear with White-CT_18 Pass [3M]', 'Moto Holo Sticker', 'Chrome Mirror 3',
    'Mystery Paper', '720@720x1440-CT', 'EPSON SureColor S80600',
    'Roland VersaCAMM VS-540', 'HP Latex 570', 'Epson Stylus Pro 7890',
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


def onyx_line(title, printer='FAKE-PRINTER-A', status='1', epoch='1712345678',
              feed_px='14400', across_px='7200', dpi='720', copies='1',
              filename='secret.pdf', quick='SYNTH_QUICKSET_X'):
    """One invented Thrive record: quoted fields, spaces, at least 20 of them."""
    fields = [
        status, filename, title, epoch, '1', feed_px, across_px, feed_px, '1',
        copies, dpi, dpi, '0', printer, 'plain vinyl', 'mode', '00:01:00', quick,
        'K: 0.10 C: 0.10', '0.20 ml', '10%',
    ]
    return '{{ ' + ' '.join('"%s"' % field for field in fields) + ' }}'


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
            'print.completed', 'print.completed', 'print.completed', 'print.completed',
            'print.completed',
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
        salt = store.salt()
        first = build_event(store.instance_id(), 'onyx_joblog', line, 'printer', 'print.completed',
                            '2026-10-28T00:00:00Z', onyx_joblog.parse_line(line, {'printers': ['FAKE-PRINTER-A']}, salt)['payload'], salt)
        second = build_event(store.instance_id(), 'onyx_joblog', line, 'printer', 'print.completed',
                             '2026-10-28T00:00:00Z', first['payload'], salt)
        self.assertEqual(first['eventId'], second['eventId'])
        self.assertEqual(first['requestId'], second['requestId'])
        self.assertEqual(first['requestId'], request_id_for(store.instance_id(), event_id_for('onyx_joblog', line, salt)))
        other = Store(self.root / 'other-install')
        self.assertNotEqual(first['eventId'], event_id_for('onyx_joblog', line, other.salt()))
        import hashlib
        plain = hashlib.sha256(b'onyx_joblog\n' + line).hexdigest()
        self.assertNotEqual(first['eventId'], plain)
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
                self.assertFalse(handle.writable())
                with self.assertRaises(OSError):
                    handle.write(b'forbidden')
                with open(path, 'ab') as writer:
                    writer.write(b'more\n')
                handle.seek(0)
                data = handle.read()
        self.assertIn(b'more\n', data)
        if os.name != 'nt':  # Windows opens via CreateFileW, not os.open.
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
        lines, offset, dropped, skipping = complete_lines(b'full\npartial', 5)
        self.assertEqual(lines, [b'full'])
        self.assertEqual(offset, 10)
        self.assertEqual(dropped, 0)
        self.assertFalse(skipping)
        lines, offset, dropped, skipping = complete_lines(b'partial', 0)
        self.assertEqual(lines, [])
        self.assertEqual(offset, 0)
        self.assertFalse(skipping)

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


class OnyxJobLogTests(TempCase):
    PRINTERS = [
        'EPSON SureColor S80600', 'Roland VersaCAMM VS-540', 'HP Latex 570',
        'Epson Stylus Pro 7890',
    ]

    def test_synthetic_fixture_hides_names_and_collapses_the_duplicate(self):
        store = self.store()
        lines = [line for line in FIXTURES.joinpath('onyx_joblog.txt').read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], lines[-1])
        options = {'printers': self.PRINTERS}
        parsed = [onyx_joblog.parse_line(line, options, store.salt()) for line in lines]
        self.assertTrue(all(item is not None for item in parsed))
        self.assertEqual(parsed[0]['payload']['status'], 'ok')
        self.assertEqual(parsed[0]['payload']['onyxStatus'], '1')
        self.assertEqual(parsed[1]['payload']['status'], 'abnormal')
        self.assertEqual(parsed[1]['payload']['onyxStatus'], '-1')
        self.assertEqual(parsed[2]['payload']['status'], 'abnormal')
        self.assertEqual(parsed[2]['payload']['onyxStatus'], '0')
        self.assertEqual(
            [item['payload']['machineModel'] for item in parsed[:5]],
            ['epson_s80600', 'epson_s80600', 'roland_vs540', 'hp_latex_570', 'epson_7890'],
        )
        self.assertEqual(parsed[0]['payload']['widthIn'], '50.50')
        self.assertFalse(parsed[0]['payload']['axisSwapped'])
        first_id = event_id_for('onyx_joblog', lines[0].encode(), store.salt())
        self.assertEqual(first_id, event_id_for('onyx_joblog', lines[-1].encode(), store.salt()))
        events = runtime.replay(FIXTURES, store)
        prints = [event for event in events if event['kind'] == 'print.completed']
        self.assertEqual(len(prints), 5)
        self.assertEqual(sum(1 for event in prints if event['eventId'] == first_id), 1)
        shown = public_text(prints)
        for secret in (
            'SYNTH_CUSTOMER_A.PDF', 'SYNTH_CUSTOMER_E.PDF', 'Synthetic Title A',
            'Synthetic Title E', 'SYNTH_QUICKSET_A', 'SYNTH_QUICKSET_E',
            'IJ35-10(Graphic Film White) [3M]', '720@720x1440-CT',
            'EPSON SureColor S80600', 'HP Latex 570',
        ):
            self.assertNotIn(secret, shown, secret)
        self.assertNotIn(store.salt().hex(), json.dumps(prints))

    def test_rotated_job_swaps_across_and_along(self):
        store = self.store()
        # 70 in across and 20 in along at 100 dpi. Across is past the 64.5 in sample limit.
        line = onyx_line(
            'Rotated Title', printer='EPSON SureColor S80600', filename='rotated.pdf',
            quick='SYNTH_QUICKSET_ROT', feed_px='2000', across_px='7000', dpi='100', copies='2',
        )
        parsed = onyx_joblog.parse_line(line, {'printers': ['EPSON SureColor S80600']}, store.salt())
        self.assertTrue(parsed['payload']['axisSwapped'])
        self.assertEqual(parsed['payload']['widthIn'], '20.00')
        self.assertEqual(parsed['payload']['mediaUsedFt'], '11.67')
        shown = json.dumps(parsed['payload'])
        self.assertNotIn('Rotated Title', shown)
        self.assertNotIn('rotated.pdf', shown)
        self.assertNotIn('SYNTH_QUICKSET_ROT', shown)
        self.assertNotIn('SureColor', shown)


class BoundAndHostTests(TempCase):
    def test_read_window_and_oversize_lines_are_capped(self):
        path = self.root / 'big.log'
        path.write_bytes(b'x' * (READ_WINDOW + 50))
        chunk = read_bytes(path, 0, self.root / 'data')
        self.assertEqual(len(chunk), READ_WINDOW)
        huge = b'A' * (64 * 1024 + 8)
        payload = b'ok\n' + huge + b'\n' + b'next\n'
        lines, offset, dropped, skipping = complete_lines(payload, 0)
        self.assertEqual(lines, [b'ok', b'next'])
        self.assertEqual(dropped, 1)
        self.assertFalse(skipping)
        self.assertEqual(offset, len(payload))
        partial = b'short\n' + (b'B' * (64 * 1024 + 4))
        lines, offset, dropped, skipping = complete_lines(partial, 0)
        self.assertEqual(lines, [b'short'])
        self.assertEqual(dropped, 1)
        self.assertTrue(skipping)
        lines, offset, dropped, skipping = complete_lines(b'garbage\nkept\n', 0, skipping=True)
        self.assertEqual(lines, [b'kept'])
        self.assertEqual(dropped, 0)
        self.assertFalse(skipping)

    def test_poll_drops_oversize_lines_and_bounds_inventory(self):
        log = self.root / 'JobLog.txt'
        log.write_bytes(b'')
        config = self.write_config({'onyx_joblog': {
            'enabled': True, 'source': {'type': 'file', 'path': str(log)},
            'printers': ['FAKE-PRINTER-A'],
        }})
        specs, _directory = load_settings(config)
        store = self.store()
        output_credential.save(store.directory, TOKEN)
        runtime.poll(specs, store, send=False)
        huge = b'C' * (64 * 1024 + 12)
        text = huge + b'\n' + (onyx_line('AFTER-HUGE', epoch='1712346400') + '\n').encode()
        log.write_bytes(text)
        runtime.poll(specs, store, send=False)
        self.assertEqual(len(store.outbox()), 1)
        self.assertGreaterEqual(store.dropped('onyx_joblog'), 1)
        self.assertNotIn(b'CCCCCCC', (self.root / 'data' / 'connector.sqlite3').read_bytes())
        view = self.root / 'stock.json'
        view.write_bytes(b'[' + b' ' * (READ_WINDOW + 32))
        view_config = self.write_config({'inventory': {
            'enabled': True, 'source': {'type': 'file', 'path': str(view)},
        }})
        view_specs, _directory = load_settings(view_config)
        runtime.poll(view_specs, store, send=False)
        self.assertFalse(store.inventory_seeded())
        self.assertGreaterEqual(store.dropped('inventory'), 1)

    def test_output_host_is_pinned_unless_the_config_file_sets_https(self):
        os.environ['EZ_NEST_OUTPUT_URL'] = 'https://evil.example/steal'
        self.assertEqual(client.normalize_output_base(None), 'https://output.jeezlabs.io')
        self.assertEqual(client.url_for('event'), 'https://output.jeezlabs.io/api/shop/telemetry')
        self.assertEqual(client.url_for('pair'), 'https://output.jeezlabs.io/api/shop/agent/pair')
        self.assertEqual(client.normalize_output_base('https://lab.example'), 'https://lab.example')
        for bad in ('http://output.jeezlabs.io', 'https://user:secret@output.jeezlabs.io', 'https://output.jeezlabs.io/api', 'not a url'):
            with self.assertRaises(client.ClientError):
                client.normalize_output_base(bad)
        plain = self.write_config({})
        loaded = load_settings(plain)
        self.assertIsNone(loaded.output_host)
        self.assertTrue(client.url_for('event', loaded.output_host).startswith('https://output.jeezlabs.io/'))
        custom = self.root / 'custom.json'
        custom.write_text(json.dumps({'outputHost': 'https://lab.example'}), encoding='utf-8')
        loaded = load_settings(custom)
        self.assertEqual(client.url_for('event', loaded.output_host), 'https://lab.example/api/shop/telemetry')
        rejected = self.root / 'bad-host.json'
        rejected.write_text(json.dumps({'outputHost': 'http://lab.example'}), encoding='utf-8')
        with self.assertRaises(ConfigError):
            load_settings(rejected)

    def test_shop_json_and_output_url_do_not_move_the_shop_key(self):
        os.environ['EZ_NEST_OUTPUT_URL'] = 'https://evil.example/steal'
        (self.root / 'shop.json').write_text(json.dumps({'outputUrl': 'https://evil.example'}), encoding='utf-8')
        calls = []

        def transport(url, raw, headers):
            calls.append((url, headers.get('Authorization'), raw))
            return 200, {}, b'{}'

        client.post_json({'ok': True}, TOKEN, role='event', transport=transport)
        client.post_json({'ok': True}, None, role='pair', transport=transport)
        self.assertEqual(calls[0][0], 'https://output.jeezlabs.io/api/shop/telemetry')
        self.assertEqual(calls[0][1], 'Bearer ' + TOKEN)
        self.assertEqual(calls[1][0], 'https://output.jeezlabs.io/api/shop/agent/pair')
        self.assertNotIn('evil.example', calls[0][0])
        self.assertNotIn('evil.example', calls[1][0])
        self.assertNotIn(b'evil.example', calls[0][2])

    def test_salt_is_random_per_install_and_state_is_private(self):
        first = self.store()
        again = Store(first.directory)
        other = Store(self.root / 'other-install')
        self.assertEqual(len(first.salt()), 32)
        self.assertEqual(first.salt(), again.salt())
        self.assertNotEqual(first.salt(), other.salt())
        if os.name != 'nt':
            self.assertEqual(first.directory.stat().st_mode & 0o077, 0)
            self.assertEqual(first.path.stat().st_mode & 0o077, 0)
        else:
            # Windows privacy is an ACL property; stat's POSIX mode is synthetic.
            for path in (first.directory, first.path):
                literal = str(path).replace("'", "''")
                # Windows PowerShell 5.1's ConvertTo-Json drops AreAccessRulesProtected.
                # The DACL 'P' flag is the protected bit. Allow rules must be only this user's SID.
                script = """
$ErrorActionPreference = 'Stop'
$env:PSModulePath = Join-Path $PSHOME 'Modules'
$acl = Get-Acl -LiteralPath '__PATH__'
[Console]::Error.WriteLine("ACL type: $($acl.GetType().FullName); SDDL: $($acl.Sddl)")
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$sddl = ([string]$acl.Sddl) -replace [char]0, ''
$protected = $false
if ($sddl -match 'D:([A-Za-z]*)') { $protected = $Matches[1].ToUpperInvariant().Contains('P') }
try {
  $value = $acl.GetType().GetProperty('AreAccessRulesProtected').GetValue($acl, $null)
  if ($null -ne $value) { $protected = $protected -or [bool]$value }
} catch {}
$allowed = @($acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | Where-Object { $_.AccessControlType -eq 'Allow' } | ForEach-Object { $_.IdentityReference.Value })
$list = (@($allowed) | ForEach-Object { '"' + $_ + '"' }) -join ','
$shown = $sddl.Replace('\\','\\\\').Replace('"','\\"')
if ($protected) { $flag = 'true' } else { $flag = 'false' }
Write-Output ('{"protected":' + $flag + ',"current":"' + $sid + '","allowed":[' + $list + '],"sddl":"' + $shown + '"}')
""".replace('__PATH__', literal)
                env = os.environ.copy()
                # The runner's PSModulePath points at PowerShell 7 and hides Get-Acl from Windows PowerShell 5.1.
                env.pop('PSModulePath', None)
                result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                                        capture_output=True, text=True, timeout=15, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                acl = json.loads(result.stdout.lstrip('\ufeff'))
                detail = ((result.stderr or '') + '\n' + str(acl.get('sddl', ''))).strip()
                self.assertTrue(acl['protected'], detail)
                self.assertEqual(set(acl['allowed']), {acl['current']}, detail)
        commands = windows_acl_commands(first.directory, 'ShopUser', container=True)
        flat = [' '.join(part) for part in commands]
        self.assertIn('/inheritance:r', flat[0])
        self.assertIn('ShopUser:(OI)(CI)F', flat[1])
        self.assertNotIn('/grant', flat[0])
        self.assertEqual(flat[1].count('/grant:r'), 1)
        self.assertNotIn('ShopUser', flat[2])
        self.assertIn('/remove:g', flat[2])
        for sid in ('*S-1-1-0', '*S-1-5-32-545', '*S-1-5-11', '*S-1-5-32-544', '*S-1-5-18'):
            self.assertIn(sid, flat[2])
        file_grant = ' '.join(windows_acl_commands(first.path, 'ShopUser', container=False)[1])
        self.assertIn('ShopUser:F', file_grant)
        self.assertNotIn('(OI)', file_grant)
        readme = ' '.join((ROOT / 'connector' / 'README.md').read_text(encoding='utf-8').split())
        self.assertIn("computer's name and installation id", readme)
        self.assertIn('sent once', readme)

    def test_pairing_text_says_the_name_and_install_id_are_sent_once(self):
        ack = json.dumps({'outcome': 'created', 'result': {'token': TOKEN, 'shopName': 'North Shop'}}).encode()
        stdout = io.StringIO()
        with patch('sys.stdout', stdout), patch('connector.client.post_json', return_value=(200, {}, ack)):
            code = main(['pair', '7K4NP-QRX2M'])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn('installation id', text)
        self.assertIn('sent once', text)
        self.assertNotIn(TOKEN, text)


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
                                  'printer', 'print.completed', '2024-04-05T19:34:38Z', payload, store.salt())

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
