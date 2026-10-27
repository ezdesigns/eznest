import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
import telemetry as t

NEST = 'a' * 32
ROLL = 'b' * 32
REQUEST = 'c' * 32
JOB = {'materialId': 'Customer private preset', 'webOptions': {'material': 'chrome'},
       'settings': {'rollWidth': 1100},
       'productionJobs': [{'order': 'EZ-1234', 'name': 'Private customer', 'code': 'A',
                           'sourceFile': 'Secret artwork.pdf'}]}
RESULT = {'width': 1000, 'usedLength': 1250, 'area': 750000,
          'placements': [{'id': 'Private piece'}], 'elapsed': 91.234}


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def create(self, ident=NEST):
        t.observe(self.root, ident, JOB, RESULT)

    def commit(self, ident=NEST):
        t.observe(self.root, ident, JOB, RESULT, 'nest.committed')

    def stock(self, remaining=10000, revision=0, request=REQUEST):
        key = t.measurements(JOB, RESULT)['materialKey']
        t.record_stock(self.root, ROLL, key, remaining, request, revision)

    def test_actual_atom_is_banded_and_excludes_private_fields(self):
        self.commit()
        atom = next(e for e in t.pending(self.root) if e['type'] == 'material.allocated')
        self.assertEqual(atom['payload']['jobCodes'], ['EZ-1234'])
        self.assertEqual(atom['payload']['lengthMmBand'], '[1250,1500)')
        self.assertEqual(atom['payload']['materialClass'], 'moto_chrome')
        self.assertFalse(atom['payload']['consumed'])
        self.assertNotIn('lengthMm', atom['payload'])
        text = json.dumps(t.pending(self.root))
        for secret in ('Private', 'Secret', 'artwork.pdf', '91.234'):
            self.assertNotIn(secret, text)
            if secret != '91.234':  # Exact measurements are intentionally local.
                self.assertFalse(secret.encode() in (self.root / 'telemetry.sqlite3').read_bytes())
        emit = Mock(return_value=True)
        self.assertEqual(t.dispatch(self.root, emit), 0)
        emit.assert_not_called()
        with self.assertRaises(ValueError):
            t.dispatch(self.root, emit, enabled=True, registered_schema='unregistered')
        self.assertEqual(t.dispatch(self.root, emit, enabled=True, registered_schema=t.SCHEMA), 4)
        self.assertIn(atom, [call.args[0] for call in emit.call_args_list])
        self.assertEqual(t.pending(self.root), [])

    def test_retries_restart_and_hub_failure_do_not_double_allocate(self):
        self.commit()
        first = t.pending(self.root)
        self.commit()
        self.create()
        self.assertEqual(first, t.pending(self.root))
        emit = Mock(side_effect=RuntimeError('hub down'))
        with self.assertRaises(RuntimeError):
            t.dispatch(self.root, emit, enabled=True, registered_schema=t.SCHEMA)
        self.assertEqual(first, t.pending(self.root))
        self.assertEqual(t.dispatch(self.root, lambda _: False, enabled=True, registered_schema=t.SCHEMA), 0)
        self.assertEqual(first, t.pending(self.root))
        self.assertEqual(t.status(self.root)['nests'][0]['status'], 'prepared')

    def test_stock_reservation_print_confirmation_and_new_measurement(self):
        self.create()
        self.stock()
        t.link(self.root, NEST, ['EZ-1234'], ROLL)
        self.commit()
        self.commit()
        roll = t.status(self.root)['rolls'][0]
        self.assertEqual(roll['remaining_mm'], 10000)
        self.assertEqual(roll['reservedMm'], 1250)
        self.assertEqual(roll['availableToAllocateMm'], 8750)
        t.transition(self.root, NEST, 'queue')
        t.transition(self.root, NEST, 'queue')
        t.observe(self.root, NEST, JOB, RESULT, 'nest.sent_to_print')
        self.assertEqual(t.status(self.root)['rolls'][0]['reservedMm'], 1250)
        t.transition(self.root, NEST, 'printed')
        t.transition(self.root, NEST, 'printed')
        roll = t.status(self.root)['rolls'][0]
        self.assertEqual(roll['reservedMm'], 0)
        self.assertEqual(roll['estimatedRemainingMm'], 8750)
        self.assertEqual(roll['remaining_mm'], 10000)
        self.stock(8700, 1, 'd' * 32)
        roll = t.status(self.root)['rolls'][0]
        self.assertEqual(roll['availableToAllocateMm'], 8700)
        self.assertEqual(roll['confirmedPlannedUseSinceReadingMm'], 0)

    def test_stock_revision_and_request_replay_guards(self):
        self.stock()
        self.stock()
        with self.assertRaises(ValueError):
            self.stock(9000)
        with self.assertRaises(ValueError):
            self.stock(9000, 0, 'd' * 32)
        self.assertEqual(t.status(self.root)['rolls'][0]['remaining_mm'], 10000)

    def test_stock_reconciliation_does_not_depend_on_wall_clock(self):
        self.create()
        self.stock()
        t.link(self.root, NEST, ['EZ-1234'], ROLL)
        self.commit()
        t.transition(self.root, NEST, 'queue')
        with patch.object(t, 'now', return_value='2000-01-01T00:00:00+00:00'):
            t.transition(self.root, NEST, 'printed')
        self.assertEqual(t.status(self.root)['rolls'][0]['estimatedRemainingMm'], 8750)
        with patch.object(t, 'now', return_value='1999-01-01T00:00:00+00:00'):
            self.stock(8700, 1, 'd' * 32)
        self.assertEqual(t.status(self.root)['rolls'][0]['estimatedRemainingMm'], 8700)

    def test_link_changes_back_to_previous_value_have_distinct_events(self):
        self.create()
        for code in ('EZ-5678', 'EZ-9999', 'EZ-5678', 'EZ-5678'):
            t.link(self.root, NEST, [code])
        events = [e for e in t.pending(self.root) if e['type'] == 'nest.linked']
        self.assertEqual(len(events), 3)
        self.assertEqual(len(set(e['id'] for e in events)), 3)
        self.assertEqual(events[-1]['payload']['jobCodes'], ['EZ-5678'])

    def test_cancel_releases_reservation_but_folder_removal_does_not(self):
        self.create()
        self.stock(1000)
        t.link(self.root, NEST, [], ROLL)
        self.commit()
        t.observe(self.root, NEST, JOB, RESULT, 'nest.removed_from_folder')
        roll = t.status(self.root)['rolls'][0]
        self.assertEqual(roll['shortfallMm'], 250)
        self.assertEqual(roll['reservedMm'], 1250)
        t.transition(self.root, NEST, 'cancel')
        self.assertEqual(t.status(self.root)['rolls'][0]['reservedMm'], 0)
        with self.assertRaises(ValueError):
            t.transition(self.root, NEST, 'printed')

    def test_multi_job_codes_and_multi_sheet_length_are_not_double_counted(self):
        job = copy.deepcopy(JOB)
        job['productionJobs'] += [{'order': 'EZ-5678'}, {'code': 'EZ-1234'}, {'order': 'Customer Name'}]
        result = dict(RESULT, usedLength=2500, sheets=[{'usedLength': 1250}, {'usedLength': 1250}])
        t.observe(self.root, NEST, job, result, 'nest.committed')
        snapshot = t.status(self.root)['nests'][0]['snapshot']
        self.assertEqual(snapshot['jobCodes'], ['EZ-1234', 'EZ-5678'])
        self.assertEqual(snapshot['lengthMm'], 2500)
        self.assertEqual(snapshot['sheetCount'], 2)
        self.assertEqual(snapshot['rollAreaM2'], 2.75)
        self.assertEqual(len([e for e in t.pending(self.root) if e['type'] == 'material.allocated']), 1)

    def test_context_immutable_after_commit_and_unknown_stock_stays_unknown(self):
        self.create()
        with self.assertRaises(ValueError):
            t.link(self.root, NEST, ['Customer Secret'])
        with self.assertRaises(ValueError):
            t.link(self.root, NEST, ['EZ-1234'], ROLL)
        t.link(self.root, NEST, ['EZ-5678'])
        self.commit()
        with self.assertRaises(ValueError):
            t.link(self.root, NEST, ['EZ-0000'])
        self.assertEqual(t.status(self.root)['rolls'], [])
        atom = next(e for e in t.pending(self.root) if e['type'] == 'material.allocated')
        self.assertEqual(atom['payload']['jobCodes'], ['EZ-5678'])
        self.assertIsNone(atom['payload']['rollId'])

    def test_invalid_numbers_leave_no_partial_observations(self):
        for value in (float('nan'), float('inf'), -1, True, 'Private'):
            with self.assertRaises(ValueError):
                t.observe(self.root, NEST, JOB, dict(RESULT, usedLength=value))
        self.assertEqual(t.pending(self.root), [])
        with self.assertRaises(ValueError):
            t.observe(self.root, NEST, JOB, dict(RESULT, area=1e10))

    def test_concurrent_freeze_is_one_allocation(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.commit(), range(8)))
        self.assertEqual(len(t.pending(self.root)), 4)


class TelemetryApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.old_work, self.old_port, self.old_state = server.WORK, server.PORT, copy.deepcopy(server.STATE)
        server.WORK = Path(self.folder.name)
        server.STATE.clear()
        server.STATE.update(status='ready', id=NEST, job=copy.deepcopy(JOB), result=copy.deepcopy(RESULT))
        self.service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = self.service.server_port
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join()
        server.WORK, server.PORT = self.old_work, self.old_port
        server.STATE.clear()
        server.STATE.update(self.old_state)
        self.folder.cleanup()

    def request(self, path, data=None, token=True, headers=None):
        request_headers = {'Content-Type': 'application/json'}
        if token:
            request_headers['X-EZ-Token'] = server.TOKEN
        request_headers.update(headers or {})
        req = Request(f'http://127.0.0.1:{server.PORT}' + path,
                      data=json.dumps(data).encode() if data is not None else None, headers=request_headers)
        with urlopen(req) as response:
            return json.load(response)

    def test_auth_context_and_explicit_queue_confirmation(self):
        for route in ('/api/telemetry', '/api/telemetry/events'):
            with self.assertRaises(HTTPError) as failure:
                self.request(route, token=False)
            self.assertEqual(failure.exception.code, 403)
        server.record_telemetry('nest.created')
        self.request('/api/telemetry/link', {'id': NEST, 'jobCodes': ['EZ-9999']})
        server.record_workload('prepared')
        for body in ({'id': NEST, 'action': 'queue'}, {'id': NEST, 'action': 'queue', 'confirmed': True, 'name': 'secret'}):
            with self.assertRaises(HTTPError):
                self.request('/api/telemetry/status', body)
        self.request('/api/telemetry/status', {'id': NEST, 'action': 'queue', 'confirmed': True})
        info = self.request('/api/telemetry')
        self.assertEqual(info['nests'][0]['status'], 'queued')
        self.assertFalse(info['hubConnected'])
        with self.assertRaises(HTTPError):
            self.request('/api/telemetry/status', {'id': NEST, 'action': 'printed', 'confirmed': True}, headers={'Origin': 'http://evil.test'})

    def test_actual_server_hooks_distinguish_save_folder_from_rip(self):
        from output_folder import OutputFolder
        hot = server.WORK / 'hot'
        hot.mkdir()
        output = OutputFolder(server.WORK / 'output-folder.json')
        output.connect(str(hot), None)
        server.record_workload('prepared')
        with patch.object(server, 'OUTPUT', output), patch.object(server, 'load_shop', return_value={'hotFolder': ''}):
            server.record_workload('sent_to_folder')
        kinds = [e['type'] for e in t.pending(server.WORK)]
        self.assertIn('nest.exported', kinds)
        self.assertNotIn('nest.sent_to_print', kinds)
        with patch.object(server, 'OUTPUT', output), patch.object(server, 'load_shop', return_value={'hotFolder': str(hot)}):
            server.record_workload('sent_to_folder')
        kinds = [e['type'] for e in t.pending(server.WORK)]
        self.assertIn('nest.sent_to_print', kinds)
        self.assertNotIn('nest.printed', kinds)

    def test_tracking_failure_cannot_fail_layout_or_delivery(self):
        with patch.object(t, 'observe', side_effect=sqlite3.OperationalError('full')):
            server.record_workload('prepared')
            self.assertEqual(server.STATE['status'], 'ready')
            self.assertIn('telemetryWarning', server.STATE)
        server.record_telemetry('nest.created')
        self.assertNotIn('telemetryWarning', server.STATE)

    def test_failed_and_rejected_improvement_do_not_create_extra_nests(self):
        # Manifest already has its own geometry checks; isolate the lifecycle here.
        with patch.object(server, 'manifest', return_value={}), patch.object(server, 'batch_output_check', return_value=None):
            server.finish_search({'ok': True, 'result': copy.deepcopy(RESULT)})
            original = copy.deepcopy(server.STATE)
            server.STATE.update(id='d' * 32, incumbent=original)
            server.finish_search({'ok': False, 'error': 'failed attempt'})
        self.assertEqual(len(t.status(server.WORK)['nests']), 1)
        self.assertEqual(len(t.pending(server.WORK)), 2)

    def test_lan_clients_cannot_read_or_change_telemetry(self):
        import io
        handler = object.__new__(server.Handler)
        handler.client_address = ('192.168.1.123', 1234)
        handler.headers = {'X-EZ-Token': server.TOKEN, 'Content-Length': '2'}
        handler.allowed = lambda: True
        handler.send = Mock()
        handler.path = '/api/telemetry'
        handler.do_GET()
        self.assertEqual(handler.send.call_args.args[0], 403)
        handler.path = '/api/telemetry/stock'
        handler.rfile = io.BytesIO(b'{}')
        handler.handle_post()
        self.assertEqual(handler.send.call_args.args[0], 403)

    def test_stock_api_accepts_only_explicit_versioned_measurements(self):
        body = {'rollId': ROLL, 'materialKey': t.measurements(JOB, RESULT)['materialKey'],
                'remainingMm': 10000, 'requestId': REQUEST, 'expectedRevision': 0}
        self.request('/api/telemetry/stock', body)
        self.request('/api/telemetry/stock', body)
        with self.assertRaises(HTTPError):
            self.request('/api/telemetry/stock', dict(body, customer='never allowed'))
        info = self.request('/api/telemetry')
        self.assertEqual(info['rolls'][0]['revision'], 1)
        self.assertEqual(info['rolls'][0]['remaining_mm'], 10000)

    def test_preexisting_frozen_pack_cannot_be_relinked_after_upgrade(self):
        server.STATE['released'] = True
        with self.assertRaises(HTTPError):
            self.request('/api/telemetry/link', {'id': NEST, 'jobCodes': ['EZ-9999']})
        self.assertEqual(t.status(server.WORK)['totalNests'], 0)


if __name__ == '__main__':
    unittest.main()
