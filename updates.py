"""Version comparison, changelog, and the tester update check.

The portable app downloads a build only after a manifest or GitHub release
publishes a checksum and an HTTPS URL. Workflow artifacts can carry a manifest
with published set to false; those builds are not offered.
"""
import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, HTTPHandler, HTTPSHandler, HTTPErrorProcessor

from app_info import UPDATE_CHANNEL, VERSION

ROOT = Path(__file__).resolve().parent
REPO = 'ezdesigns/eznest'
RELEASES_URL = f'https://api.github.com/repos/{REPO}/releases?per_page=20'
DEFAULT_MANIFESTS = {
    'beta': f'https://raw.githubusercontent.com/{REPO}/main/updates/beta.json',
    'stable': f'https://raw.githubusercontent.com/{REPO}/main/updates/stable.json',
}
_VERSION = re.compile(r'(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?')
_LOCK = threading.Lock()
_PREPARE = threading.Lock()
_CACHE = {'at': 0.0, 'key': None, 'value': None}
MAX_MANIFEST_BYTES = 1_000_000
MAX_ZIP_BYTES = 800 * 1024 * 1024
CHECK_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 300


class _NoRedirect(HTTPErrorProcessor):
    def http_response(self, request, response):
        return response

    https_response = http_response


def updates_enabled():
    return os.environ.get('EZ_NEST_UPDATES', '1') != '0'


def current_channel():
    override = os.environ.get('EZ_NEST_UPDATE_CHANNEL', '').strip().lower()
    if override in ('stable', 'beta'):
        return override
    return UPDATE_CHANNEL if UPDATE_CHANNEL in ('stable', 'beta') else 'beta'


def parse_version(value):
    match = _VERSION.search(str(value or ''))
    if not match:
        raise ValueError(f'Unrecognized version: {value}')
    core = tuple(int(match.group(index)) for index in range(1, 4))
    pre = tuple(match.group(4).split('.')) if match.group(4) else ()
    text = f'{core[0]}.{core[1]}.{core[2]}' + (f'-{match.group(4)}' if match.group(4) else '')
    return core, pre, text


def _pre_key(pre):
    if not pre:
        return (1,)
    parts = []
    for part in pre:
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return (0, tuple(parts))


def compare(left, right):
    """Return -1 when left is older, 0 when equal, 1 when left is newer."""
    parsed_left, parsed_right = parse_version(left), parse_version(right)
    if parsed_left[0] != parsed_right[0]:
        return -1 if parsed_left[0] < parsed_right[0] else 1
    left_key, right_key = _pre_key(parsed_left[1]), _pre_key(parsed_right[1])
    if left_key == right_key:
        return 0
    return -1 if left_key < right_key else 1


def parse_changelog(text):
    entries = []
    current = None
    for line in text.splitlines():
        if line.startswith('## '):
            if current:
                entries.append(current)
            title = line[3:].strip()
            try:
                version = parse_version(title)[2]
            except ValueError:
                version = ''
            current = {'title': title, 'version': version, 'lines': []}
        elif current is not None and not line.startswith('# '):
            current['lines'].append(line)
    if current:
        entries.append(current)
    for entry in entries:
        while entry['lines'] and not entry['lines'][0].strip():
            entry['lines'].pop(0)
        while entry['lines'] and not entry['lines'][-1].strip():
            entry['lines'].pop()
        entry['body'] = '\n'.join(entry['lines'])
        del entry['lines']
    return entries


def changelog_entries():
    path = ROOT / 'CHANGELOG.md'
    if not path.is_file():
        return []
    return parse_changelog(path.read_text(encoding='utf-8'))


def changelog_notes(version, limit=1500):
    for entry in changelog_entries():
        if entry['version'] == version:
            return entry['body'][:limit]
    return ''


def _is_github(hostname):
    host = (hostname or '').lower()
    return host == 'github.com' or host.endswith('.github.com') or host == 'githubusercontent.com' or host.endswith('.githubusercontent.com')


def _require_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme == 'https' and host:
        return
    if parsed.scheme == 'http' and host in ('127.0.0.1', 'localhost'):
        return
    raise ValueError('Update downloads must use HTTPS.')


def github_token():
    return os.environ.get('EZ_NEST_GITHUB_TOKEN', '').strip() or None


def public_error(error):
    if isinstance(error, HTTPError):
        return f'HTTP {error.code}'
    if isinstance(error, TimeoutError):
        return 'timed out'
    if isinstance(error, URLError):
        if isinstance(error.reason, TimeoutError):
            return 'timed out'
        return 'network unreachable'
    if isinstance(error, ValueError):
        return str(error)[:200]
    return 'update check failed'


def fetch_bytes(url, timeout, limit=MAX_MANIFEST_BYTES, accept=None):
    opener = build_opener(_NoRedirect, HTTPHandler, HTTPSHandler)
    current = url
    token = github_token()
    for _ in range(5):
        _require_url(current)
        headers = {'User-Agent': 'eznest-update'}
        if accept:
            headers['Accept'] = accept
        if token and _is_github(urlparse(current).hostname):
            headers['Authorization'] = f'Bearer {token}'
            headers.setdefault('Accept', 'application/vnd.github+json')
        request = Request(current, headers=headers)
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, 'status', None) or response.getcode()
            if status in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    raise ValueError('Update server redirected without a destination.')
                current = urljoin(current, location)
                continue
            if status != 200:
                raise ValueError(f'HTTP {status}')
            chunks = []
            total = 0
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise ValueError('Update download is larger than this version allows.')
                chunks.append(block)
            return b''.join(chunks)
    raise ValueError('Too many redirects.')


def fetch_json(url, timeout=CHECK_TIMEOUT):
    body = fetch_bytes(url, timeout, limit=MAX_MANIFEST_BYTES)
    try:
        return json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Update manifest was not valid JSON.') from error


def parse_sha256_text(text):
    token = text.strip().split()[0].lower() if text.strip() else ''
    if len(token) != 64 or any(character not in '0123456789abcdef' for character in token):
        raise ValueError('Checksum file is not a SHA-256 hex digest.')
    return token


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_matches(actual, expected):
    actual = actual.lower()
    expected = expected.strip().lower()
    if len(actual) != len(expected) or any(character not in '0123456789abcdef' for character in expected):
        return False
    return hmac.compare_digest(actual, expected)


def _platform(manifest):
    platforms = manifest.get('platforms') if isinstance(manifest, dict) else None
    windows = platforms.get('windows-x64') if isinstance(platforms, dict) else None
    return windows if isinstance(windows, dict) else {}


def usable_manifest(manifest, channel):
    if not isinstance(manifest, dict) or manifest.get('published') is False:
        return False
    manifest_channel = manifest.get('channel') or 'stable'
    if manifest_channel not in ('stable', 'beta'):
        return False
    if channel == 'stable' and manifest_channel != 'stable':
        return False
    try:
        version = parse_version(manifest.get('version'))[2]
    except ValueError:
        return False
    windows = _platform(manifest)
    url, digest = windows.get('url'), windows.get('sha256')
    if not isinstance(url, str) or not isinstance(digest, str):
        return False
    try:
        _require_url(url)
        parse_sha256_text(digest)
    except ValueError:
        return False
    return True


def candidate_from_manifest(manifest, source):
    windows = _platform(manifest)
    version = parse_version(manifest['version'])[2]
    notes = manifest.get('notes') if isinstance(manifest.get('notes'), str) else ''
    filename = windows.get('filename') if isinstance(windows.get('filename'), str) else ''
    return {
        'version': version,
        'channel': manifest.get('channel') or 'stable',
        'source': source,
        'url': windows['url'],
        'sha256': parse_sha256_text(windows['sha256']),
        'notes': notes[:2000],
        'filename': filename,
        'htmlUrl': manifest.get('htmlUrl') if isinstance(manifest.get('htmlUrl'), str) else '',
    }


def _release_channel(release):
    return 'beta' if release.get('prerelease') else 'stable'


def candidates_from_releases(releases, channel):
    if isinstance(releases, dict):
        releases = [releases]
    if not isinstance(releases, list):
        raise ValueError('GitHub release list was not valid.')
    found = []
    for release in releases:
        if not isinstance(release, dict) or release.get('draft'):
            continue
        release_channel = _release_channel(release)
        if channel == 'stable' and release_channel != 'stable':
            continue
        try:
            version = parse_version(release.get('tag_name'))[2]
        except ValueError:
            continue
        assets = {}
        for asset in release.get('assets') or []:
            if isinstance(asset, dict) and isinstance(asset.get('name'), str):
                assets[asset['name']] = asset
        manifest_name = f'manifest-{release_channel}.json'
        if manifest_name in assets or 'manifest.json' in assets:
            asset = assets.get(manifest_name) or assets['manifest.json']
            manifest = fetch_json(asset.get('browser_download_url') or '')
            if usable_manifest(manifest, channel):
                candidate = candidate_from_manifest(manifest, 'github-release')
                candidate['htmlUrl'] = release.get('html_url') or candidate['htmlUrl']
                candidate['version'] = version
                found.append(candidate)
                continue
        zip_name = next((name for name in assets if name.endswith('-windows-x64.zip')), None)
        sha_name = f'{zip_name}.sha256' if zip_name else None
        if not zip_name or sha_name not in assets:
            continue
        digest = parse_sha256_text(fetch_bytes(assets[sha_name]['browser_download_url'], CHECK_TIMEOUT, limit=4096).decode('utf-8', 'replace'))
        url = assets[zip_name].get('browser_download_url')
        _require_url(url)
        body = release.get('body') if isinstance(release.get('body'), str) else ''
        found.append({
            'version': version,
            'channel': release_channel,
            'source': 'github-release',
            'url': url,
            'sha256': digest,
            'notes': body[:2000],
            'filename': zip_name,
            'htmlUrl': release.get('html_url') or '',
        })
    return found


def choose_update(current, channel, candidates):
    usable = []
    for candidate in candidates:
        try:
            if not candidate.get('url') or not candidate.get('sha256'):
                continue
            if candidate.get('channel') == 'beta' and channel == 'stable':
                continue
            if compare(candidate['version'], current) <= 0:
                continue
        except (ValueError, KeyError):
            continue
        usable.append(candidate)
    if not usable:
        return None

    def sort_key(candidate):
        parsed = parse_version(candidate['version'])
        return (parsed[0], _pre_key(parsed[1]), 1 if candidate.get('source') == 'github-release' else 0)

    return max(usable, key=sort_key)


def check_remote(current=None, channel=None):
    current = current or VERSION
    channel = channel or current_channel()
    if not updates_enabled():
        return {'current': current, 'channel': channel, 'enabled': False, 'updateAvailable': False, 'latest': None, 'error': None}
    candidates = []
    errors = []
    reached = False
    override = os.environ.get('EZ_NEST_UPDATE_MANIFEST_URL', '').strip()
    if override:
        loaders = [('manifest', lambda: _manifest_candidate(override, channel))]
    else:
        loaders = [
            ('github-release', lambda: candidates_from_releases(fetch_json(RELEASES_URL), channel)),
            ('manifest', lambda: _manifest_candidate(DEFAULT_MANIFESTS[channel], channel)),
        ]
    for name, loader in loaders:
        try:
            candidates.extend(loader())
            reached = True
        except Exception as error:
            errors.append(f'{name}: {public_error(error)}')
    chosen = choose_update(current, channel, candidates)
    return {
        'current': current,
        'channel': channel,
        'enabled': True,
        'updateAvailable': chosen is not None,
        'latest': chosen['version'] if chosen else None,
        'source': chosen['source'] if chosen else None,
        'url': chosen['url'] if chosen else None,
        'sha256': chosen['sha256'] if chosen else None,
        'notes': chosen['notes'] if chosen else None,
        'filename': chosen['filename'] if chosen else None,
        'htmlUrl': chosen['htmlUrl'] if chosen else None,
        'offerChannel': chosen['channel'] if chosen else None,
        'error': None if chosen or reached or not errors else '; '.join(errors)[:300],
    }


def _manifest_candidate(url, channel):
    manifest = fetch_json(url)
    if not usable_manifest(manifest, channel):
        return []
    return [candidate_from_manifest(manifest, 'manifest')]


def cached_check(force=False):
    import time
    key = (VERSION, current_channel(), os.environ.get('EZ_NEST_UPDATE_MANIFEST_URL', ''), updates_enabled())
    now = time.time()
    with _LOCK:
        if not force and _CACHE['value'] is not None and _CACHE['key'] == key and now - _CACHE['at'] < 900:
            return dict(_CACHE['value'])
    value = check_remote()
    with _LOCK:
        _CACHE.update(at=now, key=key, value=value)
    return dict(value)


def updates_dir(data_dir):
    path = Path(data_dir) / 'updates'
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path):
    file = Path(path)
    if not file.is_file():
        return None
    try:
        return json.loads(file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temporary.replace(path)


def pending_state(data_dir):
    pending = read_json(updates_dir(data_dir) / 'pending.json')
    if not pending or not pending.get('verified'):
        return None
    zip_path = Path(pending.get('zip', ''))
    if not zip_path.is_file() or not checksum_matches(sha256_file(zip_path), pending.get('sha256', '')):
        return None
    return pending


def local_state(data_dir, install_root):
    import updater
    pending = pending_state(data_dir)
    rollback = read_json(updates_dir(data_dir) / 'rollback.json')
    return {
        'applySupported': updater.apply_supported(install_root),
        'staged': pending is not None,
        'stagedVersion': pending.get('version') if pending else None,
        'applyOnRestart': bool(pending and pending.get('applyOnRestart')),
        'rollback': rollback if isinstance(rollback, dict) else None,
    }


def status(data_dir, install_root, force=False):
    remote = cached_check(force=force)
    remote.update(local_state(data_dir, install_root))
    return remote


def _filename(candidate):
    name = candidate.get('filename') or ''
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        return f"eznest-{candidate['version']}-windows-x64.zip"
    return name


def prepare(data_dir, install_root, when, remote=None):
    import updater
    with _PREPARE:
        return _prepare(data_dir, install_root, when, remote, updater)


def _prepare(data_dir, install_root, when, remote, updater):
    if when not in ('now', 'restart'):
        raise ValueError('Choose Update now or install on the next restart.')
    if not updater.apply_supported(install_root):
        raise ValueError('Open the portable eznest.exe to download and install updates.')
    remote = remote or cached_check(force=True)
    if not remote.get('updateAvailable'):
        raise ValueError(remote.get('error') or 'No newer Ez Nest build is available.')
    candidate = {
        'version': remote['latest'],
        'sha256': remote['sha256'],
        'url': remote['url'],
        'filename': remote.get('filename') or '',
        'channel': remote.get('offerChannel') or remote.get('channel'),
        'notes': remote.get('notes') or '',
    }
    directory = updates_dir(data_dir)
    destination = directory / 'incoming' / _filename(candidate)
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = pending_state(data_dir)
    if not (existing and existing.get('version') == candidate['version'] and existing.get('sha256') == candidate['sha256']):
        partial = destination.with_suffix(destination.suffix + '.partial')
        try:
            payload = fetch_bytes(candidate['url'], DOWNLOAD_TIMEOUT, limit=MAX_ZIP_BYTES)
        except Exception as error:
            partial.unlink(missing_ok=True)
            raise ValueError(f'The update download did not finish ({public_error(error)}).') from error
        if not checksum_matches(hashlib.sha256(payload).hexdigest(), candidate['sha256']):
            partial.unlink(missing_ok=True)
            raise ValueError('The downloaded update does not match its checksum. It was not installed.')
        partial.write_bytes(payload)
        partial.replace(destination)
    pending = {
        'version': candidate['version'],
        'sha256': candidate['sha256'],
        'zip': str(destination),
        'verified': True,
        'channel': candidate['channel'],
        'notes': candidate['notes'],
        'filename': destination.name,
        'applyOnRestart': True,
        'applyNow': when == 'now',
        'openBrowser': True,
    }
    write_json(directory / 'pending.json', pending)
    result = dict(remote)
    result.update(local_state(data_dir, install_root))
    result['prepared'] = True
    result['when'] = when
    return result


def begin_apply(data_dir, install_root):
    import updater
    if not updater.apply_supported(install_root):
        raise ValueError('Open the portable eznest.exe to install updates.')
    pending = pending_state(data_dir)
    if not pending:
        raise ValueError('Download the update before installing it.')
    pending['applyNow'] = True
    pending['applyOnRestart'] = True
    write_json(updates_dir(data_dir) / 'pending.json', pending)
    updater.spawn_helper(install_root, Path(data_dir), os.getpid())
    return {'ok': True, 'restarting': True, 'version': pending['version']}


def write_ci_manifest(path, version, sha256, filename, channel='beta', notes='', size=None):
    if channel not in ('beta', 'stable'):
        raise ValueError('Choose the beta or stable channel.')
    parse_version(version)
    digest = parse_sha256_text(sha256)
    manifest = {
        'channel': channel,
        'version': parse_version(version)[2],
        'published': False,
        'notes': notes[:2000],
        'approval': 'This manifest is a workflow artifact. Ez Nest does not install it until a release is approved and published.',
        'platforms': {
            'windows-x64': {
                'filename': filename,
                'url': None,
                'sha256': digest,
                'size': size,
            }
        }
    }
    path = Path(path)
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Write the unpublished Ez Nest update manifest')
    parser.add_argument('--write-manifest', action='store_true')
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--channel', default='beta')
    parser.add_argument('--version')
    parser.add_argument('--notes-file', type=Path)
    args = parser.parse_args(argv)
    if not args.write_manifest:
        parser.print_help()
        return 0
    if not args.zip or not args.out or not args.version:
        raise ValueError('Manifest writing needs --zip, --out and --version.')
    digest = sha256_file(args.zip)
    notes = ''
    if args.notes_file and args.notes_file.is_file():
        notes = changelog_notes(parse_version(args.version)[2]) or args.notes_file.read_text(encoding='utf-8')[:1500]
    else:
        notes = changelog_notes(parse_version(args.version)[2])
    write_ci_manifest(args.out, args.version, digest, args.zip.name, args.channel, notes, args.zip.stat().st_size)
    sha_path = args.out.parent / f'{args.zip.name}.sha256'
    sha_path.write_text(f'{digest}  {args.zip.name}\n', encoding='utf-8')
    print(args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
