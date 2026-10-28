"""Host-local OUTPUT shop credential.

The secret is not an environment variable. It is not written to logs, API
responses, or the telemetry database. On Windows the file is a DPAPI blob
scoped to this machine so the shop service and an interactive host session
can both read it, and the blob is useless on another PC. The file ACL allows
SYSTEM, Administrators, the current user, and eznest-svc. On other systems
the file mode is 0600. Callers must not log the return value.
"""
import json
import os
import re
import subprocess
from pathlib import Path

FILE_NAME = 'output-credential.bin'
TOKEN_RE = re.compile(r'osa_[A-Za-z0-9_-]{43}')
_MAGIC = b'EZNCRED1'
_LOCAL_MACHINE = 0x4
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
        ok = crypt32.CryptProtectData(ctypes.byref(incoming), None, None, None, None, _LOCAL_MACHINE | _UI_FORBIDDEN, ctypes.byref(outgoing))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(outgoing))
    if not ok:
        raise ValueError('unreadable')
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(outgoing.pbData)


def _account_grant(name):
    if not isinstance(name, str) or not name or len(name) > 64:
        return None
    if any(ch in name for ch in '*?"<>|:\r\n'):
        return None
    return name + ':(M)'


def _restrict_windows(target):
    # SYSTEM and Administrators can recover the file. The current user covers
    # an interactive host session. eznest-svc is granted separately because
    # that account does not exist until shop setup.
    grants = ['*S-1-5-18:(M)', '*S-1-5-32-544:(M)']
    current = _account_grant(os.environ.get('USERNAME', ''))
    if current:
        grants.append(current)
    if subprocess.run(['icacls', str(target), '/inheritance:r'], capture_output=True).returncode != 0:
        raise ValueError('Could not protect the saved OUTPUT credential on this computer.')
    if subprocess.run(['icacls', str(target), '/grant:r', *grants], capture_output=True).returncode != 0:
        raise ValueError('Could not protect the saved OUTPUT credential on this computer.')
    service = _account_grant('eznest-svc')
    if service:
        subprocess.run(['icacls', str(target), '/grant:r', service], capture_output=True)


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
        fd = os.open(temporary, flags, 0o600)
        try:
            os.write(fd, blob)
        finally:
            os.close(fd)
        if os.name == 'nt':
            _restrict_windows(temporary)
        else:
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        if os.name == 'nt':
            _restrict_windows(target)
        else:
            os.chmod(target, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def save(directory, credential, shop_name, codec=None):
    if not valid_token(credential):
        raise ValueError('OUTPUT did not return a shop credential. Ask the owner for a new pairing code.')
    name = clean_shop_name(shop_name)
    payload = json.dumps({'v': 1, 'credential': credential, 'shopName': name}, separators=(',', ':')).encode()
    _write(directory, payload, codec or default_codec())


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
