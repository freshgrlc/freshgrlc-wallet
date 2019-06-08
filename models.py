import os

from binascii import unhexlify
from Crypto.Cipher import AES
from sqlalchemy import Binary, Column, ForeignKey, Integer, MetaData, String
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

import config
from coininfo import Coin
from connections import connectionmanager
from indexer.models import Address


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

    API_DATA_FIELDS = [ user ]
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


class WalletManager(Base):
    __tablename__ = 'manager'

    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    tokenhash = Column(Binary(32), unique=True)

    accounts = relationship('Account', back_populates='manager', cascade='save-update, merge, delete')




