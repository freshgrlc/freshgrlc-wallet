import os

from binascii import unhexlify
from Crypto.Cipher import AES
from sqlalchemy import BINARY as Binary, Column, Float, ForeignKey, Integer, MetaData, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session

import config
from coininfo import Coin, COINS
from connections import connectionmanager
from indexer.models import Address, TXOUT_TYPES


AUTH_TOKEN_SIZE = 64
ACCOUNT_NAME_LEN = 64


def make_indexer_ref(cointicker, object_name_path, object_id):
    return '%s/%s%s/%s/' % (config.INDEXER_API_ENDPOINT, cointicker.lower(), object_name_path, object_id)


def make_address_ref(addressbinding):
    return make_indexer_ref(addressbinding.coin, config.INDEXER_ADDRESS_API_PATH, addressbinding.address_info.address)


def make_tx_ref(coininfo, txid):
    return make_indexer_ref(coininfo.ticker, config.INDEXER_TRANSACTION_API_PATH, txid)


Base = declarative_base(metadata=MetaData(schema=config.DATABASE_WALLET_DB))


class Account(Base):
    __tablename__ = 'account'

    id = Column(Integer, primary_key=True)
    manager_id = Column('manager', Integer, ForeignKey('manager.id'))
    user = Column(String(ACCOUNT_NAME_LEN))
    iv = Column(Binary(16))
    encrypted_key = Column('key', Binary(32))
    pubkeyhash = Column(Binary(20))

    addresses = relationship('AccountAddress', back_populates='account', cascade='save-update, merge, delete')
    _consolidationinfo = relationship('AccountAutoConsolidationInfo', back_populates='account', cascade='save-update, merge, delete')
    manager = relationship('WalletManager', back_populates='accounts')

    @property
    def private_key(self):
        cipher = AES.new(unhexlify(config.ENCRYPTION_KEY), AES.MODE_CBC, self.iv)
        return cipher.decrypt(self.encrypted_key)

    @private_key.setter
    def private_key(self, value):
        self.iv = os.urandom(AES.block_size)
        cipher = AES.new(unhexlify(config.ENCRYPTION_KEY), AES.MODE_CBC, self.iv)
        self.encrypted_key = cipher.encrypt(value)

    @property
    def consolidationinfo(self):
        consolidationinfo = { coin.ticker: None for coin in COINS }
        for info in self._consolidationinfo:
            consolidationinfo[info.coin] = info
        return consolidationinfo

    def consolidationinfo_for(self, coin):
        return Session.object_session(self).query(
            AccountAutoConsolidationInfo
        ).filter(
            AccountAutoConsolidationInfo.account_id == self.id,
            AccountAutoConsolidationInfo.coin == coin.ticker
        ).first()

    API_DATA_FIELDS = [ user, 'Account.consolidationinfo' ]
    POSTPROCESS_RESOLVE_FOREIGN_KEYS = [ addresses ]


class AccountAddress(Base):
    __tablename__ = 'addressbinding'

    id = Column(Integer, primary_key=True)
    account_id = Column('account', Integer, ForeignKey('account.id'), index=True)
    coin = Column(String(5))
    address_id = Column('address', Integer, index=True)

    account = relationship('Account', back_populates='addresses')

    API_DATA_FIELDS = [ coin, 'AccountAddress.address', 'AccountAddress.balance', 'AccountAddress.pending', 'AccountAddress.href' ]

    @property
    def _dbsession(self):
        return connectionmanager.database_session(coin=Coin.by_ticker(self.coin))

    @property
    def address_info(self):
        try:
            return self._address_info
        except AttributeError:
            self._address_info = self._dbsession.query(Address).filter(Address.id == self.address_id).first()
            return self._address_info

    @property
    def address(self):
        return self.address_info.address if self.address_info != None else None

    @property
    def balance(self):
        return self.address_info.balance if self.address_info != None else 0.0

    @property
    def pending(self):
        return self.address_info.pending if self.address_info != None else 0.0

    @property
    def href(self):
        return make_address_ref(self) if self.address_info != None else None

    @property
    def consolidationinfo(self):
        return Session.object_session(self).query(
            AccountAutoConsolidationInfo
        ).filter(
            AccountAutoConsolidationInfo.account_id == self.account_id,
            AccountAutoConsolidationInfo.coin == self.coin
        ).first()


class AccountAutoConsolidationInfo(Base):
    __tablename__ = 'autopay'

    id = Column(Integer, primary_key=True)
    account_id = Column('account', Integer, ForeignKey('account.id'))
    coin = Column(String(5))
    pubkeyhash = Column(Binary(20))
    txout_type_id = Column('type', Integer)
    minbalance = Column(Float(asdecimal=True))
    maxbalance = Column(Float(asdecimal=True))
    interval = Column(Integer)

    account = relationship('Account', back_populates='_consolidationinfo')

    API_DATA_FIELDS = [
        'AccountAutoConsolidationInfo.address', 'AccountAutoConsolidationInfo.isreceiveaddress',
        minbalance, maxbalance, interval
    ]

    @property
    def txout_type(self):
        return TXOUT_TYPES.resolve(self.txout_type_id)

    @txout_type.setter
    def txout_type(self, txout_type):
        self.txout_type_id = TXOUT_TYPES.internal_id(txout_type)

    @property
    def address(self):
        return Coin.by_ticker(self.coin).encode_address(self.pubkeyhash, self.txout_type)

    @address.setter
    def address(self, address):
        hash, txout_type = Coin.by_ticker(self.coin).decode_address_and_type(address)
        if hash is None:
            raise ValueError('Cannot decode address %s for coin %s' % (address, self.coin))
        self.pubkeyhash = hash
        self.txout_type = txout_type

    @property
    def isreceiveaddress(self):
        return self.maxbalance == 0.0


class WalletManager(Base):
    __tablename__ = 'manager'

    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    tokenhash = Column(Binary(32), unique=True)

    accounts = relationship('Account', back_populates='manager', cascade='save-update, merge, delete')




