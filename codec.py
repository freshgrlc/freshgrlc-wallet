from base58 import b58encode_check as b58encode, b58decode_check as b58decode
from bech32 import encode as b32encode, decode as b32decode


def _assert_version(found, expected, datatype):
    if expected is not None and found != expected:
        raise ValueError('Invalid %s version (expected %d, got %d)' % (datatype, expected, found))


def _assert_inputdata(version, data, expected_length, datatype):
    if type(version) != int or version < 0 or version >= 0x100:
        raise ValueError('Invalid version byte')
    if len(data) != expected_length:
        raise ValueError('Invalid %s: not %d bytes' % (datatype, expected_length))


def _assert_bech32_prefix(prefix):
    if type(prefix) != str or len(prefix) > 4 or ''.join(filter(lambda c: c in 'abcdefghijklmnopqrstuvwxyz', prefix)) != prefix:
        raise ValueError('Invalid bech32 prefix')


def decode_base58_address(address, verify_version=None):
    raw = b58decode(address)

    if len(raw) != 20 + 1:
        raise ValueError('Invalid length')

    version = ord(raw[0])
    pubkeyhash = raw[1:]

    _assert_version(version, verify_version, 'address')
    return version, pubkeyhash


def decode_bech32_address(address, verify_prefix=None):
    if verify_prefix is None:
        verify_prefix = address.split('1')[0]

    version, decoded = b32decode(verify_prefix, address)

    if decoded is None:
        raise ValueError('Invalid bech32 address')
    if version != 0:
        raise ValueError('Not a version-0 bech32 address')
    if len(decoded) != 20:
        raise ValueError('Not a bech32 p2wpkh address')

    return version, ''.join(chr(b) for b in decoded)


def decode_privkey(encoded_privkey, verify_version=None):
    raw = b58decode(encoded_privkey)

    if len(raw) not in [1+32, 1+32+1]:
        raise ValueError('Invalid private key length')

    compressed_pubkey = len(raw) == 1+32+1

    if compressed_pubkey and ord(raw[-1:]) != 0x01:
        raise ValueError('Invalid private key length / invalid public key compression byte')

    version = ord(raw[0])
    privkey = raw[1:1+32]

    _assert_version(version, verify_version, 'private key')
    return version, privkey, compressed_pubkey


def encode_base58_address(version, pubkeyhash):
    _assert_inputdata(version, pubkeyhash, 20, 'public key hash')
    return b58encode(chr(version) + pubkeyhash)


def encode_bech32_address(prefix, pubkeyhash):
    _assert_inputdata(0, pubkeyhash, 20, 'public key hash')
    _assert_bech32_prefix(prefix)

    encoded = b32encode(prefix, 0, [ ord(c) for c in pubkeyhash ])
    if encoded is not None:
        return encoded
    raise ValueError('Unable to encode public key hash to bech32 encoded address with prefix "%s"' % prefix)


def encode_privkey(version, privkey, compressed_pubkey=True):
    _assert_inputdata(version, privkey, 32, 'private key')
    return b58encode(chr(version) + privkey + (chr(0x01) if compressed_pubkey else b''))

