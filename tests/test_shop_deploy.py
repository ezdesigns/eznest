"""Shop-server install choices: one computer, many browsers."""
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(shop_deploy.default_hot_folder(True), r'C:\ONYX\EPSON SureColor S80600 ONYX Input')
        self.assertEqual(shop_deploy.default_hot_folder(False), r'\\ONYX\EPSON SureColor S80600 ONYX Input')

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
        self.assertFalse(shop_deploy.release_url_allowed('https://user:secret@github.com/ezdesigns/eznest/releases/download/v1/eznest-setup.exe'))
        api = shop_deploy._headers(shop_deploy.RELEASE_API, 'secret')
        cdn = shop_deploy._headers('https://objects.githubusercontent.com/eznest-setup.exe', 'secret')
        self.assertEqual(api['Authorization'], 'Bearer secret')
        self.assertNotIn('Authorization', cdn)

    def test_pull_latest_reports_current_and_saves_a_newer_installer(self):
        current = json.dumps({'tag_name': '1.0.0-rc.1', 'assets': []}).encode()
        url = 'https://github.com/ezdesigns/eznest/releases/download/v1.0.0-rc.2/eznest-setup.exe'
        newer = json.dumps({'tag_name': 'v1.0.0-rc.2', 'assets': [
            {'name': 'eznest-windows.zip', 'browser_download_url': 'https://github.com/ezdesigns/eznest/releases/download/v1.0.0-rc.2/eznest-windows.zip'},
            {'name': 'eznest-setup.exe', 'browser_download_url': url},
        ]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            same = shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: current}))
            self.assertFalse(same['updated'])
            self.assertEqual(same['message'], 'This is the latest release.')
            with patch('shop_deploy.os.startfile', create=True) as opened:
                saved = shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: newer, url: b'MZ-eznest'}))
            self.assertTrue(saved['updated'])
            self.assertIn('Downloaded eznest-setup.exe.', saved['message'])
            self.assertEqual((root / 'updates' / 'eznest-setup.exe').read_bytes(), b'MZ-eznest')
            if os.name == 'nt':
                opened.assert_called_once()
                self.assertIn('The installer is opening.', saved['message'])
            else:
                opened.assert_not_called()
                self.assertNotIn('installer is opening', saved['message'])
            slipped = json.dumps({'tag_name': '9.0.0', 'assets': [{'name': '../eznest-setup.exe', 'browser_download_url': url}]}).encode()
            with self.assertRaisesRegex(ValueError, 'release file'):
                shop_deploy.pull_latest(root, '1.0.0-rc.1', opener=ScriptedOpener({shop_deploy.RELEASE_API: slipped}))

    def test_shop_names_are_this_computer_or_a_private_address(self):
        self.assertTrue(shop_deploy.shop_name_allowed(socket.gethostname()))
        self.assertTrue(shop_deploy.shop_name_allowed('192.168.1.20'))
        self.assertFalse(shop_deploy.shop_name_allowed('8.8.8.8'))

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
            self.assertTrue(handler.local_name('127.0.0.1:9999'))
            self.assertTrue(handler.local_name('localhost:80'))
            self.assertFalse(handler.local_name('shop-pc:8765'))
            server.LAN = True
            host = socket.gethostname()
            self.assertTrue(handler.local_name(host + ':8765'))
            self.assertTrue(handler.local_name('192.168.1.20:8765'))
            self.assertFalse(handler.local_name('8.8.8.8:8765'))
            self.assertFalse(handler.local_name(host + ':80'))
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
                self.assertIn('shop network only', status['warning'].casefold())
                self.assertEqual(status['version'], '1.0.0-rc.1')
                self.assertIn(r'\\ONYX\EPSON SureColor S80600 ONYX Input', status['hotFolderDefault'])
            finally:
                server.WORK, server.PORT, server.HOST, server.LAN = old

    def test_installer_script_matches_the_shop_server(self):
        root = Path(__file__).resolve().parents[1]
        version = json.loads((root / 'version.json').read_text(encoding='utf-8'))['version']
        script = (root / 'installer' / 'eznest.iss').read_text(encoding='utf-8')
        install = (root / 'installer' / 'install-shop.ps1').read_text(encoding='utf-8')
        server_cmd = (root / 'eznest-server.cmd').read_text(encoding='utf-8')
        build = (root / 'build_windows.py').read_text(encoding='utf-8')
        self.assertIn(f'#define MyAppVersion "{version}"', script)
        self.assertIn(r'{autopf}\eznest', script)
        self.assertIn('{commondesktop}', script)
        self.assertIn('schtasks.exe', script)
        self.assertIn('ONSTART', install)
        self.assertIn('schtasks.exe', install)
        self.assertIn('profile=private', install)
        self.assertIn(r'C:\ONYX\EPSON SureColor S80600 ONYX Input', install)
        self.assertIn('--web --no-browser', server_cmd)
        self.assertIn(r'%ProgramData%\eznest', server_cmd)
        self.assertIn('ISCC', build)
        self.assertIn('eznest-server.cmd', build)


if __name__ == '__main__':
    unittest.main()
