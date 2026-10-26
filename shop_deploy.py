"""Shop-server install choices: one computer, many browsers.

LAN binding, the EZ Designs preset, and release checks live here so the
nest, the file import, and the gear can stay separate.
"""
import hmac
import io
import ipaddress
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

# Today's EZ Designs shop. A preset the operator can apply. Nothing is connected until they save.
EZ_PRESET = {
    'name': 'EZ Designs',
    'printer': 'Epson SureColor S80600',
    'units': 'in',
    'thru': 'CutContour_Thru-cut',
    'kiss': 'CutContour_Kiss-cut',
    'hotFolderLabel': 'EPSON SureColor S80600 ONYX Input',
    'localHotFolder': r'C:\ONYX\EPSON SureColor S80600 ONYX Input',
    'shareHotFolder': r'\\ONYX\EPSON SureColor S80600 ONYX Input',
}
DEFAULT_REPO = 'ezdesigns/eznest'
RELEASE_API = f'https://api.github.com/repos/{DEFAULT_REPO}/releases?per_page=20'
WARNING = 'Anyone on the shop LAN can Send to ONYX. Do not share this network with guest WiFi.'
OUTPUT_NOTE = 'Off. Nothing is sent. If you turn this on later, only the machine list and free capacity would be shared, and only after you opt in.'
MAX_RELEASE_BYTES = 300_000_000
_REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
SHOP_UNITS = ('in', 'mm', 'cm')
REDIRECT_HOSTS = {
    'github.com',
    'api.github.com',
    'objects.githubusercontent.com',
    'release-assets.githubusercontent.com',
    'github-releases.githubusercontent.com',
}


def default_hot_folder(onyx_pc):
    """The EZ Designs preset path. The shop saves a path on first run."""
    return EZ_PRESET['localHotFolder'] if onyx_pc else EZ_PRESET['shareHotFolder']


def _clip(value, limit):
    if not isinstance(value, str):
        return ''
    text = value.strip()
    if len(text) > limit or any(ord(char) < 32 for char in text):
        return ''
    return text


def _https(url):
    parsed = urlparse(url or '')
    return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password


def data_directory(package_root, data_dir=None, frozen=False, program_files=None, program_data=None):
    if data_dir:
        return Path(data_dir)
    root = Path(package_root)
    if frozen and program_files:
        try:
            if root.resolve().is_relative_to(Path(program_files).resolve()):
                return Path(program_data or r'C:\ProgramData') / 'eznest'
        except (OSError, ValueError):
            pass
    return root / ('data' if frozen else '.local')


def load_shop(directory):
    path = Path(directory) / 'shop.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    units = data.get('units') if data.get('units') in SHOP_UNITS else 'in'
    return {
        'onyxPc': data.get('onyxPc') is True,
        'lan': data.get('lan') is True,
        'updates': data.get('updates') is not False,
        'channel': 'test' if data.get('channel') == 'test' else 'stable',
        'outputNetwork': data.get('outputNetwork') is True,
        'setupComplete': data.get('setupComplete') is True,
        'printer': _clip(data.get('printer'), 80),
        'units': units,
        'thru': _clip(data.get('thru'), 80),
        'kiss': _clip(data.get('kiss'), 80),
        'hotFolder': _clip(data.get('hotFolder'), 400),
    }


def save_shop(directory, onyx_pc, lan, updates=None, **fields):
    current = load_shop(directory)
    if updates is None:
        updates = current['updates']
    channel = fields.get('channel', current['channel'])
    units = fields.get('units', current['units'])
    payload = {
        'onyxPc': bool(onyx_pc),
        'lan': bool(lan),
        'updates': bool(updates),
        'channel': 'test' if channel == 'test' else 'stable',
        'outputNetwork': current['outputNetwork'] if 'outputNetwork' not in fields else fields.get('outputNetwork') is True,
        'setupComplete': current['setupComplete'] if 'setupComplete' not in fields else fields.get('setupComplete') is True,
        'printer': current['printer'] if 'printer' not in fields else _clip(fields.get('printer'), 80),
        'units': units if units in SHOP_UNITS else 'in',
        'thru': current['thru'] if 'thru' not in fields else _clip(fields.get('thru'), 80),
        'kiss': current['kiss'] if 'kiss' not in fields else _clip(fields.get('kiss'), 80),
        'hotFolder': current['hotFolder'] if 'hotFolder' not in fields else _clip(fields.get('hotFolder'), 400),
    }
    path = Path(directory) / 'shop.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return load_shop(directory)


def output_network_status(saved):
    """The switch is stored. It does not open a connection or send a shop file."""
    return {'joined': saved.get('outputNetwork') is True, 'sends': False, 'note': OUTPUT_NOTE}


# Windows getaddrinfo and getfqdn ignore the Python socket timeout and can sit
# on DNS for longer than a minute. The shop page waits on this during boot.
_LOOKUP_TIMEOUT = 1.0
_LOOKUP_TTL = 30.0
_lookup_lock = threading.Lock()
_address_cache = {'expires': 0.0, 'values': []}
_fqdn_cache = {'expires': 0.0, 'value': ''}
_host_cache = {'expires': 0.0, 'value': ''}


def clear_name_cache():
    with _lookup_lock:
        _address_cache['expires'] = 0.0
        _address_cache['values'] = []
        _fqdn_cache['expires'] = 0.0
        _fqdn_cache['value'] = ''
        _host_cache['expires'] = 0.0
        _host_cache['value'] = ''


def _call_within(function, timeout):
    """Return function's result, or None when it is still running after timeout."""
    done = threading.Event()
    box = {}

    def run():
        try:
            box['result'] = function()
        except Exception:
            box['result'] = None
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    if not done.wait(timeout):
        return None
    return box.get('result')


def _remember_address(found, ip):
    if not ip or ip.startswith('127.') or ip in found:
        return
    try:
        if not ipaddress.ip_address(ip).is_private:
            return
    except ValueError:
        return
    found.append(ip)


def _route_address():
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(('192.0.2.1', 9))
            _remember_address(found, probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    return found


def _hostname_ips():
    infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def lan_addresses():
    with _lookup_lock:
        if time.monotonic() < _address_cache['expires']:
            return list(_address_cache['values'])
        found = _route_address()
        looked_up = _call_within(_hostname_ips, _LOOKUP_TIMEOUT)
        for ip in looked_up or []:
            _remember_address(found, ip)
        _address_cache['values'] = list(found)
        _address_cache['expires'] = time.monotonic() + _LOOKUP_TTL
        return list(found)


def _cached_fqdn():
    with _lookup_lock:
        if time.monotonic() < _fqdn_cache['expires']:
            return _fqdn_cache['value']
        looked_up = _call_within(lambda: socket.getfqdn().strip().rstrip('.'), _LOOKUP_TIMEOUT)
        _fqdn_cache['value'] = looked_up or ''
        _fqdn_cache['expires'] = time.monotonic() + _LOOKUP_TTL
        return _fqdn_cache['value']


def host_name():
    """This computer's name, or localhost when Windows is still resolving it."""
    with _lookup_lock:
        if time.monotonic() < _host_cache['expires']:
            return _host_cache['value']
        looked_up = _call_within(lambda: socket.gethostname().strip().rstrip('.'), _LOOKUP_TIMEOUT)
        _host_cache['value'] = looked_up or 'localhost'
        _host_cache['expires'] = time.monotonic() + _LOOKUP_TTL
        return _host_cache['value']


def shop_names():
    host = host_name()
    names = {host.casefold(), host.split('.')[0].casefold()}
    fqdn = _cached_fqdn()
    if fqdn:
        names.add(fqdn.casefold())
    names.update(ip.casefold() for ip in lan_addresses())
    names.discard('')
    return names


def shop_name_allowed(name):
    folded = (name or '').strip().rstrip('.').casefold()
    if not folded or any(mark in folded for mark in '/\\@ '):
        return False
    if folded in shop_names():
        return True
    try:
        address = ipaddress.ip_address(folded)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def _numbers(text):
    main, _, pre = text.strip().lstrip('vV').partition('-')
    parts = []
    for part in main.split('.'):
        if not part.isdigit():
            raise ValueError('Unrecognized version.')
        parts.append(int(part))
    while len(parts) < 3:
        parts.append(0)
    if not pre:
        return tuple(parts), (1,)
    rank = []
    for part in pre.replace('-', '.').split('.'):
        rank.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts), (0, tuple(rank))


def is_newer(latest, current):
    return _numbers(latest) > _numbers(current)


def _data_line(directory, name):
    if not directory:
        return ''
    try:
        return (Path(directory) / name).read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def github_repo(directory=None):
    raw = os.environ.get('EZ_NEST_GITHUB_REPO', '').strip() or _data_line(directory, 'github-repo') or DEFAULT_REPO
    return raw if _REPO.fullmatch(raw) else DEFAULT_REPO


def release_api(directory=None):
    raw = os.environ.get('EZ_NEST_RELEASE_API', '').strip() or _data_line(directory, 'release-api')
    if raw and _https(raw):
        return raw
    return f'https://api.github.com/repos/{github_repo(directory)}/releases?per_page=20'


def issues_url(directory=None):
    raw = os.environ.get('EZ_NEST_ISSUES_URL', '').strip() or _data_line(directory, 'issues-url')
    if raw and _https(raw):
        return raw
    return f'https://github.com/{github_repo(directory)}/issues/new?template=tester-problem.yml'


def repo_for_release(directory=None):
    parsed = urlparse(release_api(directory))
    parts = [part for part in parsed.path.split('/') if part]
    host = (parsed.hostname or '').casefold()
    if host == 'api.github.com' and len(parts) >= 3 and parts[0] == 'repos' and _REPO.fullmatch(f'{parts[1]}/{parts[2]}'):
        return f'{parts[1]}/{parts[2]}'
    return github_repo(directory)


def release_url_allowed(url, download=False, repo=None):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or not parsed.hostname:
        return False
    repo = repo or DEFAULT_REPO
    host = parsed.hostname.casefold()
    if download and host in REDIRECT_HOSTS and host not in ('github.com', 'api.github.com'):
        return True
    if host == 'api.github.com' and parsed.path in (f'/repos/{repo}/releases', f'/repos/{repo}/releases/latest'):
        return not download
    if host == 'github.com' and parsed.path.startswith(f'/{repo}/releases/download/'):
        return True
    if host == 'api.github.com' and parsed.path.startswith(f'/repos/{repo}/releases/assets/'):
        return True
    return False


def choose_asset(release, repo=None):
    assets = [asset for asset in release.get('assets') or [] if isinstance(asset, dict)]
    files = [asset for asset in assets if str(asset.get('name', '')).lower().endswith(('.exe', '.zip'))]
    files.sort(key=lambda asset: (0 if 'setup' in asset.get('name', '').lower() and asset['name'].lower().endswith('.exe') else 1, asset.get('name', '')))
    if not files:
        raise ValueError('The latest release has no Windows installer.')
    url = files[0].get('browser_download_url') or ''
    if not release_url_allowed(url, repo=repo):
        raise ValueError('The release file is not from the eznest releases.')
    return files[0]


def github_token(directory):
    token = os.environ.get('EZ_NEST_GITHUB_TOKEN', '').strip()
    if token:
        return token
    path = Path(directory) / 'github-token'
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _headers(url, token):
    host = (urlparse(url).hostname or '').casefold()
    headers = {'User-Agent': 'eznest'}
    if token and host in ('api.github.com', 'github.com'):
        headers['Authorization'] = 'Bearer ' + token
        headers['Accept'] = 'application/octet-stream' if '/releases/assets/' in urlparse(url).path else 'application/vnd.github+json'
    return headers


class _StopRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(opener, url, token, timeout, repo=None, redirects=0):
    if redirects > 5:
        raise ValueError('Too many release redirects.')
    if not release_url_allowed(url, download=True, repo=repo) and not release_url_allowed(url, download=False, repo=repo):
        raise ValueError('The release file is not from the eznest releases.')
    request = Request(url, headers=_headers(url, token))
    try:
        return opener.open(request, timeout=timeout)
    except HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise
        location = error.headers.get('Location')
        if not location or not release_url_allowed(location, download=True, repo=repo):
            raise ValueError('The release file is not from the eznest releases.') from error
        return _open(opener, location, token, timeout, repo, redirects + 1)


def _read_limited(response):
    chunks = []
    total = 0
    while True:
        block = response.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > MAX_RELEASE_BYTES:
            raise ValueError('The release file is too large.')
        chunks.append(block)
    return b''.join(chunks)


def parse_sha256_text(text):
    token = text.strip().split()[0].lower() if text.strip() else ''
    if len(token) != 64 or any(character not in '0123456789abcdef' for character in token):
        raise ValueError('Checksum file is not a SHA-256 hex digest.')
    return token


def checksum_matches(actual, expected):
    actual = (actual or '').lower()
    expected = (expected or '').strip().lower()
    if len(actual) != 64 or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
        return False
    return hmac.compare_digest(actual, expected)


def _asset_map(release):
    assets = {}
    for asset in release.get('assets') or []:
        if isinstance(asset, dict) and isinstance(asset.get('name'), str):
            assets[asset['name']] = asset
    return assets


def select_release(payload, current, include_prerelease=False):
    releases = payload if isinstance(payload, list) else [payload]
    chosen = None
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') or not release.get('tag_name'):
            continue
        if release.get('prerelease') and not include_prerelease:
            continue
        try:
            if not is_newer(str(release['tag_name']), current):
                continue
        except ValueError:
            continue
        if chosen is None or _numbers(str(release['tag_name'])) > _numbers(str(chosen['tag_name'])):
            chosen = release
    return chosen


def release_checksum(release, filename, opener, token, repo):
    assets = _asset_map(release)
    sha_asset = assets.get(filename + '.sha256')
    if sha_asset:
        url = sha_asset.get('browser_download_url') or ''
        if not release_url_allowed(url, repo=repo):
            raise ValueError('The release file is not from the eznest releases.')
        with _open(opener, url, token, 30, repo) as response:
            return parse_sha256_text(_read_limited(response).decode('utf-8', 'replace'))
    manifest_asset = assets.get('manifest.json')
    if manifest_asset:
        url = manifest_asset.get('browser_download_url') or ''
        if not release_url_allowed(url, repo=repo):
            raise ValueError('The release file is not from the eznest releases.')
        with _open(opener, url, token, 30, repo) as response:
            manifest = json.loads(_read_limited(response).decode('utf-8'))
        if isinstance(manifest, dict) and manifest.get('published') is not False and manifest.get('filename') in (None, filename):
            digest = manifest.get('sha256')
            if isinstance(digest, str):
                return parse_sha256_text(digest)
    raise ValueError('The release has no checksum. It was not downloaded.')


def _known_latest(releases, current):
    known = []
    for item in releases:
        tag = str(item.get('tag_name')) if isinstance(item, dict) and item.get('tag_name') else ''
        if not tag:
            continue
        try:
            _numbers(tag)
        except ValueError:
            continue
        known.append(tag)
    return max(known, key=_numbers).lstrip('vV') if known else current


def _idle(current, latest, message):
    return {
        'ok': True, 'current': current, 'latest': latest, 'updated': False, 'staged': False,
        'applyOnRestart': False, 'message': message,
    }


def pull_latest(directory, current, opener=None, when='restart', install_root=None):
    """Check a newer release, then stage it. The gear's Update button calls this.

    The file stays in the data directory until the next start, or until Install now
    asks the helper to swap it in. The installer is not opened from the browser.
    """
    directory = Path(directory)
    if os.environ.get('EZ_NEST_UPDATES', '1') == '0' or not load_shop(directory)['updates']:
        return _idle(current, current, 'Updates are off.')
    if when not in ('now', 'restart'):
        raise ValueError('Choose Update or install on the next start.')
    include_prerelease = load_shop(directory)['channel'] == 'test'
    token = github_token(directory)
    repo = repo_for_release(directory)
    api = release_api(directory)
    opener = opener or build_opener(_StopRedirect)
    try:
        with _open(opener, api, token, 30, repo) as response:
            payload = json.loads(_read_limited(response).decode('utf-8'))
    except (OSError, URLError, HTTPError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ValueError) and 'release file' in str(error):
            raise
        raise ValueError('Could not reach the release.') from error
    releases = payload if isinstance(payload, list) else [payload]
    if not releases or not isinstance(releases[0], dict):
        raise ValueError('Could not reach the release.')
    release = select_release(payload, current, include_prerelease)
    if release is None:
        return _idle(current, _known_latest(releases, current), 'This is the latest release.')
    latest = str(release['tag_name']).lstrip('vV')
    asset = choose_asset(release, repo)
    name = Path(asset['name']).name
    if name != asset['name'] or Path(name).name != name:
        raise ValueError('The release file is not from the eznest releases.')
    try:
        digest = release_checksum(release, name, opener, token, repo)
        with _open(opener, asset['browser_download_url'], token, 120, repo) as response:
            body = _read_limited(response)
    except (OSError, URLError, HTTPError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError('Could not reach the release.') from error
    import installer_update
    pending = installer_update.stage_file(directory, latest, digest, body, name)
    supported = installer_update.apply_supported(install_root)
    result = {
        'ok': True,
        'current': current,
        'latest': latest,
        'updated': True,
        'staged': True,
        'applyOnRestart': supported,
        'path': pending['file'],
        'message': f'{name} is checked and installs the next time eznest starts. Settings and the hot folder stay.' if supported else f'{name} is checked and saved. Automatic installation is unavailable for this installation. The current app stays running.',
        'restarting': False,
    }
    if when == 'now':
        if installer_update.apply_supported(install_root):
            result.update(installer_update.begin_apply(directory, install_root))
        else:
            result['message'] = f'{name} is checked and saved. Automatic installation is unavailable for this installation. The current app stays running.'
            result['applyOnRestart'] = False
    return result


def peek_latest(directory, current, opener=None):
    """Say whether a newer release exists. This does not download the installer."""
    directory = Path(directory)
    if os.environ.get('EZ_NEST_UPDATES', '1') == '0' or not load_shop(directory)['updates']:
        return {'ok': True, 'current': current, 'updateAvailable': False, 'latest': current, 'message': 'Update checks are off.', 'error': None}
    include_prerelease = load_shop(directory)['channel'] == 'test'
    token = github_token(directory)
    repo = repo_for_release(directory)
    opener = opener or build_opener(_StopRedirect)
    try:
        with _open(opener, release_api(directory), token, 15, repo) as response:
            payload = json.loads(_read_limited(response).decode('utf-8'))
    except (OSError, URLError, HTTPError, ValueError, json.JSONDecodeError):
        return {'ok': True, 'current': current, 'updateAvailable': False, 'latest': None, 'message': 'Could not reach the release.', 'error': 'Could not reach the release.'}
    release = select_release(payload, current, include_prerelease)
    if release is None:
        return {'ok': True, 'current': current, 'updateAvailable': False, 'latest': current, 'message': 'This is the latest release.', 'error': None}
    latest = str(release['tag_name']).lstrip('vV')
    try:
        choose_asset(release, repo)
    except ValueError as error:
        return {'ok': True, 'current': current, 'updateAvailable': False, 'latest': latest, 'message': str(error), 'error': str(error)}
    return {'ok': True, 'current': current, 'updateAvailable': True, 'latest': latest, 'message': f'{latest} is available.', 'releaseNotes': str(release.get('body') or '')[:4000], 'error': None}


def read_json(value):
    if isinstance(value, bytes):
        return json.loads(value.decode('utf-8'))
    return json.load(io.BytesIO(value) if not hasattr(value, 'read') else value)



def validate_setup(data):
    if not isinstance(data, dict):
        raise ValueError('Enter your shop setup.')
    clean = {}
    for field, limit in (('printer', 120), ('hotFolder', 400), ('thru', 80), ('kiss', 80)):
        value = data.get(field)
        if not isinstance(value, str) or (field in ('thru','kiss') and not value.strip()) or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError(f'Enter a valid {field}.')
        clean[field] = value.strip()
    if clean['thru'].casefold() == clean['kiss'].casefold():
        raise ValueError('Thru and kiss cut spots must have different names.')
    if data.get('units') not in ('in', 'mm', 'cm'):
        raise ValueError('Choose inches, millimeters, or centimeters.')
    clean['units'] = data['units']
    return clean

