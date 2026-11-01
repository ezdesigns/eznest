"""Plan and atomically publish a checked, dual-platform release. No asset overwrites."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macos_service_config import version_key

REPO = 'ezdesigns/eznest'
SHA = re.compile(r'[0-9a-f]{40}')


class ReleaseError(ValueError):
    pass


class GitHub:
    def request(self, method, path, data=None, *, missing=False):
        args = ['gh', 'api', '--method', method, path]
        if data is not None:
            args += ['--input', '-']
        result = subprocess.run(args, input=None if data is None else json.dumps(data),
                                capture_output=True, text=True)
        if result.returncode:
            if missing and 'HTTP 404' in result.stderr:
                return None
            raise ReleaseError(f'GitHub API failed: {method} {path}')
        return json.loads(result.stdout) if result.stdout.strip() else None

    def releases(self):
        for page in range(1, 101):
            rows = self.request('GET', f'repos/{REPO}/releases?per_page=100&page={page}')
            yield from rows
            if len(rows) < 100:
                return
        raise ReleaseError('Release history exceeds the bounded scan; inspect it before publishing.')

    def tag_commit(self, tag):
        ref = self.request('GET', f'repos/{REPO}/git/ref/tags/{quote(tag, safe="")}', missing=True)
        if not ref:
            return None
        obj = ref['object']
        for _ in range(8):
            if obj['type'] == 'commit' and SHA.fullmatch(obj['sha']):
                return obj['sha']
            if obj['type'] != 'tag' or not SHA.fullmatch(obj['sha']):
                break
            obj = self.request('GET', f'repos/{REPO}/git/tags/{obj["sha"]}')['object']
        raise ReleaseError('The existing release tag does not resolve to a bounded commit.')


def trusted_run(event):
    run = event.get('workflow_run', {})
    if (event.get('repository', {}).get('full_name') != REPO
            or run.get('head_repository', {}).get('full_name') != REPO
            or run.get('event') != 'push' or run.get('head_branch') != 'main'
            or run.get('path') != '.github/workflows/test.yml'
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or not isinstance(run.get('head_sha'), str) or not SHA.fullmatch(run['head_sha'])):
        raise ReleaseError('Only successful Tests on this repository main push may release.')
    return run['head_sha']


def plan(github, event, version):
    commit = trusted_run(event)
    version_key(version)
    tag = 'v' + version
    tip = github.request('GET', f'repos/{REPO}/git/ref/heads/main')['object']['sha']
    result = {'should_release': False, 'sha': commit, 'version': version, 'tag': tag}
    if tip != commit:
        return {**result, 'reason': 'A newer main commit supersedes this CI run.'}
    existing = None
    published = []
    for release in github.releases():
        if release['tag_name'] == tag:
            existing = release
        if not release.get('draft'):
            try:
                published.append(version_key(release['tag_name'].removeprefix('v')))
            except ValueError:
                pass
    if existing and not existing.get('draft'):
        return {**result, 'reason': 'This version is already published; nothing is overwritten.'}
    if existing and existing.get('target_commitish') != commit:
        raise ReleaseError('An existing draft belongs to another commit; preserve it and choose a new version.')
    tagged = github.tag_commit(tag)
    if tagged and tagged != commit:
        return {**result, 'reason': 'This version tag already belongs to another commit.'}
    if published and version_key(version) <= max(published):
        raise ReleaseError('version.json must be newer than every published application version.')
    return {**result, 'should_release': True, 'reason': 'New version, checked main commit.'}


def digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 300_000_000:
        raise ReleaseError('A release asset is not a bounded regular file.')
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def verify_sidecar(path):
    sidecar = path.with_name(path.name + '.sha256')
    digest(sidecar)
    words = sidecar.read_text().split()
    if words != [digest(path), path.name]:
        raise ReleaseError(f'Invalid final checksum for {path.name}.')
    return sidecar


def checked_assets(directory, version, commit):
    directory = Path(directory)
    win, mac = directory / 'windows', directory / 'macos'
    if any(folder.is_symlink() or not folder.is_dir() for folder in (directory, win, mac)):
        raise ReleaseError('Use intact platform artifact directories.')
    exe = win / 'eznest-setup.exe'
    pkg = mac / f'eznest-shop-arm64-{version}.pkg'
    pins = [(win / 'BUILD.json', exe), (mac / 'MACOS-RELEASE.json', pkg)]
    for pin, binary in pins:
        digest(pin)
        receipt = json.loads(pin.read_text())
        if (receipt.get('version') != version or receipt.get('commit') != commit
                or receipt.get('sha256') != digest(binary)):
            raise ReleaseError(f'Version, commit or checksum mismatch: {pin.name}.')
        if binary == pkg and (receipt.get('architecture') != 'arm64'
                or not all(receipt.get(key) is True for key in
                           ('applicationNotarized', 'packageNotarized', 'packageSigned',
                            'installed', 'offlineFileFlows', 'restartPersistence', 'cleanup'))):
            raise ReleaseError('Signed Mac acceptance evidence is incomplete.')
    manifest = win / 'manifest.json'
    digest(manifest)
    info = json.loads(manifest.read_text())
    if (info.get('version') != version or info.get('filename') != exe.name
            or info.get('sha256') != digest(exe)):
        raise ReleaseError('Windows update manifest does not match the built installer.')
    return [exe, verify_sidecar(exe), pins[0][0], manifest,
            pkg, verify_sidecar(pkg), pins[1][0]]


def publish(github, event, version, directory, *, upload=None):
    # Recheck the trusted CI/main/version after both builds, before any remote mutation.
    state = plan(github, event, version)
    if not state['should_release']:
        return state
    files = checked_assets(directory, version, state['sha'])
    tag = state['tag']
    release = next((r for r in github.releases() if r['tag_name'] == tag), None)
    if release is None:
        notes = (f'EZNest {version}\n\nSource: `{state["sha"]}`.\n\n'
                 'Windows x64: unsigned preview; fresh-install checks passed.\n'
                 'Mac: Apple Silicon/macOS 26 experimental preview, new test installations only. '
                 'Developer ID signed, notarized and stapled; local SVG/PDF export, restart persistence '
                 'and owned VM cleanup checked. Keep updates off. Closing the browser leaves the service running.\n\n'
                 'Live OUTPUT pairing/revocation remains a separate owner-run acceptance. '
                 'Production RIP/cutting, signed upgrades/rollback, reboot/logout longevity, Intel Macs '
                 'and normal end-user uninstallation are not established by this release workflow.\n\n'
                 f'[Changelog](https://github.com/{REPO}/blob/{state["sha"]}/CHANGELOG.md)')
        release = github.request('POST', f'repos/{REPO}/releases', {
            'tag_name': tag, 'target_commitish': state['sha'], 'name': tag,
            'draft': True, 'prerelease': '-' in version, 'body': notes})
    if not release.get('draft') or release.get('target_commitish') != state['sha']:
        raise ReleaseError('Release changed during publication; nothing is overwritten.')
    release_id = release['id']
    path = f'repos/{REPO}/releases/{release_id}/assets?per_page=100'
    present = {asset['name']: asset for asset in github.request('GET', path)}
    expected_names = {file.name for file in files}
    if set(present) - expected_names:
        raise ReleaseError('The draft contains unchecked assets; preserve it for manual inspection.')
    for file in files:
        expected = 'sha256:' + digest(file)
        if file.name in present:
            if present[file.name].get('digest') != expected:
                raise ReleaseError(f'Existing asset differs: {file.name}; it was preserved.')
            continue
        if upload is None:
            subprocess.run(['gh', 'release', 'upload', tag, str(file), '--repo', REPO], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            upload(tag, file)
    observed = {a['name']: a for a in github.request('GET', path)}
    if set(observed) != expected_names:
        raise ReleaseError('Unexpected or missing uploaded assets; release remains a draft.')
    for file in files:
        if observed.get(file.name, {}).get('digest') != 'sha256:' + digest(file):
            raise ReleaseError('Uploaded asset verification failed; release remains a draft.')
    # Published versions are immutable for this workflow. Missing/different assets never get clobbered.
    github.request('PATCH', f'repos/{REPO}/releases/{release_id}', {
        'draft': False, 'prerelease': '-' in version,
        'make_latest': 'false' if '-' in version else 'true'})
    return {**state, 'reason': 'Both checked platform artifacts published.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('plan', 'publish'))
    parser.add_argument('--assets', type=Path)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_run':
        raise ReleaseError('Run only in the checked release workflow.')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    version = json.loads((ROOT / 'version.json').read_text())['version']
    api = GitHub()
    state = plan(api, event, version) if args.phase == 'plan' else publish(api, event, version, args.assets)
    if args.phase == 'plan':
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            for key in ('should_release', 'sha', 'version', 'tag'):
                value = str(state[key]).lower() if isinstance(state[key], bool) else state[key]
                handle.write(f'{key}={value}\n')
    print(state['reason'])


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Release stopped: {error if isinstance(error, ReleaseError) else "validation or tool failure"}', file=sys.stderr)
        raise SystemExit(1)
