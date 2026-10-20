"""Shop-server install choices: one computer, many browsers.

LAN binding, the ONYX hot-folder default, and release checks live here so the
nest, the file import, and the gear can stay separate.
"""
import io
import ipaddress
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

LOCAL_HOT_FOLDER = r'C:\ONYX\EPSON SureColor S80600 ONYX Input'
UNC_HOT_FOLDER = r'\\ONYX\EPSON SureColor S80600 ONYX Input'
RELEASE_API = 'https://api.github.com/repos/ezdesigns/eznest/releases/latest'
WARNING = 'Anyone on the shop LAN can Send to ONYX. Do not share this network with guest WiFi.'
MAX_RELEASE_BYTES = 300_000_000
REDIRECT_HOSTS = {
    'github.com',
    'api.github.com',
    'objects.githubusercontent.com',
    'release-assets.githubusercontent.com',
    'github-releases.githubusercontent.com',
}


def default_hot_folder(onyx_pc):
    """The ONYX computer writes a local folder. Every other PC uses the share."""
    return LOCAL_HOT_FOLDER if onyx_pc else UNC_HOT_FOLDER


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
    return {
        'onyxPc': data.get('onyxPc') is True,
        'lan': data.get('lan') is True,
        'updates': data.get('updates') is not False,
    }


def save_shop(directory, onyx_pc, lan, updates=None):
    path = Path(directory) / 'shop.json'
    if updates is None:
        updates = load_shop(directory)['updates']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'onyxPc': bool(onyx_pc), 'lan': bool(lan), 'updates': bool(updates)}, indent=2) + '\n', encoding='utf-8')
    return load_shop(directory)


# Windows getaddrinfo and getfqdn ignore the Python socket timeout and can sit
# on DNS for longer than a minute. The shop page waits on this during boot.
_LOOKUP_TIMEOUT = 1.0
_LOOKUP_TTL = 30.0
_lookup_lock = threading.Lock()
_address_cache = {'expires': 0.0, 'values': []}
_fqdn_cache = {'expires': 0.0, 'value': ''}


def clear_name_cache():
    with _lookup_lock:
        _address_cache['expires'] = 0.0
        _address_cache['values'] = []
        _fqdn_cache['expires'] = 0.0
        _fqdn_cache['value'] = ''


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


def shop_names():
    host = socket.gethostname().strip().rstrip('.')
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


def release_url_allowed(url, download=False):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    if download and host in REDIRECT_HOSTS and host not in ('github.com', 'api.github.com'):
        return True
    if host == 'api.github.com' and parsed.path == '/repos/ezdesigns/eznest/releases/latest':
        return not download
    if host == 'github.com' and parsed.path.startswith('/ezdesigns/eznest/releases/download/'):
        return True
    if host == 'api.github.com' and parsed.path.startswith('/repos/ezdesigns/eznest/releases/assets/'):
        return True
    return False


def choose_asset(release):
    assets = [asset for asset in release.get('assets') or [] if isinstance(asset, dict)]
    files = [asset for asset in assets if str(asset.get('name', '')).lower().endswith(('.exe', '.zip'))]
    files.sort(key=lambda asset: (0 if 'setup' in asset.get('name', '').lower() and asset['name'].lower().endswith('.exe') else 1, asset.get('name', '')))
    if not files:
        raise ValueError('The latest release has no Windows installer.')
    url = files[0].get('browser_download_url') or ''
    if not release_url_allowed(url):
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


def _open(opener, url, token, timeout):
    if not release_url_allowed(url, download=True) and not release_url_allowed(url, download=False):
        raise ValueError('The release file is not from the eznest releases.')
    request = Request(url, headers=_headers(url, token))
    try:
        return opener.open(request, timeout=timeout)
    except HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise
        location = error.headers.get('Location')
        if not location or not release_url_allowed(location, download=True):
            raise ValueError('The release file is not from the eznest releases.') from error
        return _open(opener, location, token, timeout)


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


def pull_latest(directory, current, opener=None):
    """Download a newer official Windows release. The button in the gear calls this."""
    directory = Path(directory)
    if not load_shop(directory)['updates']:
        return {'ok': True, 'current': current, 'latest': current, 'updated': False, 'message': 'Updates are off.'}
    token = github_token(directory)
    opener = opener or build_opener(_StopRedirect)
    try:
        with _open(opener, RELEASE_API, token, 30) as response:
            release = json.loads(_read_limited(response).decode('utf-8'))
    except (OSError, URLError, HTTPError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ValueError) and 'release file' in str(error):
            raise
        raise ValueError('Could not reach the release.') from error
    if not isinstance(release, dict) or not release.get('tag_name'):
        raise ValueError('Could not reach the release.')
    latest = str(release['tag_name'])
    if not is_newer(latest, current):
        return {'ok': True, 'current': current, 'latest': latest.lstrip('vV'), 'updated': False, 'message': 'This is the latest release.'}
    asset = choose_asset(release)
    name = Path(asset['name']).name
    if name != asset['name'] or Path(name).name != name:
        raise ValueError('The release file is not from the eznest releases.')
    try:
        with _open(opener, asset['browser_download_url'], token, 120) as response:
            payload = _read_limited(response)
    except (OSError, URLError, HTTPError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError('Could not reach the release.') from error
    folder = directory / 'updates'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    temporary = target.with_suffix(target.suffix + '.part')
    temporary.write_bytes(payload)
    temporary.replace(target)
    message = 'Downloaded ' + name + '.'
    if os.name == 'nt' and target.suffix.lower() == '.exe':
        try:
            os.startfile(target)  # noqa: S606 - the gear asked to open this eznest release installer
        except OSError:
            message += ' The installer is in the updates folder.'
        else:
            message += ' The installer is opening.'
    return {'ok': True, 'current': current, 'latest': latest.lstrip('vV'), 'updated': True, 'path': str(target), 'message': message}


def read_json(value):
    if isinstance(value, bytes):
        return json.loads(value.decode('utf-8'))
    return json.load(io.BytesIO(value) if not hasattr(value, 'read') else value)
