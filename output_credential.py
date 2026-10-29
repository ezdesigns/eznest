"""Host-local OUTPUT shop credential.

The secret is not an environment variable. It is not written to logs, API
responses, or the telemetry database. On Windows the file is a DPAPI blob
for the Windows user that saved it, not for the whole machine. Pair while
the eznest service is running so that user is eznest-svc. A different
interactive user cannot decrypt that blob. The file ACL allows SYSTEM,
Administrators, and the user who wrote the file, plus eznest-svc when
Windows can map that account. On other systems the file mode is 0600.
Callers must not log the return value.
"""
import json
import os
import re
import subprocess
from pathlib import Path

FILE_NAME = 'output-credential.bin'
TOKEN_RE = re.compile(r'osa_[A-Za-z0-9_-]{43}')
_MAGIC = b'EZNCRED1'
_UI_FORBIDDEN = 0x1


def path(directory):
    return Path(directory) / FILE_NAME


def valid_token(value):
    return isinstance(value, str) and TOKEN_RE.fullmatch(value) is not None


def clean_shop_name(value):
    if not isinstance(value, str) or any(ord(ch) < 32 for ch in value):
        raise ValueError('OUTPUT did not name the shop. Ask the owner for a new pairing code.')
    name = ' '.join(value.split())
    if not name or len(name) > 80:
        raise ValueError('OUTPUT did not name the shop. Ask the owner for a new pairing code.')
    return name


class PosixCodec:
    """Development and test storage. Production Windows builds use DPAPI."""

    def protect(self, data):
        return _MAGIC + data

    def unprotect(self, data):
        if not isinstance(data, (bytes, bytearray)) or not data.startswith(_MAGIC):
            raise ValueError('unreadable')
        return bytes(data[len(_MAGIC):])


class DpapiCodec:
    def protect(self, data):
        return _dpapi(data, protect=True)

    def unprotect(self, data):
        return _dpapi(data, protect=False)


def default_codec():
    return DpapiCodec() if os.name == 'nt' else PosixCodec()


def _dpapi(data, *, protect):
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_type = ctypes.POINTER(DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [blob_type, wintypes.LPCWSTR, blob_type, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_type]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [blob_type, ctypes.POINTER(wintypes.LPWSTR), blob_type, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_type]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    raw = bytes(data)
    holder = ctypes.create_string_buffer(raw)
    incoming = DATA_BLOB(len(raw), ctypes.cast(holder, ctypes.POINTER(ctypes.c_char)))
    outgoing = DATA_BLOB()
    if protect:
        # User scope only. The machine-wide DPAPI flag is not set.
        ok = crypt32.CryptProtectData(ctypes.byref(incoming), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(outgoing))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(outgoing))
    if not ok:
        raise ValueError('unreadable')
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(outgoing.pbData)


_SERVICE_ACCOUNT = 'eznest-svc'
_PROTECT_ERROR = 'Could not protect the saved OUTPUT credential on this computer.'
_UNMAPPED_ACCOUNT = 1332
_SYSTEM_GRANT = '*S-1-5-18:(M)'
_ADMINISTRATORS_GRANT = '*S-1-5-32-544:(M)'


def _account_grant(name):
    if not isinstance(name, str) or not name or len(name) > 64:
        return None
    if any(ch in name for ch in '*?"<>|:\r\n\x00'):
        return None
    return name + ':(M)'


def _use_windows_acl():
    return os.name == 'nt'


def _account_exists(name):
    """True or False when Windows can decide, else None.

    LookupAccountNameW is used so the account name is not passed to a shell.
    None means the caller should try the grant and drop it if the name does
    not map.
    """
    if os.name != 'nt' or _account_grant(name) is None or '\x00' in name:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        library = ctypes.WinDLL('advapi32', use_last_error=True)
        lookup = library.LookupAccountNameW
        lookup.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        )
        lookup.restype = wintypes.BOOL
        sid_size = wintypes.DWORD(0)
        domain_size = wintypes.DWORD(0)
        use = wintypes.DWORD()
        ctypes.set_last_error(0)
        lookup(None, name, None, ctypes.byref(sid_size), None, ctypes.byref(domain_size), ctypes.byref(use))
        error = ctypes.get_last_error()
        insufficient = 122
        if error == _UNMAPPED_ACCOUNT:
            return False
        if error != insufficient or not 0 < sid_size.value <= 256 or domain_size.value > 1024:
            return None
        sid = ctypes.create_string_buffer(sid_size.value)
        domain = ctypes.create_unicode_buffer(max(domain_size.value, 1))
        sid_size = wintypes.DWORD(len(sid))
        domain_size = wintypes.DWORD(len(domain))
        ctypes.set_last_error(0)
        if lookup(None, name, sid, ctypes.byref(sid_size), domain, ctypes.byref(domain_size), ctypes.byref(use)):
            return True
        if ctypes.get_last_error() == _UNMAPPED_ACCOUNT:
            return False
    except (AttributeError, OSError, ImportError, TypeError, ValueError):
        return None
    return None


def _icacls(args):
    return subprocess.run(args, capture_output=True)


def _unmapped_account(result):
    if getattr(result, 'returncode', None) == _UNMAPPED_ACCOUNT:
        return True
    text = []
    for stream in (getattr(result, 'stdout', None), getattr(result, 'stderr', None)):
        if isinstance(stream, bytes):
            text.append(stream.decode('utf-8', 'replace'))
        elif isinstance(stream, str):
            text.append(stream)
    return 'No mapping' in ''.join(text)


def _restrict_windows(target):
    # SYSTEM, Administrators, and the current user are required. eznest-svc is
    # the shop service account and is optional until the installer creates it.
    # User-scoped DPAPI still decrypts only for the account that protected the blob.
    grants = [_SYSTEM_GRANT, _ADMINISTRATORS_GRANT]
    user = _account_grant(os.environ.get('USERNAME', ''))
    if user and user not in grants:
        grants.append(user)
    service = _account_grant(_SERVICE_ACCOUNT)
    include_service = (
        bool(service)
        and service not in grants
        and _account_exists(_SERVICE_ACCOUNT) is not False
    )
    if include_service:
        grants.append(service)
    if _icacls(['icacls', str(target), '/inheritance:r']).returncode != 0:
        raise ValueError(_PROTECT_ERROR)
    result = _icacls(['icacls', str(target), '/grant:r', *grants])
    if result.returncode != 0 and include_service and _unmapped_account(result):
        required = [grant for grant in grants if grant != service]
        result = _icacls(['icacls', str(target), '/grant:r', *required])
    if result.returncode != 0:
        raise ValueError(_PROTECT_ERROR)


def _write(directory, payload, codec):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = path(directory)
    temporary = target.with_name(FILE_NAME + '.tmp')
    blob = codec.protect(payload)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        # Windows opens in text mode by default, which expands 0x0A bytes in the
        # encrypted DPAPI blob to 0x0D0A and corrupts it. Force binary.
        if hasattr(os, 'O_BINARY'):
            flags |= os.O_BINARY
        fd = os.open(temporary, flags, 0o600)
        try:
            os.write(fd, blob)
        finally:
            os.close(fd)
        if _use_windows_acl():
            _restrict_windows(temporary)
        else:
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        if _use_windows_acl():
            _restrict_windows(target)
        else:
            os.chmod(target, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def save(directory, credential, shop_name=None, codec=None):
    if not valid_token(credential):
        raise ValueError('OUTPUT did not return a shop credential. Ask the owner for a new pairing code.')
    payload = {'v': 1, 'credential': credential}
    if shop_name is not None:
        payload['shopName'] = clean_shop_name(shop_name)
    _write(directory, json.dumps(payload, separators=(',', ':')).encode(), codec or default_codec())


def _record(directory, codec):
    target = path(directory)
    if not target.is_file():
        return {'credential': None, 'shopName': None}
    blob = target.read_bytes()
    try:
        payload = json.loads((codec or default_codec()).unprotect(blob))
    except (ValueError, TypeError, json.JSONDecodeError):
        return {'credential': None, 'shopName': None}
    if not isinstance(payload, dict):
        return {'credential': None, 'shopName': None}
    credential = payload.get('credential')
    if not valid_token(credential):
        return {'credential': None, 'shopName': None}
    try:
        shop_name = clean_shop_name(payload.get('shopName'))
    except ValueError:
        shop_name = None
    return {'credential': credential, 'shopName': shop_name}


def describe(directory, codec=None):
    """Return the stored credential and shop name. Missing or unreadable is not connected."""
    return _record(directory, codec)


def load(directory, codec=None):
    return describe(directory, codec)['credential']


def clear(directory):
    path(directory).unlink(missing_ok=True)
    path(directory).with_name(FILE_NAME + '.tmp').unlink(missing_ok=True)
