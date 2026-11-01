"""Pairing stores a host credential and never returns it. No live OUTPUT call."""
import opt_out
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import output_credential
import output_pairing
import server
import telemetry
import telemetry_sender as sender

TOKEN = 'osa_' + 'B' * 43
CODE = '7K4NP-QRX2M'
ROOT = Path(__file__).resolve().parents[1]


class FlipCodec:
    def protect(self, data):
        return bytes(byte ^ 0x5A for byte in data)

    def unprotect(self, data):
        return bytes(byte ^ 0x5A for byte in data)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_pairing_stays_on_the_allowlisted_origin(self):
        (self.root / 'shop.json').write_text(json.dumps({'outputUrl': 'https://evil.example'}), encoding='utf-8')
        seen = {}

        class Response:
            status = 404

            def read(self, _size):
                return b'{}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def open_request(request, timeout=10):
            seen['url'] = request.full_url
            return Response()

        opener = Mock()
        opener.open.side_effect = open_request
        output_pairing._PAIR_DIRECTORY = self.root
        try:
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_URL': 'https://evil.example/steal'}):
                with patch('output_pairing.build_opener', return_value=opener):
                    output_pairing._post(b'{}')
            self.assertEqual(seen['url'], 'https://output.jeezlabs.io/api/shop/agent/pair')
            self.assertNotIn('evil.example', seen['url'])
            with patch('output_pairing.pair_endpoint', return_value='https://evil.example/api/shop/agent/pair'):
                with patch('output_pairing.build_opener') as blocked:
                    with self.assertRaises(output_pairing.PairingError):
                        output_pairing._post(b'{}')
                    blocked.assert_not_called()
        finally:
            output_pairing._PAIR_DIRECTORY = None

    def test_private_file_round_trip_and_corrupt_file_is_not_connected(self):
        output_credential.save(self.root, TOKEN, 'North Shop')
        target = output_credential.path(self.root)
        if os.name == 'nt':
            # Windows has no POSIX mode bits. The file is restricted with an ACL,
            # so assert no broad principal was granted access.
            import subprocess
            acl = subprocess.run(['icacls', str(target)], capture_output=True, text=True).stdout
            for broad in ('Everyone', 'BUILTIN\\Users', 'Authenticated Users'):
                self.assertNotIn(broad, acl)
        else:
            self.assertEqual(target.stat().st_mode & 0o077, 0)
        self.assertEqual(output_credential.load(self.root), TOKEN)
        self.assertEqual(output_credential.describe(self.root)['shopName'], 'North Shop')
        target.write_bytes(b'not-a-credential')
        self.assertIsNone(output_credential.load(self.root))
        output_credential.clear(self.root)
        self.assertFalse(target.exists())

    def test_protecting_codec_hides_the_credential(self):
        output_credential.save(self.root, TOKEN, 'North Shop', codec=FlipCodec())
        blob = output_credential.path(self.root).read_bytes()
        self.assertNotIn(TOKEN.encode(), blob)
        self.assertNotIn(b'North Shop', blob)
        self.assertEqual(output_credential.load(self.root, codec=FlipCodec()), TOKEN)

    def test_shop_name_and_token_are_rejected_before_a_file_exists(self):
        for name in ('', 'bad\nname', 'x' * 81):
            with self.assertRaises(ValueError):
                output_credential.save(self.root, TOKEN, name)
        with self.assertRaises(ValueError):
            output_credential.save(self.root, 'osa_short', 'North Shop')
        self.assertFalse(output_credential.path(self.root).exists())


class _Icacls:
    def __init__(self, code, stdout=b'', stderr=b''):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


class WindowsAclTests(unittest.TestCase):
    """ACL grants are checked with a mocked icacls so Linux CI covers Windows."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / output_credential.FILE_NAME
        self.target.write_bytes(b'blob')

    def _restrict(self, run, account_exists):
        return (
            patch.object(output_credential, '_account_exists', return_value=account_exists),
            patch.object(output_credential.subprocess, 'run', side_effect=run),
            patch.dict(os.environ, {'USERNAME': 'shop-user'}),
        )

    def test_all_grants_succeed(self):
        calls = []

        def run(args, **kwargs):
            calls.append((list(args), kwargs))
            self.assertIsNot(kwargs.get('shell'), True)
            self.assertTrue(kwargs.get('capture_output'))
            return _Icacls(0)

        account, process, env = self._restrict(run, True)
        with account, process, env:
            output_credential._restrict_windows(self.target)
        self.assertEqual(calls[0][0], ['icacls', str(self.target), '/inheritance:r'])
        grant = calls[1][0]
        self.assertEqual(grant[:3], ['icacls', str(self.target), '/grant:r'])
        self.assertEqual(grant[3:], [
            '*S-1-5-18:(M)', '*S-1-5-32-544:(M)', 'shop-user:(M)', 'eznest-svc:(M)',
        ])
        self.assertEqual(len(calls), 2)

    def test_unmapped_service_account_retries_without_it(self):
        failures = (
            _Icacls(1332),
            _Icacls(5, stdout='No mapping between account names and security IDs was done.'),
        )
        for failure in failures:
            calls = []

            def run(args, **kwargs):
                calls.append(list(args))
                self.assertIsNot(kwargs.get('shell'), True)
                if args[2] == '/inheritance:r':
                    return _Icacls(0)
                if 'eznest-svc:(M)' in args:
                    return failure
                return _Icacls(0)

            account, process, env = self._restrict(run, None)
            with account, process, env:
                output_credential._restrict_windows(self.target)
            self.assertEqual(calls[0], ['icacls', str(self.target), '/inheritance:r'])
            self.assertIn('eznest-svc:(M)', calls[1])
            self.assertEqual(calls[2][:3], ['icacls', str(self.target), '/grant:r'])
            self.assertNotIn('eznest-svc:(M)', calls[2])
            self.assertEqual(calls[2][3:], ['*S-1-5-18:(M)', '*S-1-5-32-544:(M)', 'shop-user:(M)'])
            for broad in ('Everyone', 'Users', 'Authenticated Users', 'BUILTIN\\Users'):
                self.assertNotIn(broad, calls[2])
            self.assertEqual(len(calls), 3)

    def test_known_missing_service_account_is_omitted(self):
        calls = []

        def run(args, **kwargs):
            calls.append(list(args))
            return _Icacls(0)

        account, process, env = self._restrict(run, False)
        with account, process, env:
            output_credential._restrict_windows(self.target)
        self.assertEqual([call[2] for call in calls], ['/inheritance:r', '/grant:r'])
        self.assertNotIn('eznest-svc:(M)', calls[1])
        self.assertEqual(calls[1][3:], ['*S-1-5-18:(M)', '*S-1-5-32-544:(M)', 'shop-user:(M)'])

    def test_required_grant_failure_raises(self):
        calls = []

        def run(args, **kwargs):
            calls.append(list(args))
            if args[2] == '/inheritance:r':
                return _Icacls(0)
            return _Icacls(1332, stderr=b'No mapping between account names and security IDs was done.')

        account, process, env = self._restrict(run, False)
        with account, process, env:
            with self.assertRaisesRegex(ValueError, 'Could not protect the saved OUTPUT credential'):
                output_credential._restrict_windows(self.target)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('eznest-svc:(M)', calls[1])

        calls.clear()

        def retry(args, **kwargs):
            calls.append(list(args))
            if args[2] == '/inheritance:r':
                return _Icacls(0)
            if 'eznest-svc:(M)' in args:
                return _Icacls(1332, stderr=b'No mapping between account names and security IDs was done.')
            return _Icacls(5, stderr=b'Access is denied.')

        account, process, env = self._restrict(retry, None)
        with account, process, env:
            with self.assertRaisesRegex(ValueError, 'Could not protect the saved OUTPUT credential'):
                output_credential._restrict_windows(self.target)
        grants = [call for call in calls if call[2] == '/grant:r']
        self.assertEqual(len(grants), 2)
        self.assertNotIn('eznest-svc:(M)', grants[1])
        self.assertIn('shop-user:(M)', grants[1])
        self.assertIn('*S-1-5-18:(M)', grants[1])
        self.assertIn('*S-1-5-32-544:(M)', grants[1])

    def test_inheritance_failure_raises(self):
        calls = []

        def run(args, **kwargs):
            calls.append(list(args))
            return _Icacls(1, stderr=b'Access is denied.')

        account, process, env = self._restrict(run, True)
        with account, process, env:
            with self.assertRaisesRegex(ValueError, 'Could not protect the saved OUTPUT credential'):
                output_credential._restrict_windows(self.target)
        self.assertEqual(calls, [['icacls', str(self.target), '/inheritance:r']])

    def test_account_grant_rejects_unsafe_names(self):
        for name in (
            '', 'a' * 65, 'user*', 'user?', 'has"quote', 'a<b', 'a>b', 'a|b', 'a:b',
            'line\n', 'line\r', 'has\x00null', None, 7, b'eznest-svc',
        ):
            self.assertIsNone(output_credential._account_grant(name), name)
        self.assertEqual(output_credential._account_grant('eznest-svc'), 'eznest-svc:(M)')
        self.assertEqual(output_credential._account_grant('a' * 64), ('a' * 64) + ':(M)')
        calls = []

        def run(args, **kwargs):
            calls.append(list(args))
            return _Icacls(0)

        with patch.object(output_credential, '_account_exists', return_value=False), \
             patch.object(output_credential.subprocess, 'run', side_effect=run), \
             patch.dict(os.environ, {'USERNAME': 'shop:user'}):
            output_credential._restrict_windows(self.target)
        self.assertNotIn('shop:user:(M)', calls[1])
        self.assertNotIn('shop:user', calls[1])
        self.assertEqual(calls[1][3:], ['*S-1-5-18:(M)', '*S-1-5-32-544:(M)'])

    def test_account_lookup_does_not_shell_out(self):
        with patch.object(output_credential.subprocess, 'run', side_effect=AssertionError('shell')):
            result = output_credential._account_exists('eznest-svc')
        self.assertIn(result, (True, False, None))

    def test_save_round_trip_when_service_account_is_unmapped(self):
        calls = []

        def run(args, **kwargs):
            calls.append(list(args))
            self.assertIsNot(kwargs.get('shell'), True)
            if args[2] == '/inheritance:r':
                return _Icacls(0)
            if 'eznest-svc:(M)' in args:
                return _Icacls(1332, stderr=b'No mapping between account names and security IDs was done.')
            return _Icacls(0)

        with patch.object(output_credential, '_use_windows_acl', return_value=True), \
             patch.object(output_credential, '_account_exists', return_value=None), \
             patch.object(output_credential.subprocess, 'run', side_effect=run), \
             patch.dict(os.environ, {'USERNAME': 'shop-user'}):
            output_credential.save(self.root, TOKEN, 'North Shop')
        self.assertEqual(output_credential.load(self.root), TOKEN)
        self.assertEqual(output_credential.describe(self.root)['shopName'], 'North Shop')
        if os.name != 'nt':
            self.assertEqual(output_credential.path(self.root).stat().st_mode & 0o077, 0)
        self.assertEqual(sum(call[2] == '/inheritance:r' for call in calls), 2)
        attempted = [call for call in calls if 'eznest-svc:(M)' in call]
        applied = [call for call in calls if call[2] == '/grant:r' and 'eznest-svc:(M)' not in call]
        self.assertEqual(len(attempted), 2)
        self.assertEqual(len(applied), 2)
        for call in applied:
            self.assertEqual(call[3:], ['*S-1-5-18:(M)', '*S-1-5-32-544:(M)', 'shop-user:(M)'])
            self.assertNotIn('Everyone', call)


def created(shop='North Shop'):
    return 200, json.dumps({'outcome': 'created', 'result': {'token': TOKEN, 'shopName': shop}}).encode()


class ExchangeTests(unittest.TestCase):
    def test_wire_host_label_fits_output_utf16_limit(self):
        cases = (
            ('SHOP PC', 'SHOP PC'),
            ('x' * 80, 'x' * 60),
            ('\u5e97' * 61, '\u5e97' * 60),
            ('x' * 59 + '\U0001f680', 'x' * 59),
            ('\U0001f680' * 31, '\U0001f680' * 30),
            (' \t\n', 'localhost'),
        )
        for supplied, expected in cases:
            with self.subTest(host_label=supplied):
                seen = []
                def transport(raw):
                    seen.append(json.loads(raw))
                    return created()
                output_pairing.exchange(CODE, host_label=supplied, transport=transport)
                label = seen[0]['hostLabel']
                self.assertEqual(label, expected)
                self.assertLessEqual(len(label.encode('utf-16-le')) // 2, 60)
                self.assertFalse(any(0xD800 <= ord(ch) <= 0xDFFF for ch in label))

    def test_code_is_trimmed_uppercased_and_hyphen_optional(self):
        self.assertEqual(output_pairing.normalize_code('  7k4np-qrx2m '), CODE)
        self.assertEqual(output_pairing.normalize_code('7k4npqrx2m'), CODE)
        self.assertEqual(output_pairing.normalize_code('7K4NP - QRX2M'), CODE)
        for bad in ('', 'NOPE-0000', '7K4NP-QRX2', '7K4NP-QRX2MM', 'not a code'):
            with self.assertRaises(output_pairing.PairingError) as caught:
                output_pairing.normalize_code(bad)
            self.assertEqual(caught.exception.reason, 'invalid_code')
            if bad.strip():
                self.assertNotIn(bad.strip(), str(caught.exception))

    def test_success_token_replay_and_each_error_code(self):
        import telemetry_output
        self.assertEqual(telemetry_output.SCHEMA, 'eznest-observation/1')
        result = output_pairing.interpret(*created())
        self.assertEqual(result, {'credential': TOKEN, 'shopName': 'North Shop'})
        outpost = output_pairing.interpret(200, json.dumps({'outcome': 'created', 'result': {'token': TOKEN, 'outpostId': 'op_123'}}).encode())
        self.assertEqual(outpost, {'credential': TOKEN, 'shopName': None})
        self.assertNotIn('op_123', json.dumps(outpost))
        secret = json.dumps({'error': {'version': 1, 'schema': None, 'code': 'expired', 'field': 'code', 'message': CODE + TOKEN}}).encode()

        def envelope(code, field='code'):
            return {'error': {'version': 1, 'schema': None, 'code': code, 'field': field, 'message': 'server says ' + CODE}}

        cases = (
            (503, envelope('disabled', 'service'), 'disabled', output_pairing.DISABLED),
            (404, envelope('invalid_code'), 'invalid_code', output_pairing.INVALID_CODE),
            (401, envelope('expired'), 'expired', output_pairing.EXPIRED),
            (409, envelope('consumed'), 'consumed', output_pairing.CONSUMED),
            (429, envelope('rate_limited'), 'rate_limited', output_pairing.RATE_LIMITED),
            (409, envelope('limit'), 'limit', output_pairing.LIMIT),
            (409, envelope('conflict'), 'unexpected', output_pairing.UNEXPECTED),
            (409, envelope('other'), 'unexpected', output_pairing.UNEXPECTED),
            (404, {'code': 'api_route_not_found', 'detail': CODE}, 'disabled', output_pairing.DISABLED),
            (401, {'error': 'expired'}, 'expired', output_pairing.EXPIRED),
            (429, {'code': 'rate_limited'}, 'rate_limited', output_pairing.RATE_LIMITED),
        )
        for status, payload, reason, message in cases:
            with self.assertRaises(output_pairing.PairingError) as caught:
                output_pairing.interpret(status, json.dumps(payload).encode())
            self.assertEqual(caught.exception.reason, reason)
            self.assertEqual(str(caught.exception), message)
            self.assertNotIn(CODE, str(caught.exception))
            self.assertNotIn(TOKEN, str(caught.exception))
        with self.assertRaises(output_pairing.PairingError) as replay:
            output_pairing.interpret(200, b'{"outcome":"replay"}')
        self.assertEqual(replay.exception.reason, 'replay')
        self.assertNotIn(TOKEN, str(replay.exception))
        with self.assertRaises(output_pairing.PairingError) as leaked:
            output_pairing.interpret(401, secret)
        self.assertNotIn(CODE, str(leaked.exception))
        self.assertNotIn(TOKEN, str(leaked.exception))
        with self.assertRaises(output_pairing.PairingError) as bad:
            output_pairing.interpret(200, json.dumps({'outcome': 'created', 'result': {'token': 'not-a-token'}}).encode())
        self.assertEqual(bad.exception.reason, 'unexpected')
        self.assertNotIn('not-a-token', str(bad.exception))

    def test_request_id_is_reused_only_for_a_network_retry(self):
        seen = []

        def transport(raw):
            body = json.loads(raw)
            seen.append(body)
            if len(seen) == 1:
                raise output_pairing.PairingError('offline', output_pairing.OFFLINE)
            return created()

        result = output_pairing.exchange('7k4npqrx2m', host_label='SHOP PC', host_ref='ab' * 16, transport=transport)
        self.assertEqual(result['shopName'], 'North Shop')
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[0]['code'], CODE)
        self.assertEqual(seen[0]['hostLabel'], 'SHOP PC')
        self.assertEqual(seen[0]['hostRef'], 'ab' * 16)
        self.assertRegex(seen[0]['requestId'], output_pairing.UUID_RE.pattern)
        self.assertEqual(set(seen[0]), {'code', 'requestId', 'hostLabel', 'hostRef'})
        again = []

        def once(raw):
            again.append(json.loads(raw)['requestId'])
            return created()

        output_pairing.exchange(CODE, host_label='SHOP PC', transport=once)
        output_pairing.exchange(CODE, host_label='SHOP PC', transport=once)
        self.assertEqual(len(again), 2)
        self.assertNotEqual(again[0], again[1])
        self.assertNotEqual(again[0], seen[0]['requestId'])
        calls = []

        def fail(_raw):
            calls.append(1)
            return 503, b'{"code":"disabled","detail":"7K4NP-QRX2M"}'

        with self.assertRaises(output_pairing.PairingError) as disabled:
            output_pairing.exchange(CODE, host_label='HOST', transport=fail)
        self.assertEqual(calls, [1])
        self.assertEqual(disabled.exception.reason, 'disabled')
        self.assertNotIn(CODE, str(disabled.exception))

    def test_transport_does_not_follow_redirects(self):
        with patch.object(output_pairing, 'build_opener') as opener:
            opener.return_value.open.side_effect = URLError('timed out')
            with self.assertRaises(output_pairing.PairingError) as offline:
                output_pairing.exchange(CODE, host_label='HOST')
            self.assertEqual(offline.exception.reason, 'offline')
            self.assertNotIn('timed out', str(offline.exception))
            self.assertEqual(opener.return_value.open.call_count, output_pairing.NETWORK_ATTEMPTS)
            self.assertIsInstance(opener.call_args.args[0], output_pairing.NoRedirect)
        with patch.object(output_pairing, 'build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError(output_pairing.ENDPOINT, 302, 'Found', hdrs={}, fp=io.BytesIO(b'{"result":{"token":"' + TOKEN.encode() + b'"}}'))
            with self.assertRaises(output_pairing.PairingError) as redirected:
                output_pairing.exchange(CODE, host_label='HOST')
            self.assertNotIn(TOKEN, str(redirected.exception))
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.assertIsInstance(opener.call_args.args[0], sender.NoRedirect)


class ConnectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = json.loads((ROOT / 'sample.json').read_text())
        self.env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def transport(self, raw):
        self.sent = json.loads(raw)
        return created()

    def test_connect_stores_credential_and_consent_sends_it_without_env(self):
        order = []
        real_save = output_credential.save
        real_status = sender.status

        def save(*args, **kwargs):
            order.append('save')
            return real_save(*args, **kwargs)

        def status(*args, **kwargs):
            order.append('status')
            self.assertEqual(output_credential.load(self.root), TOKEN)
            return real_status(*args, **kwargs)

        with patch.object(output_credential, 'save', side_effect=save), patch.object(sender, 'status', side_effect=status):
            info = output_pairing.connect(self.root, '  7k4npqrx2m  ', transport=self.transport, host='HOST')
        self.assertEqual(order, ['save', 'status'])
        self.assertEqual(self.sent['code'], CODE)
        self.assertEqual(self.sent['hostLabel'], 'HOST')
        self.assertRegex(self.sent['requestId'], output_pairing.UUID_RE.pattern)
        self.assertRegex(self.sent['hostRef'], r'^[0-9a-f]{32}$')
        self.assertEqual(info['connection'], 'paired')
        self.assertEqual(info['shopName'], 'North Shop')
        self.assertTrue(info['requiresConsent'])
        self.assertNotIn(TOKEN, json.dumps(info))
        self.assertNotIn(CODE, json.dumps(info))
        self.assertNotIn(TOKEN.encode(), (self.root / 'telemetry.sqlite3').read_bytes())
        agreed = sender.consent(self.root, revision=info['revision'], version=info['consentVersion'], configurationId=info['configurationId'], confirmed=True)
        self.assertTrue(agreed['enabled'])
        telemetry.observe(self.root, 'c' * 32, self.job, {'width': 180, 'usedLength': 100, 'area': 10000, 'placements': [{}], 'elapsed': 5})
        with patch.object(sender, 'emit', return_value=True) as emit:
            self.assertGreater(sender.tick(self.root), 0)
            self.assertTrue(emit.call_args_list)
            self.assertTrue(all(call.args[1] == TOKEN for call in emit.call_args_list))
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '1', 'EZ_NEST_OUTPUT_TOKEN': 'osa_' + 'C' * 43}):
            self.assertEqual(sender.connection(self.root)['source'], 'environment')
            self.assertIsNone(sender.connection(self.root)['shopName'])
            self.assertFalse(sender.status(self.root)['enabled'])
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '0'}):
            self.assertEqual(sender.connection(self.root)['source'], 'disabled')
            self.assertIsNone(sender.configuration(self.root))

    def test_outpost_id_is_not_stored_as_a_shop_name(self):
        def transport(_raw):
            return 200, json.dumps({'outcome': 'created', 'result': {'token': TOKEN, 'outpostId': 'outpost-1'}}).encode()
        info = output_pairing.connect(self.root, CODE, transport=transport, host='HOST')
        self.assertIsNone(info['shopName'])
        self.assertEqual(info['connection'], 'paired')
        self.assertTrue(info['configured'])
        saved = output_credential.path(self.root).read_bytes()
        self.assertNotIn(b'outpost-1', saved)
        self.assertNotIn(b'shopName', saved)
        self.assertNotIn(TOKEN.encode(), json.dumps(info).encode())

    def test_environment_and_shop_test_do_not_spend_a_code(self):
        def explode(_raw):
            raise AssertionError('pairing code was sent')
        for uploads in ('0', '1'):
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': uploads, 'EZ_NEST_OUTPUT_TOKEN': 'osa_' + 'C' * 43}):
                with self.assertRaises(output_pairing.PairingError):
                    output_pairing.connect(self.root, CODE, transport=explode)
        self.assertFalse(output_credential.path(self.root).exists())

    def test_disconnect_removes_the_file_and_stops_sharing(self):
        output_pairing.connect(self.root, CODE, transport=self.transport, host='HOST')
        info = sender.status(self.root)
        sender.consent(self.root, revision=info['revision'], version=info['consentVersion'], configurationId=info['configurationId'], confirmed=True)
        disconnected = output_pairing.disconnect(self.root)
        self.assertFalse(disconnected['configured'])
        self.assertFalse(output_credential.path(self.root).exists())
        with self.assertRaises(output_pairing.PairingError):
            output_pairing.disconnect(self.root)
        output_credential.save(self.root, TOKEN, 'North Shop')
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '1', 'EZ_NEST_OUTPUT_TOKEN': 'osa_' + 'C' * 43}):
            with self.assertRaises(output_pairing.PairingError):
                output_pairing.disconnect(self.root)
        self.assertTrue(output_credential.path(self.root).exists())


class PairApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.old = (server.WORK, server.PORT)
        server.WORK = Path(self.folder.name)
        self.service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = self.service.server_port
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def stop(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join()
        server.WORK, server.PORT = self.old

    def request(self, path, data, token=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-EZ-Token'] = server.TOKEN
        req = Request(f'http://127.0.0.1:{server.PORT}' + path, data=json.dumps(data).encode(), headers=headers)
        try:
            with urlopen(req) as response:
                return response.status, json.load(response)
        except Exception as error:
            if not hasattr(error, 'read'):
                raise
            return error.code, json.loads(error.read().decode())

    def test_host_pair_and_disconnect_hide_the_credential(self):
        seen = {}

        def exchange(code, *, host_label, host_ref=None, transport=None, attempts=2):
            seen.update(code=code, host_label=host_label, host_ref=host_ref)
            return {'credential': TOKEN, 'shopName': 'North Shop'}

        with patch.object(output_pairing, 'exchange', side_effect=exchange):
            status, body = self.request('/api/telemetry/output/pair', {'code': CODE})
        self.assertEqual(seen['code'], CODE)
        self.assertTrue(seen['host_label'])
        self.assertRegex(seen['host_ref'], r'^[0-9a-f]{32}$')
        self.assertEqual(status, 200)
        self.assertEqual(body['shopName'], 'North Shop')
        self.assertEqual(body['connection'], 'paired')
        self.assertTrue(body['requiresConsent'])
        self.assertNotIn(TOKEN, json.dumps(body))
        self.assertNotIn('credential', body)
        status, denied = self.request('/api/telemetry/output/pair', {'code': CODE}, token=False)
        self.assertEqual(status, 403)
        self.assertNotIn(TOKEN, json.dumps(denied))
        status, body = self.request('/api/telemetry/output/disconnect', {})
        self.assertEqual(status, 200)
        self.assertFalse(body['configured'])
        self.assertNotIn(TOKEN, json.dumps(body))

    def test_lan_client_cannot_pair(self):
        handler = object.__new__(server.Handler)
        handler.client_address = ('192.168.1.50', 1234)
        handler.headers = {'X-EZ-Token': server.TOKEN, 'Content-Length': '2'}
        handler.allowed = lambda: True
        handler.send = Mock()
        handler.path = '/api/telemetry/output/pair'
        handler.rfile = io.BytesIO(b'{}')
        with patch.object(output_pairing, 'exchange', side_effect=AssertionError('lan client paired')):
            handler.handle_post()
        self.assertEqual(handler.send.call_args.args[0], 403)


class DialogCopyTests(unittest.TestCase):
    def test_popup_copy_links_and_colors(self):
        html = (ROOT / 'web.html').read_text(encoding='utf-8')
        css = (ROOT / 'web.css').read_text(encoding='utf-8')
        script = (ROOT / 'web.js').read_text(encoding='utf-8')
        dialog = html.split('id="max-output-dialog"', 1)[1].split('</dialog>', 1)[0]
        self.assertIn('<h2 id="max-output-title">Don\'t print</h2>', dialog)
        self.assertLess(dialog.index('This is a test preview. No real jobs or payments are sent.'), dialog.index('OUTPUT routes the job'))
        self.assertIn('OUTPUT routes the job to the best-fit print shop near you, based on what each shop can make.', dialog)
        self.assertIn('>Preview · test only</span>', html)
        self.assertNotIn('Devnet', html)
        self.assertNotIn('🤑', html)
        self.assertIn('You still get paid.', dialog)
        self.assertNotIn('sandbox', dialog.lower())
        self.assertNotIn('id="output-gate"', html)
        self.assertIn('DEV MODE: not connected to OUTPUT', (ROOT / 'output_gate.py').read_text(encoding='utf-8'))
        self.assertIn("You don't have the material or roll width", dialog)
        self.assertIn('Your customer is too far away', dialog)
        self.assertIn("You're too busy to finish on time", dialog)
        self.assertEqual(dialog.count('class="primary-link"'), 1)
        self.assertIn('class="output-learn"', dialog)
        self.assertIn('id="max-output-learn"', dialog)
        for banned in ('$', 'fee', '%', 'How it works', 'What is OUTPUT?', 'Devnet'):
            self.assertNotIn(banned, dialog)
        self.assertIn('.output-modes > * { padding: 11px 12px; border: 1px solid #dce0e4; border-radius: 9px; background: #f3f3f0;', css)
        self.assertIn('#max-output .paid-badge { position: static; margin-top: 2px; padding: 0; border-radius: 0; background: transparent;', css)
        self.assertNotIn('#f3fbf6', css)
        self.assertIn('#output-connect-status.error { color: #D92F00; }', css)
        self.assertRegex(css, r'#output-pair-code \{[^}]*border: 1px solid #5c5c58;[^}]*background: #fff;[^}]*color: #1c1c1c;')
        self.assertIn("const OUTPUT_WAITLIST_URL = new URL('waitlist', OUTPUT_WEBSITE_URL).href;", script)
        self.assertIn('https://output.jeezlabs.io/', script)
        self.assertIn('id="output-pair"', html)
        self.assertIn('id="output-disconnect"', html)
        self.assertIn("info.shopName ? 'Connected to ' + info.shopName + '.' : 'Connected to OUTPUT'", script)


class OutputScreenTests(unittest.TestCase):
    """Browser check for the popup and the host connect control."""

    def test_popup_and_connect_failure_are_visible(self):
        import test_web_mvp
        from playwright.sync_api import expect, sync_playwright
        helper = test_web_mvp.WebMvpTests(methodName='runTest')
        helper.setUp()
        try:
            shots = Path(__file__).resolve().parents[1] / '.local' / 'test-screenshots'
            shots.mkdir(parents=True, exist_ok=True)
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '', 'EZ_NEST_OUTPUT_TOKEN': ''}), sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    page.goto(helper.url() + '/web')
                    helper.wait_ready(page)
                    expect(page.locator('#max-output')).to_be_visible()
                    self.assertEqual(page.locator('#max-output').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgb(243, 243, 240)')
                    self.assertEqual(page.locator('#max-output .paid-badge').evaluate('n => getComputedStyle(n).backgroundColor'), 'rgba(0, 0, 0, 0)')
                    page.click('#max-output')
                    expect(page.locator('#max-output-title')).to_have_text("Don't print")
                    expect(page.locator('#max-output-waitlist')).to_have_attribute('href', 'https://output.jeezlabs.io/waitlist')
                    expect(page.locator('#max-output-learn')).to_have_attribute('href', 'https://output.jeezlabs.io/')
                    self.assertEqual(page.locator('#max-output-learn').get_attribute('class'), 'output-learn')
                    self.assertEqual(page.locator('.output-points li').count(), 3)
                    page.screenshot(path=str(shots / 'output-popup-desktop.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    box = page.locator('#max-output-dialog').bounding_box()
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertLessEqual(box['x'] + box['width'], 390)
                    page.screenshot(path=str(shots / 'output-popup-mobile.png'))
                    page.keyboard.press('Escape')
                    page.set_viewport_size({'width': 1280, 'height': 900})
                    page.click('#settings-open')
                    page.locator('#settings-telemetry').evaluate('node => node.open = true')
                    page.wait_for_function("() => !document.querySelector('#output-pair').disabled")
                    expect(page.locator('#output-pair-form')).to_be_visible()
                    page.fill('#output-pair-code', '7k4np-qrx2m')

                    def disabled(*_args, **_kwargs):
                        raise output_pairing.PairingError('disabled', output_pairing.DISABLED)

                    with patch.object(output_pairing, 'exchange', side_effect=disabled):
                        page.click('#output-pair')
                        page.wait_for_function("() => document.querySelector('#output-connect-status').classList.contains('error')")
                    message = page.locator('#output-connect-status').inner_text()
                    self.assertEqual(message, output_pairing.DISABLED)
                    self.assertEqual(page.input_value('#output-pair-code'), '7k4np-qrx2m')
                    self.assertNotIn('osa_', page.locator('#settings-telemetry').inner_text())
                    self.assertEqual(page.locator('#output-connect-status').evaluate('n => getComputedStyle(n).color'), 'rgb(217, 47, 0)')
                    page.screenshot(path=str(shots / 'output-connect-error-desktop.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.locator('#output-connect').scroll_into_view_if_needed()
                    page.screenshot(path=str(shots / 'output-connect-error-mobile.png'))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                finally:
                    browser.close()
        finally:
            helper.tearDown()


if __name__ == '__main__':
    unittest.main()
