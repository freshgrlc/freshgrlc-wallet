from codec import decode_base58_address, encode_base58_address, encode_bech32_address

import config
from indexer.models import Block


class CoinNotDefinedException(Exception):
    pass


class SegwitConverter(object):
    def __init__(self, addresstype, send_only):
        self.addresstype = addresstype
        self.send_only = send_only
        self.parent = None

    def make_p2wpkh(self, address, receive=False):
        if receive and self.send_only:
            return None
        _, pubkeyhash = decode_base58_address(address, verify_version=(self.parent.address_version if self.parent is not None else None))

        return self.encode_segwit_address(pubkeyhash)

    def encode_segwit_address(self, pubkeyhash):
        raise NotImplementedError('%s.encode_segwit_address()' % self.__class__.__name__)


class VersionByteSegwitConverter(SegwitConverter):
    def __init__(self, addresstype, address_version, send_only=True):
        super(VersionByteSegwitConverter, self).__init__(addresstype, send_only)
        self.versionbyte = address_version

    def encode_segwit_address(self, pubkeyhash):
        return encode_base58_address(self.versionbyte, pubkeyhash)


class Bech32SegwitConverter(SegwitConverter):
    def __init__(self, addresstype, address_prefix, send_only=False):
        super(Bech32SegwitConverter, self).__init__(addresstype, send_only)
        self.prefix = address_prefix

    def encode_segwit_address(self, pubkeyhash):
        return encode_bech32_address(self.prefix, pubkeyhash)


SEGWIT_CONVERTERS = {
    'base58': VersionByteSegwitConverter,
    'bech32': Bech32SegwitConverter
}


class Coin(object):
    coins = []

    def __init__(self, name, ticker, database_name, rpc_host, rpc_port, address_version, privkey_version, segwit_converter, register=True):
        self.name = name
        self.ticker = ticker
        self.db_table = database_name
        self.rpc_host = rpc_host
        self.rpc_port = rpc_port
        self.address_version = address_version
        self.privkey_version = privkey_version
        self.segwit_converter = segwit_converter

        if self.segwit_converter is not None:
            self.segwit_converter.parent = self

        if register:
            self.coins.append(self)

    @property
    def has_separate_segwit_address(self):
        return self.segwit_converter is not None and not self.segwit_converter.send_only

    def get_addresses_for_pubkeyhash(self, pubkeyhash):
        addresses = [ encode_base58_address(self.address_version, pubkeyhash) ]
        if self.has_separate_segwit_address:
            addresses.append(self.segwit_converter.encode_segwit_address(pubkeyhash))
        return addresses

    def current_coinbase_confirmation_height(self, dbsession=None):
        if dbsession is None:
            from connections import connectionmanager
            dbsession = connectionmanager.database_session(coin=self)
        return dbsession.query(Block.height).order_by(Block.height.desc()).first()[0] - 100

    @classmethod
    def get_by_filter(cls, value, filter_func):
        filtered = list(filter(filter_func, cls.coins))
        if len(filtered) < 1:
            raise CoinNotDefinedException(value)
        return filtered[0]

    @classmethod
    def by_name(cls, name):
        return cls.get_by_filter(name, lambda coin: coin.name == name)

    @classmethod
    def by_ticker(cls, ticker):
        return cls.get_by_filter(ticker, lambda coin: coin.ticker == ticker)


def parse_coin_segwit_info(segwit_info):
    if segwit_info is None:
        return None
    if 'addresstype' not in segwit_info or segwit_info['addresstype'] not in SEGWIT_CONVERTERS.keys():
        raise ValueError('No segwit address type info available or unexpect address type: %s' % segwit_info['addresstype'] if 'addresstype' in segwit_info else None)
    return SEGWIT_CONVERTERS[segwit_info['addresstype']](**segwit_info)


def make_coin(info, register=True):
    return Coin(
        name=info['name'],
        ticker=info['ticker'] if 'ticker' in info else None,
        database_name=info['database']['name'] if 'database' in info and info['database'] is not None else None,
        rpc_host=info['coindaemon']['hostname'],
        rpc_port=info['coindaemon']['port'],
        address_version=info['address_version'],
        privkey_version=info['privkey_version'],
        segwit_converter=parse_coin_segwit_info(info['segwit_info']),
        register=register
    )

COINS = [ make_coin(info) for info in config.COINS ]
KEYSEEDER_INFO = make_coin(config.KEYSEEDER, register=False)

