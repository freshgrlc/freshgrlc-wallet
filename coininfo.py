from binascii import hexlify

from coinsupport.segwit import get_converter_factory_for_address_type
from coinsupport.addresscodecs import decode_base58_address, encode_base58_address, decode_bech32_address, encode_bech32_address, encode_privkey

import config
from indexer.models import Block, TXOUT_TYPES


class CoinNotDefinedException(Exception):
    pass


class InvalidTransactionOutputType(Exception):
    pass


class Coin(object):
    coins = []

    def __init__(self, name, ticker, database_name, rpc_host, rpc_port, address_version, p2sh_address_version, privkey_version, segwit_converter, allow_tx_subsidy, register=True):
        self.name = name
        self.ticker = ticker
        self.db_table = database_name
        self.rpc_host = rpc_host
        self.rpc_port = rpc_port
        self.address_version = address_version
        self.p2sh_address_version = p2sh_address_version
        self.privkey_version = privkey_version
        self.segwit_converter = segwit_converter
        self.allow_tx_subsidy = allow_tx_subsidy

        if self.segwit_converter is not None:
            self.segwit_converter.parent = self

        if register:
            self.coins.append(self)

    @property
    def has_separate_segwit_address(self):
        return self.segwit_converter is not None and not self.segwit_converter.receive_only

    def get_legacy_address(self, pubkeyhash):
        return encode_base58_address(self.address_version, pubkeyhash)

    def get_segwit_address(self, pubkeyhash):
        return self.segwit_converter.encode_segwit_address(pubkeyhash) if self.segwit_converter is not None else None

    def get_p2sh_address(self, scripthash):
        return encode_base58_address(self.p2sh_address_version, scripthash)

    def get_addresses_for_pubkeyhash(self, pubkeyhash):
        addresses = [ self.get_legacy_address(pubkeyhash) ]
        if self.has_separate_segwit_address:
            addresses.append(self.get_segwit_address(pubkeyhash))
        return addresses

    def current_coinbase_confirmation_height(self, dbsession=None):
        if dbsession is None:
            from connections import connectionmanager
            dbsession = connectionmanager.database_session(coin=self)
        return dbsession.query(Block.height).order_by(Block.height.desc()).first()[0] - 100

    def get_default_receive_address(self, pubkeyhash):
        address = self.get_segwit_address(pubkeyhash)
        return address if address is not None else self.get_legacy_address(pubkeyhash)

    def valid_address(self, address):
        pubkeyhash, _ = self.decode_address_and_type(address)
        return pubkeyhash is not None

    def decode_address_and_type(self, address):
        try:
            _, pubkeyhash = decode_base58_address(address, verify_version=self.address_version)
            return pubkeyhash, TXOUT_TYPES.P2PKH
        except ValueError:
            pass

        try:
            _, scripthash = decode_base58_address(address, verify_version=self.p2sh_address_version)
            return scripthash, TXOUT_TYPES.P2SH
        except ValueError:
            pass

        try:
            if self.segwit_converter is not None:
                _, pubkeyhash = self.segwit_converter.decode_address(address)
                return pubkeyhash, TXOUT_TYPES.P2WPKH
        except ValueError:
            pass

        return None, None

    def encode_address(self, hash, txout_type):
        if txout_type == TXOUT_TYPES.P2PKH:
            return self.get_legacy_address(hash)
        if txout_type == TXOUT_TYPES.P2WPKH:
            if self.segwit_converter is not None:
                return self.get_segwit_address(hash)
            raise InvalidTransactionOutputType('Cannot encode hash "%s" to p2wpkh address: Segwit not enabled on network for %s' % (hexlify(hash), self.ticker))
        if txout_type == TXOUT_TYPES.P2SH:
            return self.get_p2sh_address(hash)
        raise NotImplementedError('Output type %s not supported' % txout_type)

    def encode_private_key(self, raw_privkey):
        return encode_privkey(self.privkey_version, raw_privkey)

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
        return cls.get_by_filter(ticker, lambda coin: coin.ticker.lower() == ticker.lower())


def parse_coin_segwit_info(segwit_info):
    if segwit_info is None:
        return None
    if 'addresstype' not in segwit_info:
        raise ValueError('No segwit address type info available or unexpect address type: %s' % segwit_info['addresstype'] if 'addresstype' in segwit_info else None)
    return get_converter_factory_for_address_type(segwit_info['addresstype'])(**segwit_info)


def make_coin(info, register=True):
    return Coin(
        name=info['name'],
        ticker=info['ticker'] if 'ticker' in info else None,
        database_name=info['database']['name'] if 'database' in info and info['database'] is not None else None,
        rpc_host=info['coindaemon']['hostname'],
        rpc_port=info['coindaemon']['port'],
        address_version=info['address_version'],
        p2sh_address_version=info['p2sh_address_version'],
        privkey_version=info['privkey_version'],
        segwit_converter=parse_coin_segwit_info(info['segwit_info']),
        allow_tx_subsidy=info['allow_tx_subsidy'],
        register=register
    )

COINS = [ make_coin(info) for info in config.COINS ]
KEYSEEDER_INFO = make_coin(config.KEYSEEDER, register=False)

