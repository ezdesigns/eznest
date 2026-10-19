import hashlib
import json
import os
import signal
import subprocess
import time
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
from zipfile import ZipFile, ZipInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher
import server
import updater
import updates
from app_info import VERSION


APP = '''import json, os, sys, time
from pathlib import Path
root = Path(__file__).resolve().parent
folder = root / 'data' / 'updates'
folder.mkdir(parents=True, exist_ok=True)
(folder / 'child.pid').write_text(str(os.getpid()), encoding='utf-8')
if (root / 'FAIL').is_file():
    raise SystemExit(1)
applying = folder / 'applying.json'
if applying.is_file() and '--update-confirm' in sys.argv:
    payload = json.loads(applying.read_text(encoding='utf-8'))
    (folder / 'healthy.json').write_text(json.dumps({'version': payload['version'], 'pid': os.getpid()}), encoding='utf-8')
'''


def version_bytes(version):
    return json.dumps({'app': 'eznest', 'version': version, 'updateChannel': 'beta'}).encode()


def write_install(root, version, fail=False):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'eznest.py').write_text(APP, encoding='utf-8')
    (root / 'version.json').write_bytes(version_bytes(version))
    (root / '_internal').mkdir(exist_ok=True)
    (root / '_internal' / 'build.txt').write_text(version, encoding='utf-8')
    if fail:
        (root / 'FAIL').write_text('fail', encoding='utf-8')
    data = root / 'data' / 'documents'
    data.mkdir(parents=True, exist_ok=True)
    return data


def zip_install(destination, source_root):
    with ZipFile(destination, 'w') as archive:
        for path in source_root.rglob('*'):
            if path.is_file() and 'updates' not in path.parts:
                archive.write(path, f"eznest/{path.relative_to(source_root).as_posix()}")
    return destination


def kill_recorded(data_dir):
    pid_file = Path(data_dir) / 'updates' / 'child.pid'
    if not pid_file.is_file():
        return
    try:
        os.kill(int(pid_file.read_text(encoding='utf-8')), signal.SIGTERM)
    except OSError:
        pass


class UpdateLogicTests(unittest.TestCase):
    def test_versions_order_prereleases_before_the_release(self):
        ordered = ['0.12.0-alpha', '0.12.0-beta', '0.12.0-beta.1', '0.12.0-beta.2', '0.12.0-beta.10', '0.12.0', '0.13.0', '1.0.0-rc.1', '1.0.0']
        for older, newer in zip(ordered, ordered[1:]):
            self.assertEqual(updates.compare(older, newer), -1, f'{older} should be older than {newer}')
        self.assertEqual(updates.compare('v0.12.0-beta.1', '0.12.0-beta.1'), 0)

    def test_beta_channel_can_move_to_stable_but_not_backward(self):
        beta = {'version': '0.13.0-beta.2', 'channel': 'beta', 'url': 'https://example.com/b.zip', 'sha256': 'ab'}
        stable = {'version': '0.12.5', 'channel': 'stable', 'url': 'https://example.com/s.zip', 'sha256': 'cd'}
        self.assertEqual(updates.choose_update('0.12.0', 'beta', [stable, beta])['version'], '0.13.0-beta.2')
        self.assertIsNone(updates.choose_update('0.13.0-beta.2', 'beta', [stable]))
        self.assertEqual(updates.choose_update('0.13.0-beta.2', 'beta', [dict(stable, version='0.13.0')])['channel'], 'stable')
        self.assertIsNone(updates.choose_update('0.12.0', 'stable', [beta]))

    def test_unpublished_manifest_is_not_an_update(self):
        with TemporaryDirectory() as temp:
            manifest = updates.write_ci_manifest(Path(temp) / 'manifest.json', '0.12.0-beta.2', 'a' * 64, 'eznest.zip', notes='candidate')
        self.assertFalse(manifest['published'])
        self.assertIsNone(manifest['platforms']['windows-x64']['url'])
        self.assertFalse(updates.usable_manifest(manifest, 'beta'))
        self.assertFalse(updates.usable_manifest({'channel': 'beta', 'version': '9.0.0', 'published': True, 'platforms': {'windows-x64': {'url': 'http://example.com/a.zip', 'sha256': 'ab'}}}, 'beta'))

    def test_changelog_includes_the_running_version(self):
        versions = [entry['version'] for entry in updates.changelog_entries()]
        self.assertIn(VERSION, versions)

    def test_redirects_stay_on_an_allowed_host(self):
        with self.assertRaises(ValueError):
            updates._require_url('file:///tmp/eznest.zip')
        with self.assertRaises(ValueError):
            updates._require_url('http://example.com/eznest.zip')
        updates._require_url('https://example.com/eznest.zip')
        updates._require_url('http://127.0.0.1:9/eznest.zip')


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.install = self.root / 'eznest'
        self.documents = write_install(self.install, '0.12.0-beta.1')
        (self.documents / 'job.txt').write_text('JOB-42', encoding='utf-8')
        self.job = (self.documents / 'job.txt').read_bytes()
        self.processes = []
        real_popen = subprocess.Popen
        def tracking(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            self.processes.append(process)
            return process
        self.popen_patch = patch('updater.subprocess.Popen', tracking)
        self.popen_patch.start()

    def tearDown(self):
        self.popen_patch.stop()
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self.temp.cleanup()

    def stage(self, version, fail=False):
        payload = self.root / f'payload-{version}'
        write_install(payload, version, fail=fail)
        (payload / 'data' / 'documents').mkdir(parents=True, exist_ok=True)
        (payload / 'data' / 'documents' / 'job.txt').write_text('OVERWRITE', encoding='utf-8')
        (payload / '_internal' / 'build.txt').write_text('replaced-' + version, encoding='utf-8')
        archive = self.root / f'{version}.zip'
        zip_install(archive, payload)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        updates.write_json(self.install / 'data' / 'updates' / 'pending.json', {
            'version': version, 'sha256': digest, 'zip': str(archive), 'verified': True,
            'applyOnRestart': True, 'openBrowser': False,
        })
        return archive

    def test_failed_start_restores_the_app_and_keeps_jobs(self):
        self.stage('0.12.0-beta.2', fail=True)
        result = updater.apply_and_confirm(self.install, self.install / 'data', timeout=3)
        self.assertFalse(result['ok'])
        self.assertEqual(result['restored'], '0.12.0-beta.1')
        self.assertEqual(json.loads((self.install / 'version.json').read_text())['version'], '0.12.0-beta.1')
        self.assertEqual((self.install / '_internal' / 'build.txt').read_text(encoding='utf-8'), '0.12.0-beta.1')
        self.assertFalse((self.install / 'FAIL').exists())
        self.assertEqual((self.documents / 'job.txt').read_bytes(), self.job)
        rollback = json.loads((self.install / 'data' / 'updates' / 'rollback.json').read_text())
        self.assertEqual(rollback['failed'], '0.12.0-beta.2')

    def test_successful_swap_keeps_jobs_and_replaces_the_app(self):
        self.stage('0.12.0-beta.2', fail=False)
        result = updater.apply_and_confirm(self.install, self.install / 'data', timeout=5)
        self.assertTrue(result['ok'])
        self.assertEqual((self.install / '_internal' / 'build.txt').read_text(encoding='utf-8'), 'replaced-0.12.0-beta.2')
        self.assertEqual((self.documents / 'job.txt').read_bytes(), self.job)
        self.assertFalse((self.install / 'data' / 'updates' / 'backup').exists())

    def test_bad_checksum_and_zip_slip_do_not_touch_the_install(self):
        archive = self.root / 'tamper.zip'
        zip_install(archive, self.install)
        updates.write_json(self.install / 'data' / 'updates' / 'pending.json', {
            'version': '0.12.0-beta.1', 'sha256': '0' * 64, 'zip': str(archive), 'verified': True, 'applyOnRestart': True,
        })
        self.assertIsNone(updates.pending_state(self.install / 'data'))
        slipped = self.root / 'slip.zip'
        with ZipFile(slipped, 'w') as handle:
            handle.writestr('../outside.txt', 'nope')
        with self.assertRaises(ValueError):
            updater.safe_extract(slipped, self.root / 'extracted')
        self.assertFalse((self.root / 'outside.txt').exists())
        linked = self.root / 'link.zip'
        with ZipFile(linked, 'w') as handle:
            info = ZipInfo('eznest/link')
            info.external_attr = (0xA1FF) << 16
            handle.writestr(info, 'target')
        with self.assertRaises(ValueError):
            updater.safe_extract(linked, self.root / 'linked')

    def test_next_launch_hands_off_without_starting_the_server(self):
        archive = self.root / 'pending.zip'
        archive.write_bytes(b'zip')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        updates.write_json(self.install / 'data' / 'updates' / 'pending.json', {
            'version': '0.12.0-beta.2', 'sha256': digest, 'zip': str(archive), 'verified': True, 'applyOnRestart': True,
        })
        with patch.object(updater, 'spawn_helper') as spawn, patch.object(sys, 'argv', ['eznest', '--no-browser', '--port', '8765', '--data-dir', str(self.install / 'data')]), patch.dict(os.environ, {'EZ_NEST_INSTALL_ROOT': str(self.install), 'EZ_NEST_UPDATES': '1'}), patch.object(launcher, 'urlopen', side_effect=URLError('down')):
            self.assertEqual(launcher.main(), 0)
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0], self.install.resolve())
        self.assertEqual(Path(spawn.call_args.args[1]).resolve(), (self.install / 'data').resolve())


class DownloadTests(unittest.TestCase):
    def test_prepare_rejects_a_bad_checksum_and_accepts_a_good_one(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            install = root / 'eznest'
            write_install(install, '0.12.0-beta.1')
            payload = root / 'payload'
            write_install(payload, '0.12.0-beta.2')
            archive = root / 'www' / 'eznest-0.12.0-beta.2-windows-x64.zip'
            archive.parent.mkdir()
            zip_install(archive, payload)
            body = archive.read_bytes()
            digest = hashlib.sha256(body).hexdigest()

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/go':
                        self.send_response(302)
                        self.send_header('Location', '/eznest.zip')
                        self.end_headers()
                        return
                    if self.path == '/away':
                        self.send_response(302)
                        self.send_header('Location', 'http://example.com/eznest.zip')
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                def log_message(self, *args):
                    pass

            service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(service.shutdown)
            self.addCleanup(service.server_close)
            url = f'http://127.0.0.1:{service.server_port}/eznest.zip'
            remote = {'updateAvailable': True, 'latest': '0.12.0-beta.2', 'sha256': 'f' * 64, 'url': url, 'filename': archive.name, 'offerChannel': 'beta', 'notes': 'test'}
            with self.assertRaises(ValueError):
                updates.prepare(install / 'data', install, 'restart', remote=remote)
            self.assertFalse(any((install / 'data' / 'updates').glob('incoming/*')))
            remote['sha256'] = digest
            remote['url'] = f'http://127.0.0.1:{service.server_port}/go'
            prepared = updates.prepare(install / 'data', install, 'restart', remote=remote)
            self.assertTrue(prepared['applyOnRestart'])
            self.assertEqual(prepared['stagedVersion'], '0.12.0-beta.2')
            saved = Path(updates.pending_state(install / 'data')['zip']).read_bytes()
            self.assertEqual(saved, body)
            with self.assertRaises(ValueError):
                updates.fetch_bytes(f'http://127.0.0.1:{service.server_port}/away', timeout=5)


class ServerChannelTests(unittest.TestCase):
    def test_changelog_and_update_status_are_local(self):
        service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        previous = server.PORT
        server.PORT = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        from urllib.request import urlopen
        try:
            with patch('updates.cached_check', return_value={'current': VERSION, 'channel': 'beta', 'enabled': True, 'updateAvailable': False, 'latest': None, 'error': None}):
                with urlopen(f'http://127.0.0.1:{server.PORT}/api/changelog', timeout=5) as response:
                    changelog = json.load(response)
                with urlopen(f'http://127.0.0.1:{server.PORT}/api/update', timeout=5) as response:
                    status = json.load(response)
            self.assertEqual(changelog['version'], VERSION)
            self.assertTrue(any(entry['version'] == VERSION for entry in changelog['entries']))
            self.assertEqual(status['current'], VERSION)
            self.assertFalse(status['updateAvailable'])
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=3)
            server.PORT = previous

    def test_a_running_search_blocks_the_update(self):
        import copy
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        original, previous = copy.deepcopy(server.STATE), server.PORT
        service = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        server.STATE.clear()
        server.STATE.update(status='running')
        try:
            request = Request(f'http://127.0.0.1:{server.PORT}/api/update/prepare', data=b'{"when":"restart"}', headers={'Content-Type': 'application/json', 'X-EZ-Token': server.TOKEN})
            with self.assertRaises(HTTPError) as blocked:
                urlopen(request, timeout=5)
            self.assertEqual(blocked.exception.code, 400)
        finally:
            server.STATE.clear()
            server.STATE.update(original)
            service.shutdown()
            service.server_close()
            thread.join(timeout=3)
            server.PORT = previous


class InterfaceTests(unittest.TestCase):
    def test_production_page_has_the_tester_controls(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / 'production.html').read_text(encoding='utf-8')
        self.assertEqual(html, (root / 'index.html').read_text(encoding='utf-8'))
        for token in ('whats-new-open', 'update-now', 'update-later', 'report-problem', 'id="whats-new"'):
            self.assertIn(token, html)
        self.assertIn('tester-problem.yml', html)


if __name__ == '__main__':
    unittest.main()
