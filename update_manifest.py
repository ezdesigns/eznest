"""Check a shop update manifest signed with an offline key.

PUBLIC_KEY is the pin. The matching private key is not in this repository.
A release with no manifest, or a manifest marked as a database change, is refused.
The download is kept only when its hash matches the signed manifest.
"""
import hashlib
import json
import secrets
from pathlib import Path

ASSET = 'update-manifest.json'
MAX_BYTES = 4096
MISSING = 'This release has no update manifest. It was not installed.'
UNCHECKED = 'This update manifest could not be checked. It was not installed.'
SCHEMA = 'This release changes the shop database. It was not installed.'

# Pinned Ed25519 public key (32 bytes, hex). The private key stays offline.
# Generate a key with tools/sign_update_manifest.py and replace this pin in a
# reviewed change before signing a release. This pin has no private key here.
PUBLIC_KEY = '037105ecc056dfc05e695f19b81095c2557b7633ec1a7320cac27bca93f8a5ae'

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _sha512(data):
    return hashlib.sha512(data).digest()


def _inv(value):
    value %= _P
    if value == 0:
        raise ZeroDivisionError
    return pow(value, _P - 2, _P)


def _recover_x(y, sign):
    if y >= _P:
        return None
    y2 = y * y % _P
    try:
        x2 = (y2 - 1) * _inv(_D * y2 + 1) % _P
    except ZeroDivisionError:
        return None
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _point_add(first, second):
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = (2 * _D * t1 * t2) % _P
    d = (2 * z1 * z2) % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_mul(scalar, point):
    result = (0, 1, 1, 0)
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _encode(point):
    x, y, z, _t = point
    inv_z = _inv(z)
    x, y = x * inv_z % _P, y * inv_z % _P
    raw = bytearray(y.to_bytes(32, 'little'))
    raw[31] |= (x & 1) << 7
    return bytes(raw)


def _decode(raw):
    if len(raw) != 32:
        return None
    value = int.from_bytes(raw, 'little')
    sign = (value >> 255) & 1
    y = value & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _clamp(raw):
    scalar = int.from_bytes(raw, 'little')
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar


def _affine(point):
    x, y, z, _t = point
    inv_z = _inv(z)
    return (x * inv_z % _P, y * inv_z % _P)


def generate_seed():
    return secrets.token_bytes(32)


def public_bytes(seed):
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ValueError('Signing key must be 32 bytes.')
    scalar = _clamp(_sha512(bytes(seed))[:32])
    return _encode(_point_mul(scalar, _base_point()))


def public_hex(seed):
    return public_bytes(seed).hex()


def _base_point():
    y = (4 * _inv(5)) % _P
    x = _recover_x(y, 0)
    return (x, y, 1, x * y % _P)


def sign(seed, message):
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ValueError('Signing key must be 32 bytes.')
    if not isinstance(message, (bytes, bytearray)):
        raise ValueError('Manifest bytes are required.')
    digest = _sha512(bytes(seed))
    scalar = _clamp(digest[:32])
    prefix = digest[32:]
    public = _encode(_point_mul(scalar, _base_point()))
    nonce = int.from_bytes(_sha512(prefix + bytes(message)), 'little') % _L
    commitment = _encode(_point_mul(nonce, _base_point()))
    challenge = int.from_bytes(_sha512(commitment + public + bytes(message)), 'little') % _L
    proof = (nonce + challenge * scalar) % _L
    return commitment + proof.to_bytes(32, 'little')


def verify(public_key, message, signature):
    key = _hex_bytes(public_key, 32)
    sig = _hex_bytes(signature, 64)
    if key is None or sig is None or not isinstance(message, (bytes, bytearray)):
        return False
    point = _decode(key)
    commitment = _decode(sig[:32])
    proof = int.from_bytes(sig[32:], 'little')
    if point is None or commitment is None or proof >= _L:
        return False
    challenge = int.from_bytes(_sha512(sig[:32] + key + bytes(message)), 'little') % _L
    left = _point_mul(proof, _base_point())
    right = _point_add(commitment, _point_mul(challenge, point))
    return _affine(left) == _affine(right)


def _hex_bytes(value, size):
    if isinstance(value, (bytes, bytearray)) and len(value) == size:
        return bytes(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if len(text) != size * 2 or any(character not in '0123456789abcdef' for character in text):
        return None
    return bytes.fromhex(text)


def canonical(manifest):
    payload = {
        'asset': manifest['asset'],
        'schemaChange': manifest['schemaChange'],
        'sha256': manifest['sha256'],
        'version': manifest['version'],
    }
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('ascii')


def sign_manifest(seed, *, version, asset, sha256, schema_change):
    if schema_change is not True and schema_change is not False:
        raise ValueError('schema_change must be true or false.')
    if not isinstance(sha256, str):
        raise ValueError('A SHA-256 hex digest is required.')
    body = {
        'asset': asset,
        'schemaChange': schema_change,
        'sha256': sha256.strip().lower(),
        'version': version,
    }
    return {'manifest': body, 'signature': sign(seed, canonical(body)).hex()}


def confirmed_manifest(document, *, version, asset, public_key=None):
    """Return the checked manifest, or raise ValueError with a short message."""
    if not isinstance(document, dict) or not isinstance(version, str) or not isinstance(asset, str):
        raise ValueError(UNCHECKED)
    manifest = document.get('manifest')
    signature = document.get('signature')
    if not isinstance(manifest, dict) or not isinstance(signature, str):
        raise ValueError(UNCHECKED)
    schema = manifest.get('schemaChange')
    name = manifest.get('asset')
    digest = manifest.get('sha256')
    found = manifest.get('version')
    if schema is not True and schema is not False:
        raise ValueError(UNCHECKED)
    if (not isinstance(name, str) or not name or name != asset or name != Path(name).name
            or any(mark in name for mark in '/\\:')):
        raise ValueError(UNCHECKED)
    if not isinstance(found, str) or found != version:
        raise ValueError(UNCHECKED)
    if not isinstance(digest, str):
        raise ValueError(UNCHECKED)
    digest = digest.strip().lower()
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise ValueError(UNCHECKED)
    signature = signature.strip().lower()
    if len(signature) != 128 or any(character not in '0123456789abcdef' for character in signature):
        raise ValueError(UNCHECKED)
    body = {'asset': name, 'schemaChange': schema, 'sha256': digest, 'version': found}
    try:
        message = canonical(body)
    except UnicodeEncodeError as error:
        raise ValueError(UNCHECKED) from error
    key = PUBLIC_KEY if public_key is None else public_key
    if not verify(key, message, signature):
        raise ValueError(UNCHECKED)
    if schema is True:
        raise ValueError(SCHEMA)
    return {'asset': name, 'schemaChange': False, 'sha256': digest, 'version': found, 'signature': signature}


def check_stored_manifest(stored, *, version, asset, public_key=None):
    """Check a manifest dict that already includes its signature field."""
    if not isinstance(stored, dict):
        raise ValueError(UNCHECKED)
    return confirmed_manifest(
        {'manifest': stored, 'signature': stored.get('signature')},
        version=version,
        asset=asset,
        public_key=public_key,
    )
