"""Helpers for shop update manifest tests.

The key file is a published test vector. It is not the release signing key.
"""
import hashlib
import json
from pathlib import Path

import update_manifest

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'update_manifest_test_key.txt'


def load_test_key():
    text = FIXTURE.read_text(encoding='utf-8')
    if 'TEST ONLY' not in text.splitlines()[0]:
        raise AssertionError('Mark the test key before using it.')
    public = seed = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('public '):
            public = line.split(' ', 1)[1]
        elif line.startswith('seed '):
            seed = bytes.fromhex(line.split(' ', 1)[1])
    if not public or seed is None or len(seed) != 32:
        raise AssertionError('The test key file is incomplete.')
    return public, seed


PUBLIC, SEED = load_test_key()


def signed_document(payload, version, asset, *, schema=False, signature=None):
    document = update_manifest.sign_manifest(
        SEED,
        version=version,
        asset=asset,
        sha256=hashlib.sha256(payload).hexdigest(),
        schema_change=schema,
    )
    if signature is not None:
        document = {'manifest': document['manifest'], 'signature': signature}
    return document


def manifest_bytes(document):
    return (json.dumps(document, indent=2) + '\n').encode('utf-8')


def manifest_release_asset(download_url):
    manifest_url = download_url.rsplit('/', 1)[0] + '/' + update_manifest.ASSET
    return manifest_url, {'name': update_manifest.ASSET, 'browser_download_url': manifest_url}
