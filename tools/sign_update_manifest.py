"""Create an offline shop-update signing key and sign a manifest.

The private key stays outside this repository. The app pins only the public key.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import shop_deploy
import update_manifest


def _outside_repository(path):
    root = Path(__file__).resolve().parents[1]
    original = Path(path).expanduser()
    if original.is_symlink():
        raise ValueError('Choose a private key path outside this repository.')
    candidate = original.resolve()
    if candidate == root or root in candidate.parents:
        raise ValueError('Choose a private key path outside this repository.')
    return candidate


def _regular_file(path, message):
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(message)
    return candidate


def _labeled(path, label):
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError as error:
        raise ValueError('The key file is not usable.') from error
    prefix = label + ' '
    found = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith(prefix):
            found.append(line[len(prefix):].strip())
    if len(found) != 1 or not found[0]:
        raise ValueError('The key file is not usable.')
    return found[0]


def _seed(path):
    try:
        seed = bytes.fromhex(_labeled(path, 'seed'))
    except ValueError as error:
        raise ValueError('The key file is not usable.') from error
    if len(seed) != 32:
        raise ValueError('The key file is not usable.')
    return seed


def _public(path):
    text = _labeled(path, 'public').lower()
    if len(text) != 64 or any(character not in '0123456789abcdef' for character in text):
        raise ValueError('The key file is not usable.')
    return text


def _version(version):
    if not isinstance(version, str) or not version or version[0] in 'vV':
        raise ValueError('Use the version from version.json, without a leading v.')
    try:
        shop_deploy._numbers(version)
    except ValueError as error:
        raise ValueError('Use the version from version.json, without a leading v.') from error


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_key(private, public):
    private = _outside_repository(private)
    public = Path(public).expanduser()
    if public.is_symlink():
        raise ValueError('Write the public key to a regular file.')
    public = public.resolve()
    if private.exists():
        raise ValueError('That private key file already exists.')
    if public == private:
        raise ValueError('Write the public key to a different file.')
    seed = update_manifest.generate_seed()
    public_key = update_manifest.public_hex(seed)
    private.parent.mkdir(parents=True, exist_ok=True)
    temporary = private.with_suffix(private.suffix + '.tmp')
    temporary.write_text(
        '# eznest offline update signing key\n'
        '# Keep this file offline. Do not commit it.\n'
        f'seed {seed.hex()}\n',
        encoding='utf-8',
    )
    os.chmod(temporary, 0o600)
    temporary.replace(private)
    os.chmod(private, 0o600)
    public.parent.mkdir(parents=True, exist_ok=True)
    public.write_text(
        '# eznest update manifest public key\n'
        f'public {public_key}\n',
        encoding='utf-8',
    )
    print(public_key)
    print('Copy that public key into update_manifest.PUBLIC_KEY in a reviewed change.')
    print('Keep the private key offline. Do not commit it.')


def write_manifest(private, release_file, version, out, schema_change):
    _version(version)
    release_file = _regular_file(release_file, 'Choose the release file to sign.')
    document = update_manifest.sign_manifest(
        _seed(private),
        version=version,
        asset=release_file.name,
        sha256=_sha256(release_file),
        schema_change=True if schema_change else False,
    )
    out = Path(out)
    if out.is_symlink():
        raise ValueError('Choose a manifest path that is not a link.')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {out.name}.')


def check_manifest(public, release_file, manifest_path):
    release_file = _regular_file(release_file, 'Choose the release file to check.')
    manifest_path = _regular_file(manifest_path, 'Choose the update manifest to check.')
    try:
        document = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(update_manifest.UNCHECKED) from error
    body = document.get('manifest') if isinstance(document, dict) else None
    if not isinstance(body, dict):
        raise ValueError(update_manifest.UNCHECKED)
    try:
        checked = update_manifest.confirmed_manifest(
            document, version=body.get('version'), asset=release_file.name, public_key=_public(public))
        schema_change = False
    except ValueError as error:
        if str(error) != update_manifest.SCHEMA:
            raise
        schema_change = True
        digest = body.get('sha256')
        if not isinstance(digest, str):
            raise ValueError(update_manifest.UNCHECKED) from error
        checked = {'sha256': digest.strip().lower()}
    actual = _sha256(release_file)
    if len(checked['sha256']) != len(actual) or not hmac.compare_digest(checked['sha256'], actual):
        raise ValueError('The file does not match the manifest.')
    if schema_change:
        print('Manifest checked. This release is marked as a database change. The updater will not install it.')
        return
    print('Manifest checked.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sign or check a shop update manifest offline.')
    commands = parser.add_subparsers(dest='command', required=True)

    keygen = commands.add_parser('keygen', help='Write a new signing key outside this repository.')
    keygen.add_argument('--private', required=True, type=Path)
    keygen.add_argument('--public', required=True, type=Path)

    sign = commands.add_parser('sign', help='Sign an update manifest for one release file.')
    sign.add_argument('--private', required=True, type=Path)
    sign.add_argument('--file', required=True, type=Path)
    sign.add_argument('--version', required=True)
    sign.add_argument('--out', required=True, type=Path)
    sign.add_argument('--schema-change', action='store_true')

    verify = commands.add_parser('verify', help='Check a manifest against a public key and a release file.')
    verify.add_argument('--public', required=True, type=Path)
    verify.add_argument('--file', required=True, type=Path)
    verify.add_argument('--manifest', required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == 'keygen':
            write_key(args.private, args.public)
        elif args.command == 'sign':
            write_manifest(args.private, args.file, args.version, args.out, args.schema_change)
        else:
            check_manifest(args.public, args.file, args.manifest)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
