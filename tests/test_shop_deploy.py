"""Shop-server install choices: one computer, many browsers."""
import opt_out
import hashlib
import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import build_windows
import server
import shop_deploy


class BytesResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, count=-1):
        if count < 0:
            data, self.payload = self.payload, b''
            return data
        data, self.payload = self.payload[:count], self.payload[count:]
        return data


class ScriptedOpener:
    def __init__(self, pages):
        self.pages = pages

    def open(self, request, timeout=None):
        return BytesResponse(self.pages[request.full_url])


class ShopDeployTests(unittest.TestCase):
    def test_hot_folder_default_follows_the_onyx_pc(self):
        self.assertEqual(shop_deploy.default_hot_folder(True), r'C:\RIP\Example RIP Input')
        self.assertEqual(shop_deploy.default_hot_folder(False), r'\\RIP\Example RIP Input')
        self.assertEqual(shop_deploy.EZ_PRESET['name'], 'Example shop')
        self.assertNotIn('EZ Designs', json.dumps(shop_deploy.EZ_PRESET))

    def test_program_files_install_uses_program_data(self):
        installed = shop_deploy.data_directory(Path('/tmp/Program Files/eznest'), frozen=True, program_files='/tmp/Program Files', program_data='/tmp/ProgramData')
        portable = shop_deploy.data_directory(Path('/tmp/portable'), frozen=True)
        source = shop_deploy.data_directory(Path('/tmp/src'), frozen=False)
        chosen = shop_deploy.data_directory(Path('/tmp/src'), data_dir='/tmp/custom')
        self.assertEqual(installed, Path('/tmp/ProgramData/eznest'))
        self.assertEqual(portable, Path('/tmp/portable/data'))
        self.assertEqual(source, Path('/tmp/src/.local'))
        self.assertEqual(chosen, Path('/tmp/custom'))

    def test_release_order(self):
        self.assertTrue(shop_deploy.is_newer('1.0.0-rc.2', '1.0.0-rc.1'))
        self.assertTrue(shop_deploy.is_newer('v1.0.0', '1.0.0-rc.2'))
        self.assertFalse(shop_deploy.is_newer('1.0.0-rc.1', '1.0.0-rc.1'))
        self.assertFalse(shop_deploy.is_newer('1.0.0-rc.1', '1.0.0'))

    def test_release_file_must_come_from_eznest(self):
        with self.assertRaisesRegex(ValueError, 'release file'):
            shop_deploy.choose_asset({'assets': [{'name': 'eznest-setup.exe', 'browser_download_url': 'https://evil.example/eznest-setup.exe'}]})
        self.assertFalse(shop_deploy.release_url_allowed('http://github.com/ezdesigns/eznest/releases/download/v1/eznest-setup.exe'))
        self.assertFalse(shop_deploy.release_url_allowed('https://user:REDACTED@example.com/ezdesigns/eznest/releases/download/v1/eznest-setup.exe'))
        api = shop_deploy._headers(shop_deploy.RELEASE_API, 'secret')
        cdn = shop_deploy._headers('https://objects.githubusercontent.com/eznest-setup.exe', 'secret')
        self.assertEqual(api['Authorization'], 'Bearer secret')
        self.assertNotIn('Authorization', cdn)

    @patch('shop_deploy.sys.platform', 'win32')
    def test_pull_latest_stages_a_checked_installer_and_skips_a_prerelease(self):
        import hashlib
        import installer_update
        current = json.dumps({'tag_name': '1.0.0-rc.1', 'assets': []}).encode()
        url = 'https://github.com/ezdesigns/eznest/releases/download/v1.0.0-rc.2/eznest-setup.exe'
        sha_url = url + '.sha256'
        payload = b'MZ-eznest'
        digest = hashlib.sha256(payload).hexdigest()
        newer = json.dumps({'tag_name': 'v1.0.0-rc.2', 'prerelease': True, 'assets': [
            {'name': 'eznest-windows.zip', 'browser_download_url': 'https://github.com/ezdesigns/eznest/releases/download/v1.0.0-rc.2/eznest-windows.zip'},
            {'name': 'eznest-setup.exe', 'browser_download_url': url},
            {'name': 'eznest-setup.exe.sha256', 'browser_download_url': sha_url},
        ]}).encode()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}):
            root = Path(tmp)
            shop_deploy.save_shop(root, False, False, updates=True)
            same = shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: current}))
            self.assertFalse(same['updated'])
            self.assertEqual(same['message'], 'This is the latest release.')
            stable = shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: newer, url: payload, sha_url: (digest + '  eznest-setup.exe\n').encode()}))
            self.assertFalse(stable['updated'])
            self.assertEqual(stable['message'], 'This is the latest release.')
            shop_deploy.save_shop(root, False, False, updates=True, channel='test')
            saved = shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: newer, url: payload, sha_url: (digest + '  eznest-setup.exe\n').encode()}))
            self.assertTrue(saved['updated'])
            self.assertTrue(saved['staged'])
            self.assertIn('checked', saved['message'])
            self.assertNotIn('opening', saved['message'])
            staged = Path(saved['path'])
            self.assertEqual(staged.read_bytes(), payload)
            self.assertTrue(installer_update.checksum_matches(hashlib.sha256(staged.read_bytes()).hexdigest(), digest))
            slipped = json.dumps({'tag_name': '9.0.0', 'assets': [{'name': '../eznest-setup.exe', 'browser_download_url': url}]}).encode()
            with self.assertRaisesRegex(ValueError, 'release file'):
                shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: slipped}))
            bare = json.dumps({'tag_name': 'v9.0.0', 'assets': [{'name': 'eznest-setup.exe', 'browser_download_url': url}]}).encode()
            with self.assertRaisesRegex(ValueError, 'no checksum'):
                shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: bare, url: payload}))

    def test_updates_off_does_not_call_github_or_read_a_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(shop_deploy.load_shop(root)['updates'])
            self.assertFalse(shop_deploy.updates_allowed(root))
            (root / 'github-token').write_text('secret-token', encoding='utf-8')
            shop_deploy.save_shop(root, False, False, updates=True)
            self.assertTrue(shop_deploy.load_shop(root)['updates'])
            self.assertFalse(shop_deploy.updates_allowed(root))
            with patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}):
                self.assertTrue(shop_deploy.updates_allowed(root))
            shop_deploy.save_shop(root, False, False, updates=False)
            self.assertFalse(shop_deploy.load_shop(root)['updates'])
            calls = {'token': 0, 'open': 0}

            def token_read(directory):
                calls['token'] += 1
                raise AssertionError('token read')

            def network(opener, url, token, timeout):
                calls['open'] += 1
                raise AssertionError('network')

            with patch.dict(os.environ, {'EZ_NEST_GITHUB_TOKEN': 'env-secret'}):
                with patch('shop_deploy.github_token', token_read), patch('shop_deploy._open', network):
                    result = shop_deploy.pull_latest(root, '1.0.0-rc.3')
            self.assertEqual(calls, {'token': 0, 'open': 0})
            self.assertEqual((root / 'github-token').read_text(encoding='utf-8'), 'secret-token')
            self.assertFalse(result['updated'])
            self.assertEqual(result['message'], 'Updates are off.')
            self.assertFalse((root / 'updates').exists())

    def test_release_pin_records_version_commit_and_exe_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'eznest-setup.exe'
            payload = b'MZ-eznest-setup'
            exe.write_bytes(payload)
            dest = root / 'BUILD.json'
            pin = build_windows.write_release_pin(dest, '1.0.0-rc.3', 'abc123', exe)
            saved = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(saved, pin)
            self.assertEqual(pin['version'], '1.0.0-rc.3')
            self.assertEqual(pin['commit'], 'abc123')
            self.assertEqual(pin['sha256'], hashlib.sha256(payload).hexdigest())

    def test_hostname_lookup_cannot_stall_shop_status(self):
        def hang(*args, **kwargs):
            time.sleep(30)
            return []

        shop_deploy.clear_name_cache()
        try:
            started = time.monotonic()
            with patch('shop_deploy.socket.getaddrinfo', hang), patch('shop_deploy.socket.getfqdn', hang), patch('shop_deploy.socket.gethostname', hang):
                status = server.shop_status()
                names = shop_deploy.shop_names()
            self.assertLess(time.monotonic() - started, 4)
            self.assertIn('addresses', status)
            self.assertIn('localhost', names)
        finally:
            shop_deploy.clear_name_cache()

    def test_shop_names_are_this_computer_or_its_own_address(self):
        shop_deploy.clear_name_cache()
        self.assertTrue(shop_deploy.shop_name_allowed(socket.gethostname()))
        self.assertFalse(shop_deploy.shop_name_allowed('8.8.8.8'))
        self.assertTrue(shop_deploy.shop_name_allowed('127.0.0.1'))
        with patch('shop_deploy.lan_addresses', return_value=['192.168.1.20']):
            shop_deploy.clear_name_cache()
            self.assertTrue(shop_deploy.shop_name_allowed('192.168.1.20'))
            self.assertFalse(shop_deploy.shop_name_allowed('192.168.1.21'))
            self.assertFalse(shop_deploy.shop_name_allowed('10.1.1.1'))
        shop_deploy.clear_name_cache()

    def test_host_header_allows_shop_names_only_in_lan_mode(self):
        old = (server.HOST, server.PORT, server.LAN)
        try:
            handler = server.Handler.__new__(server.Handler)
            server.PORT = 8765
            server.HOST = '127.0.0.1'
            server.LAN = False
            self.assertFalse(handler.local_name('shop-pc:8765'))
            self.assertTrue(handler.local_name('127.0.0.1:8765'))
            self.assertFalse(handler.local_name('127.0.0.1:9999'))
            server.HOST = '0.0.0.0'
            self.assertFalse(handler.local_name('127.0.0.1:9999'))
            self.assertFalse(handler.local_name('localhost:80'))
            self.assertTrue(handler.local_name('localhost:8765'))
            self.assertFalse(handler.local_name('shop-pc:8765'))
            server.LAN = True
            host = socket.gethostname()
            shop_deploy.clear_name_cache()
            with patch('shop_deploy.lan_addresses', return_value=['192.168.1.20']):
                shop_deploy.clear_name_cache()
                self.assertTrue(handler.local_name(host + ':8765'))
                self.assertTrue(handler.local_name('192.168.1.20:8765'))
                self.assertFalse(handler.local_name('10.9.8.7:8765'))
                self.assertFalse(handler.local_name('8.8.8.8:8765'))
                self.assertFalse(handler.local_name(host + ':80'))
            shop_deploy.clear_name_cache()
        finally:
            server.HOST, server.PORT, server.LAN = old

    def test_shop_status_uses_the_service_port(self):
        old = (server.WORK, server.PORT, server.HOST, server.LAN)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server.WORK = root
                server.PORT = 8765
                server.HOST = '127.0.0.1'
                server.LAN = False
                status = server.shop_status()
                self.assertTrue(status['url'].endswith(':8765/web'))
                self.assertFalse(status['lan'])
                self.assertIn('anyone on the shop lan can send to onyx', status['warning'].casefold())
                self.assertIn('guest wifi', status['warning'].casefold())
                self.assertFalse(status['updates'])
                self.assertEqual(status['outputTelemetryUrl'], 'https://output.jeezlabs.io/api/shop/telemetry')
                self.assertEqual(status['version'], '1.0.0-rc.5')
                self.assertIn(r'\\RIP\Example RIP Input', status['hotFolderDefault'])
            finally:
                server.WORK, server.PORT, server.HOST, server.LAN = old

    def test_installer_script_matches_the_shop_server(self):
        root = Path(__file__).resolve().parents[1]
        version = json.loads((root / 'version.json').read_text(encoding='utf-8'))['version']
        script = (root / 'installer' / 'eznest.iss').read_text(encoding='utf-8')
        install = (root / 'installer' / 'install-shop.ps1').read_text(encoding='utf-8')
        server_cmd = (root / 'eznest-server.cmd').read_text(encoding='utf-8')
        build = (root / 'build_windows.py').read_text(encoding='utf-8')
        self.assertNotIn(f'#define MyAppVersion "{version}"', script)
        self.assertIn('MyAppVersion is passed from version.json', script)
        self.assertIn('/DMyAppVersion=', build)
        self.assertIn("version.json", build)
        self.assertIn(r'{autopf}\eznest', script)
        self.assertIn('{commondesktop}', script)
        self.assertIn('uninstall-shop.ps1', script)
        self.assertIn('New-ScheduledTaskTrigger -AtStartup', install)
        self.assertIn('Register-ScheduledTask', install)
        self.assertNotIn('/RU SYSTEM', install)
        self.assertNotIn('/RL HIGHEST', install)
        self.assertIn('-RunLevel Limited', install)
        self.assertIn('eznest-svc', install)
        self.assertIn('icacls', install)
        self.assertIn('SeBatchLogonRight', install)
        self.assertIn('(OI)(CI)M', install)
        self.assertIn('(OI)(CI)W', install)
        self.assertIn('profile=private', install)
        self.assertIn('TlsCert', install)
        self.assertIn('TlsKey', install)
        self.assertIn('Recommended: use HTTPS', install)
        self.assertIn('EZ_NEST_HTTPS_PROMPT', install)
        self.assertIn('Name: "checkupdates"', script)
        self.assertIn('Check for app updates (also set EZ_NEST_UPDATES=1)', script)
        self.assertIn("Result := '0'", script)
        self.assertIn('LicenseFile=..\\LICENSE', script)
        self.assertIn('AppCopyright=Copyright (C) 2026 EZ Designs', script)
        self.assertIn('-Updates', script)
        self.assertIn('Excludes: "BUILD.json"', script)
        self.assertIn('{src}\\BUILD.json', script)
        self.assertIn('external', script)
        self.assertNotIn(r'C:\ONYX\EPSON SureColor S80600 ONYX Input', install)
        self.assertIn('output-folder.json', install)
        self.assertIn('setupComplete', install)
        self.assertIn('IsFreshInstall', script)
        self.assertIn('--web --no-browser', server_cmd)
        self.assertIn(r'%ProgramData%\eznest', server_cmd)
        self.assertIn('ISCC', build)
        self.assertIn('eznest-server.cmd', build)
        self.assertIn('uninstall-shop.ps1', build)

    def test_uninstall_removes_the_task_then_the_service_account(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / 'installer' / 'eznest.iss').read_text(encoding='utf-8')
        uninstall = (root / 'installer' / 'uninstall-shop.ps1').read_text(encoding='utf-8')
        uninstall_run = script.split('[UninstallRun]', 1)[1].split('[Code]', 1)[0]
        self.assertIn('uninstall-shop.ps1', uninstall_run)
        self.assertIn(r'{commonappdata}\eznest', uninstall_run)
        self.assertIn('schtasks.exe', uninstall)
        self.assertIn('eznest-svc', uninstall)
        self.assertIn('icacls', uninstall)
        self.assertNotIn(r'C:\ONYX\EPSON SureColor S80600 ONYX Input', uninstall)
        self.assertIn('output-folder.json', uninstall)
        self.assertIn('advfirewall firewall delete rule name=eznest', uninstall)
        end = uninstall.index('/End')
        delete = uninstall.index('/Delete')
        remove_acl = uninstall.index('/remove')
        remove_user = uninstall.index('Remove-LocalUser')
        disable_user = uninstall.index('Disable-LocalUser')
        self.assertLess(end, delete)
        self.assertLess(delete, remove_acl)
        self.assertLess(remove_acl, remove_user)
        self.assertLess(remove_user, disable_user)

    def test_output_network_is_off_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(shop_deploy.load_shop(root)['outputNetwork'])
            self.assertEqual(shop_deploy.load_shop(root)['channel'], 'stable')
            self.assertFalse(shop_deploy.load_shop(root)['setupComplete'])
            saved = shop_deploy.save_shop(root, False, False, outputNetwork=True)
            self.assertTrue(saved['outputNetwork'])
            share = shop_deploy.output_network_status(saved)
            self.assertFalse(share['sends'])
            self.assertIn('does not send', share['note'])
            self.assertIn('capacity', share['note'])
            self.assertIn('off', share['note'].casefold())
            saved_text = (root / 'shop.json').read_text(encoding='utf-8')
            self.assertNotIn('http://', saved_text)
            self.assertNotIn('https://', saved_text)
            self.assertIn('"outputUrl": ""', saved_text)

    def test_release_links_follow_the_environment_and_need_no_token(self):
        self.assertNotIn('Authorization', shop_deploy._headers(shop_deploy.release_api(), ''))
        with patch.dict(os.environ, {
            'EZ_NEST_RELEASE_API': 'https://api.github.com/repos/example/nest/releases?per_page=5',
            'EZ_NEST_ISSUES_URL': 'https://github.com/example/nest/issues/new',
        }):
            self.assertIn('/repos/example/nest/releases', shop_deploy.release_api())
            self.assertEqual(shop_deploy.issues_url(), 'https://github.com/example/nest/issues/new')
            self.assertEqual(shop_deploy.repo_for_release(), 'example/nest')
            self.assertTrue(shop_deploy.release_url_allowed(
                'https://github.com/example/nest/releases/download/v1/eznest-setup.exe', repo='example/nest'))

    def test_windows_workflows_keep_ci_unsigned_and_gate_dual_platform_publishing(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / '.github/workflows/windows-installer.yml').read_text(encoding='utf-8')
        tests = (root / '.github/workflows/test.yml').read_text(encoding='utf-8')
        self.assertNotIn('WINDOWS_CERT_BASE64', installer)
        self.assertNotIn('secrets.', installer)
        self.assertNotIn('contents: write', installer)
        self.assertNotIn('gh release', installer)
        self.assertNotIn('\n  publish:', installer)
        release = (root / '.github/workflows/auto-release.yml').read_text(encoding='utf-8')
        plan, publish = release.split('\n  plan:', 1)[1].split('\n  publish:', 1)
        self.assertIn("github.event.workflow_run.event == 'push'", plan)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", plan)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", plan)
        self.assertIn('environment: eznest-release', publish)
        self.assertIn('needs: [plan, windows, macos]', publish)
        self.assertIn('contents: write', publish)
        self.assertIn('tools/auto_release.py publish', publish)
        self.assertIn('version.json', installer)
        self.assertIn('installer_update.py --write-sidecars', installer)
        self.assertIn('tests/test_shop_scripts.ps1', tests)
        script = (root / 'tests/test_shop_scripts.ps1').read_text(encoding='utf-8')
        self.assertIn('install-shop.ps1', script)
        self.assertIn('uninstall-shop.ps1', script)
        self.assertIn('eznest-svc', script)

    def test_output_service_url_is_allowlisted_and_https_only(self):
        self.assertEqual(shop_deploy.output_base_url(), 'https://output.jeezlabs.io')
        self.assertEqual(shop_deploy.normalize_output_base('https://user:secret@output.example'), '')
        self.assertEqual(shop_deploy.normalize_output_base('http://output.example'), '')
        self.assertEqual(shop_deploy.normalize_output_base('https://output.example/api'), '')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = shop_deploy.save_shop(root, False, False, outputUrl='https://output.jeezlabs.io')
            self.assertEqual(saved['outputUrl'], 'https://output.jeezlabs.io')
            self.assertEqual(shop_deploy.output_base_url(root), 'https://output.jeezlabs.io')
            with self.assertRaisesRegex(ValueError, 'output.jeezlabs.io'):
                shop_deploy.save_shop(root, False, False, outputUrl='https://output.example.test')
            self.assertEqual(shop_deploy.load_shop(root)['outputUrl'], 'https://output.jeezlabs.io')
            with patch.dict(os.environ, {'EZ_NEST_OUTPUT_URL': 'https://env.example.test'}):
                self.assertEqual(shop_deploy.output_base_url(root), 'https://env.example.test')
                saved = shop_deploy.save_shop(root, False, False, outputUrl='https://env.example.test')
                self.assertEqual(saved['outputUrl'], 'https://env.example.test')
                self.assertEqual(shop_deploy.load_shop(root)['outputUrl'], 'https://env.example.test')
            with self.assertRaisesRegex(ValueError, 'https'):
                shop_deploy.save_shop(root, False, False, outputUrl='http://insecure.example')
            self.assertEqual(shop_deploy.load_shop(root)['outputUrl'], '')

    def test_github_token_is_not_read_from_shop_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'github-token').write_text('file-secret\n', encoding='utf-8')
            (root / 'shop.json').write_text(json.dumps({'githubToken': 'json-secret', 'updates': False}), encoding='utf-8')
            with patch('shop_deploy._windows_credential', return_value='') as store:
                self.assertEqual(shop_deploy.github_token(root), '')
                if os.name == 'nt':
                    store.assert_called_once_with('eznest/github-token')
                else:
                    store.assert_not_called()
            with patch.dict(os.environ, {'EZ_NEST_GITHUB_TOKEN': 'env-secret'}):
                self.assertEqual(shop_deploy.github_token(root), 'env-secret')
            shop_deploy.save_shop(root, False, False)
            text = (root / 'shop.json').read_text(encoding='utf-8')
            self.assertNotIn('json-secret', text)
            self.assertNotIn('githubToken', text)
            self.assertEqual((root / 'github-token').read_text(encoding='utf-8'), 'file-secret\n')

    def test_send_names_a_missing_hot_folder(self):
        from output_folder import OutputFolder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / 'missing-share'
            folder = OutputFolder(root / 'output-folder.json')
            with self.assertRaisesRegex(ValueError, "can't be reached"):
                folder.connect(str(missing))
            self.assertIn('missing-share', (root / 'output-folder.json').read_text(encoding='utf-8'))
            again = OutputFolder(root / 'output-folder.json')
            with self.assertRaisesRegex(ValueError, "can't be reached"):
                again.save('ab' * 16, b'not-a-zip')


if __name__ == '__main__':
    unittest.main()



