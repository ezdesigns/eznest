"""Shop updates require a signed manifest before they are staged."""
import opt_out
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import installer_update
import shop_deploy
import update_manifest
import update_manifest_support
from test_shop_deploy import ScriptedOpener
from tools.sign_update_manifest import main as sign_main

# RFC 8032 section 7.1.
_VECTORS = (
    ('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60',
     'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a',
     '',
     'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'),
    ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb',
     '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c',
     '72',
     '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00'),
    ('c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7',
     'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025',
     'af82',
     '6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a'),
)


class UpdateManifestTests(unittest.TestCase):
    def test_signature_matches_the_published_test_vectors(self):
        self.assertEqual(
            update_manifest._encode(update_manifest._base_point()).hex(),
            '5866666666666666666666666666666666666666666666666666666666666666')
        for seed_hex, public, message, signature in _VECTORS:
            seed = bytes.fromhex(seed_hex)
            body = bytes.fromhex(message)
            self.assertEqual(update_manifest.public_hex(seed), public)
            self.assertEqual(update_manifest.sign(seed, body).hex(), signature)
            self.assertTrue(update_manifest.verify(public, body, signature))
            flipped = ('0' if signature[0] != '0' else '1') + signature[1:]
            self.assertFalse(update_manifest.verify(public, body, flipped))

    def test_pinned_key_is_not_the_test_key(self):
        text = update_manifest_support.FIXTURE.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# TEST ONLY'))
        self.assertNotIn(update_manifest.PUBLIC_KEY, text)
        self.assertNotEqual(update_manifest.PUBLIC_KEY, update_manifest_support.PUBLIC)
        self.assertIsNotNone(update_manifest._decode(bytes.fromhex(update_manifest.PUBLIC_KEY)))
        document = update_manifest_support.signed_document(b'abc', '1.2.3', 'eznest-setup.exe')
        with self.assertRaisesRegex(ValueError, 'could not be checked'):
            update_manifest.confirmed_manifest(document, version='1.2.3', asset='eznest-setup.exe')

    def shop(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shop_deploy.save_shop(root, False, False, updates=True)
        return root

    def pages(self, version, asset, payload, *, manifest_payload=None, schema=False, signature=None,
              manifest_version=None, sidecar_digest=None, include_manifest=True):
        source = payload if manifest_payload is None else manifest_payload
        signed_version = version if manifest_version is None else manifest_version
        url = f'https://github.com/ezdesigns/eznest/releases/download/v{version}/{asset}'
        assets = [{'name': asset, 'browser_download_url': url}]
        pages = {url: payload}
        if sidecar_digest is not None:
            sha_url = url + '.sha256'
            assets.append({'name': asset + '.sha256', 'browser_download_url': sha_url})
            pages[sha_url] = f'{sidecar_digest}  {asset}\n'.encode()
        if include_manifest:
            manifest_url, entry = update_manifest_support.manifest_release_asset(url)
            document = update_manifest_support.signed_document(
                source, signed_version, asset, schema=schema, signature=signature)
            assets.append(entry)
            pages[manifest_url] = update_manifest_support.manifest_bytes(document)
        pages[shop_deploy.RELEASE_API] = json.dumps([{'tag_name': 'v' + version, 'assets': assets}]).encode()
        return pages

    def pull(self, root, pages):
        return shop_deploy.pull_latest(root, '1.0.0', opener=ScriptedOpener(pages))

    def peek(self, root, pages):
        return shop_deploy.peek_latest(root, '1.0.0', opener=ScriptedOpener(pages))

    def test_checked_manifest_stages_the_download(self):
        payload = b'MZ-checked'
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            result = self.pull(root, self.pages('2.0.0', 'eznest-setup.exe', payload))
            self.assertTrue(result['staged'])
            self.assertEqual(Path(result['path']).read_bytes(), payload)
            pending = installer_update.pending_state(root)
            self.assertEqual(pending['sha256'], hashlib.sha256(payload).hexdigest())
            self.assertEqual(pending['manifest']['version'], '2.0.0')
            self.assertFalse(pending['manifest']['schemaChange'])
            self.assertTrue(self.peek(root, self.pages('2.0.0', 'eznest-setup.exe', payload))['updateAvailable'])

    def test_bad_signature_is_refused(self):
        payload = b'MZ-checked'
        signature = update_manifest_support.signed_document(payload, '2.0.0', 'eznest-setup.exe')['signature']
        flipped = ('0' if signature[0] != '0' else '1') + signature[1:]
        digest = hashlib.sha256(payload).hexdigest()
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            pages = self.pages('2.0.0', 'eznest-setup.exe', payload, signature=flipped, sidecar_digest=digest)
            with self.assertRaisesRegex(ValueError, 'could not be checked'):
                self.pull(root, pages)
            self.assertFalse((root / 'updates').exists())
            peeked = self.peek(root, pages)
            self.assertFalse(peeked['updateAvailable'])
            self.assertIn('could not be checked', peeked['message'])

    def test_download_must_match_the_signed_manifest(self):
        original, tampered = b'MZ-checked', b'MZ-changed'
        sidecar = hashlib.sha256(tampered).hexdigest()
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            pages = self.pages('2.0.0', 'eznest-setup.exe', tampered, manifest_payload=original, sidecar_digest=sidecar)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                self.pull(root, pages)
            self.assertFalse(any(path.is_file() and path.read_bytes() == tampered for path in root.rglob('*')))

    def test_missing_manifest_is_refused(self):
        payload = b'MZ-checked'
        digest = hashlib.sha256(payload).hexdigest()
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            pages = self.pages('2.0.0', 'eznest-setup.exe', payload, include_manifest=False, sidecar_digest=digest)
            with self.assertRaisesRegex(ValueError, 'no update manifest'):
                self.pull(root, pages)
            peeked = self.peek(root, pages)
            self.assertFalse(peeked['updateAvailable'])
            self.assertIn('no update manifest', peeked['message'])
            self.assertFalse((root / 'updates').exists())

    def test_schema_change_is_refused(self):
        payload = b'MZ-checked'
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            pages = self.pages('2.0.0', 'eznest-setup.exe', payload, schema=True,
                               sidecar_digest=hashlib.sha256(payload).hexdigest())
            with self.assertRaisesRegex(ValueError, 'shop database'):
                self.pull(root, pages)
            peeked = self.peek(root, pages)
            self.assertFalse(peeked['updateAvailable'])
            self.assertEqual(peeked['message'], update_manifest.SCHEMA)
            self.assertFalse((root / 'updates').exists())

    def test_manifest_for_another_version_is_refused(self):
        payload = b'MZ-checked'
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            pages = self.pages('2.0.0', 'eznest-setup.exe', payload, manifest_version='9.0.0')
            with self.assertRaisesRegex(ValueError, 'could not be checked'):
                self.pull(root, pages)

    def test_changed_staged_manifest_is_ignored(self):
        payload = b'MZ-checked'
        with patch('shop_deploy.sys.platform', 'win32'), patch.dict(os.environ, {'EZ_NEST_UPDATES': '1'}), \
             patch('update_manifest.PUBLIC_KEY', update_manifest_support.PUBLIC):
            root = self.shop()
            self.pull(root, self.pages('2.0.0', 'eznest-setup.exe', payload))
            path = root / 'updates' / 'pending.json'
            pending = json.loads(path.read_text(encoding='utf-8'))
            signature = pending['manifest']['signature']
            pending['manifest']['signature'] = ('0' if signature[0] != '0' else '1') + signature[1:]
            path.write_text(json.dumps(pending), encoding='utf-8')
            self.assertIsNone(installer_update.pending_state(root))

    def run_sign(self, args):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = sign_main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_helper_writes_a_key_outside_the_repository_and_signs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private, public = root / 'eznest-update.key', root / 'eznest-update.pub'
            code, output, errors = self.run_sign(['keygen', '--private', str(private), '--public', str(public)])
            self.assertEqual(code, 0, errors)
            self.assertIn('Do not commit it.', output)
            if os.name != 'nt':
                self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            again, _, errors = self.run_sign(['keygen', '--private', str(private), '--public', str(public)])
            self.assertEqual(again, 1)
            self.assertIn('already exists', errors)
            release = root / 'eznest-shop-windows.zip'
            release.write_bytes(b'zip-bytes')
            manifest = root / 'update-manifest.json'
            code, _, errors = self.run_sign(['sign', '--private', str(private), '--file', str(release), '--version', '1.2.3', '--out', str(manifest)])
            self.assertEqual(code, 0, errors)
            code, output, errors = self.run_sign(['verify', '--public', str(public), '--file', str(release), '--manifest', str(manifest)])
            self.assertEqual(code, 0, errors)
            self.assertIn('Manifest checked.', output)
            document = json.loads(manifest.read_text(encoding='utf-8'))
            public_key = public.read_text(encoding='utf-8').split()[-1]
            checked = update_manifest.confirmed_manifest(
                document, version='1.2.3', asset=release.name, public_key=public_key)
            self.assertEqual(checked['sha256'], hashlib.sha256(b'zip-bytes').hexdigest())
            with self.assertRaisesRegex(ValueError, 'could not be checked'):
                update_manifest.confirmed_manifest(document, version='1.2.3', asset=release.name)
            code, _, errors = self.run_sign(['sign', '--private', str(private), '--file', str(release), '--version', 'v1.2.3', '--out', str(manifest)])
            self.assertEqual(code, 1)
            self.assertIn('without a leading v', errors)
            code, _, errors = self.run_sign(['sign', '--private', str(private), '--file', str(release), '--version', '1.2.4', '--schema-change', '--out', str(manifest)])
            self.assertEqual(code, 0, errors)
            code, output, errors = self.run_sign(['verify', '--public', str(public), '--file', str(release), '--manifest', str(manifest)])
            self.assertEqual(code, 0, errors)
            self.assertIn('database change', output)
            self.assertIn('will not install', output)

    def test_helper_refuses_a_private_key_inside_the_repository(self):
        repo = Path(__file__).resolve().parents[1]
        private = repo / 'eznest-update.key'
        public = repo / 'eznest-update.pub'
        self.assertFalse(private.exists())
        code, _, errors = self.run_sign(['keygen', '--private', str(private), '--public', str(public)])
        self.assertEqual(code, 1)
        self.assertIn('outside this repository', errors)
        self.assertFalse(private.exists())
        self.assertFalse(public.exists())


if __name__ == '__main__':
    unittest.main()
