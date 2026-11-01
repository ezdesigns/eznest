"""Disposable CI-only Mac signing; private material is removed before acceptance."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macos_service_config import version_key

TEAM = 'JC6858UYM9'
REQUIRED = ('MACOS_CERTIFICATE_BASE64', 'MACOS_CERTIFICATE_PASSWORD', 'MACOS_APP_IDENTITY',
            'MACOS_INSTALLER_IDENTITY', 'MACOS_NOTARY_KEY_BASE64', 'MACOS_NOTARY_KEY_ID',
            'MACOS_NOTARY_ISSUER_ID')


class ConfigurationError(ValueError):
    pass


def preflight():
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise ConfigurationError('Missing protected release configuration: ' + ', '.join(missing))
    for name, kind in [('MACOS_APP_IDENTITY', 'Application'), ('MACOS_INSTALLER_IDENTITY', 'Installer')]:
        if not re.fullmatch(r'Developer ID ' + kind + r': [^\r\n]+ \(' + TEAM + r'\)', os.environ[name]):
            raise ConfigurationError('Use the approved publisher Developer ID identities.')


def run(args, *, timeout=60, json_output=False):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # security/notarytool diagnostics may contain credentials; retain only static errors.
        raise ValueError('A required signing, notarization or trust command failed.')
    return result.stdout if json_output else result.stdout + result.stderr


def private_file(path, encoded):
    payload = base64.b64decode(encoded, validate=True)
    with path.open('xb') as handle:
        os.chmod(path, 0o600)
        handle.write(payload)


def notarize(path, key, credentials):
    auth = ['--key', key, '--key-id', credentials['MACOS_NOTARY_KEY_ID'],
            '--issuer', credentials['MACOS_NOTARY_ISSUER_ID']]
    submitted = json.loads(run(['xcrun', 'notarytool', 'submit', path, *auth, '--output-format', 'json'], timeout=180, json_output=True))
    identifier = submitted.get('id', '')
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', identifier):
        raise ValueError('Apple did not return a submission ID.')
    # Wait on this submission; never repeatedly submit the same bytes on a timeout.
    print('Apple submission:', identifier)
    response = json.loads(run(['xcrun', 'notarytool', 'wait', identifier, *auth,
                               '--timeout', '20m', '--output-format', 'json'], timeout=1250, json_output=True))
    if response.get('status') != 'Accepted':
        raise ValueError('Apple did not accept the notarization submission.')
    return identifier


def build(out):
    preflight()
    credentials = {name: os.environ.pop(name) for name in REQUIRED}
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_published_macos import runner_guard
    temporary = runner_guard()  # Reject local machines, Intel and pre-macOS 26 before OS writes.
    from build_macos import build as build_app
    from build_macos_package import build as build_package
    from macos_update import verify_package
    out = out.resolve()
    if out.exists() or not out.is_relative_to(temporary) or out == temporary:
        raise ValueError('Use a new dedicated directory in this disposable runner temp.')
    version = json.loads((ROOT / 'version.json').read_text())['version']
    version_key(version)
    out.mkdir()
    old_search = shlex.split(run(['security', 'list-keychains', '-d', 'user']))
    with tempfile.TemporaryDirectory(prefix='eznest-signing-', dir=temporary) as folder:
        folder = Path(folder)
        certificate, key, keychain = folder / 'certificate.p12', folder / 'notary.p8', folder / 'signing.keychain-db'
        password = secrets.token_urlsafe(32)
        private_file(certificate, credentials['MACOS_CERTIFICATE_BASE64'])
        private_file(key, credentials['MACOS_NOTARY_KEY_BASE64'])
        try:
            run(['security', 'create-keychain', '-p', password, keychain])
            run(['security', 'set-keychain-settings', '-lut', '3600', keychain])
            run(['security', 'unlock-keychain', '-p', password, keychain])
            run(['security', 'import', certificate, '-k', keychain, '-P', credentials['MACOS_CERTIFICATE_PASSWORD'],
                 '-T', '/usr/bin/codesign', '-T', '/usr/bin/productsign'])
            run(['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', password, keychain])
            run(['security', 'list-keychains', '-d', 'user', '-s', keychain, *old_search])
            archive = build_app(out / 'application', service_edition=True,
                                codesign_identity=credentials['MACOS_APP_IDENTITY'])
            app = out / 'application/dist/eznest.app'
            app_id = notarize(archive, key, credentials)
            # Apple accepts the ZIP; staple the app itself before wrapping it in the installer.
            run(['xcrun', 'stapler', 'staple', app], timeout=120)
            run(['xcrun', 'stapler', 'validate', app], timeout=120)
            if 'source=Notarized Developer ID' not in run(['spctl', '--assess', '--type', 'execute', '--verbose=2', app]):
                raise ValueError('The application must pass notarized Gatekeeper assessment.')
            unsigned = build_package(app, out / 'package', team_id=TEAM)
            package = out / f'eznest-shop-arm64-{version}.pkg'
            run(['productsign', '--sign', credentials['MACOS_INSTALLER_IDENTITY'], unsigned, package], timeout=300)
            package_id = notarize(package, key, credentials)
            run(['xcrun', 'stapler', 'staple', package], timeout=120)
            run(['xcrun', 'stapler', 'validate', package], timeout=120)
            verify_package(package, TEAM, version)
        finally:
            try:
                run(['security', 'list-keychains', '-d', 'user', '-s', *old_search])
            finally:
                if keychain.exists():
                    run(['security', 'delete-keychain', keychain])
    # No private key or signing credential remains when runtime/browser acceptance starts.
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    info = json.loads((out / 'application/BUILD.json').read_text())
    if info['commit'] != commit or info['architecture'] != 'arm64' or info['sourceDirty']:
        raise ValueError('The Mac build must be clean and match the selected source commit.')
    checksum = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_name(package.name + '.sha256').write_text(checksum + '  ' + package.name + '\n')
    receipt = dict(version=version, commit=commit, architecture='arm64', teamId=TEAM,
                   sha256=checksum, applicationNotarized=True, packageNotarized=True,
                   packageSigned=True, appSubmission=app_id, packageSubmission=package_id)
    (out / 'MACOS-RELEASE.json').write_text(json.dumps(receipt, indent=2) + '\n')
    candidate = temporary / package.name
    if candidate.exists():
        raise ValueError('Do not replace an existing acceptance candidate.')
    shutil.copy2(package, candidate)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
        handle.write('sha256=' + checksum + '\n')


def finalize(out):
    receipt_path = out / 'MACOS-RELEASE.json'
    receipt = json.loads(receipt_path.read_text())
    accepted = json.loads((Path(os.environ['RUNNER_TEMP']) / 'eznest-macos-acceptance.json').read_text())
    if (accepted.get('version') != receipt['version'] or accepted.get('sha256') != receipt['sha256']
            or not all(accepted.get(k) is True for k in
                       ('installed', 'offlineFileFlows', 'persistenceVerified', 'restarted',
                        'sharingOff', 'updatesOff', 'loopbackOnly', 'cleanup'))):
        raise ValueError('Installed Mac acceptance or owned cleanup is incomplete.')
    receipt.update(installed=True, offlineFileFlows=True, restartPersistence=True, cleanup=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('preflight', 'build', 'finalize'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.phase == 'preflight':
        preflight()
    elif args.phase == 'build':
        build(args.out)
    else:
        finalize(args.out)


if __name__ == '__main__':
    try:
        main()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        # Signing tools and malformed inputs may expose secret material in their exceptions.
        print('Mac release failed; verify protected configuration and sanitized CI steps.', file=sys.stderr)
        raise SystemExit(1)
