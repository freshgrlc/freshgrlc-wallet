from base64 import b64decode
from binascii import hexlify, unhexlify
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import func

from codec import decode_base58_address, decode_privkey
from coininfo import COINS, Coin
from connections import connectionmanager
from keyseeder import generate_key
from models import *
from transaction import UnsignedTransactionBuilder, SignedTransaction, FEERATE_NETWORK, FEERATE_POOLSUBSIDY, TransactionInput as UnsignedTransactionInput
from indexer import import_address
from indexer.models import *


MIN_CONSOLIDATION_UTXOS = 100
MAX_CONSOLIDATION_UTXOS = 650


TXIN_VSIZES = {
    TXOUT_TYPES.P2PKH:  149,
    TXOUT_TYPES.P2WPKH: 68
}


class AccountExistsException(Exception):
    pass


class InvalidAccountName(Exception):
    pass


class Wallet(object):
    def __init__(self, manager):
        self.manager = manager

    @classmethod
    def get(cls, token, format='raw', dbsession=None):
        token = {
            'raw':    lambda x: x,
            'base64': lambda x: b64decode(x),
            'hex':    lambda x: unhexlify(x)
        }[format](token)

        if dbsession is None:
            dbsession = connectionmanager.database_session()

        manager = dbsession.query(WalletManager).filter(WalletManager.token == token).first()
        if manager != None:
            return cls(manager)

    def create_or_import_account(self, name, get_key_cb, db_session=None):
        if type(name) not in (str, unicode) or len(name.encode('utf-8')) > ACCOUNT_NAME_LEN:
            raise InvalidAccountName(name)

        db = db_session if db_session is not None else connectionmanager.database_session()
        existing_account = db.query(Account).filter(
            Account.manager_id == self.manager.id,
            Account.user == name
        ).first()

        if existing_account != None:
            raise AccountExistsException(name)

        account = Account()
        account.manager_id = self.manager.id
        account.user = name

        privkey, pubkeyhash = get_key_cb()
        account.private_key = privkey
        account.pubkeyhash = pubkeyhash

        db.add(account)
        db.flush()

        for coin in COINS:
            try:
                addresses = coin.get_addresses_for_pubkeyhash(pubkeyhash)
                coin_db = connectionmanager.database_session(coin)
                coin_daemon = connectionmanager.coindaemon(coin)

                for address_id in [ import_address(address, dbsession=coin_db, daemon=coin_daemon) for address in addresses ]:
                    account_address = AccountAddress()
                    account_address.account_id = account.id
                    account_address.coin = coin.ticker
                    account_address.address_id = address_id
                    db.add(account_address)

                coin_db.commit()
            except Exception as e:
                print('Failed to import %s addresses for new account "%s": %s' % (coin.ticker, name, e))
                coin_db.rollback()
                db.rollback()
                raise

        db.flush()
        db.commit()
        return WalletAccount(self, account)

    def create_account(self, name, db_session=None):
        return self.create_or_import_account(name, generate_key, db_session=db_session)

    def import_account(self, name, address, db_session=None):
        def decode(privkey, address):
            for coin in COINS:
                try:
                    _, pubkeyhash = decode_base58_address(address.encode('utf-8'), verify_version=coin.address_version)
                    _, privkey, _ = decode_privkey(privkey.encode('utf-8'), verify_version=coin.privkey_version)
                    return privkey, pubkeyhash
                except ValueError:
                    continue
            raise ValueError('Could not decode address or private key')

        return self.create_or_import_account(name, lambda: decode(*address), db_session=db_session)

    @property
    def _dbsession(self):
        return Session.object_session(self.manager)

    @property
    def accounts(self):
        return [ WalletAccount(self, account) for account in self.manager.accounts ]

    def account(self, name):
        account = self._dbsession.query(Account).filter(
            Account.manager_id == self.manager.id,
            Account.user == name
        ).first()
        return WalletAccount(self, account) if account != None else None


class WalletAccount(object):
    def __init__(self, wallet, account):
        self.wallet = wallet
        self.model = account
        self.addresses = {coin.ticker: WalletAddress(self, coin) for coin in COINS}


class WalletAddress(object):
    def __init__(self, account, coin):
        self.account = account
        self.coin = coin
        self.db = connectionmanager.database_session(coin=self.coin)
        self._addresses = None

    @property
    def address_ids(self):
        if self._addresses is None:
            self._addresses = [ results[0] for results in self.db.query(
                AccountAddress.address_id
            ).filter(
                AccountAddress.account_id == self.account.model.id,
                AccountAddress.coin == self.coin.ticker
            ).all() ]
        return self._addresses

    def _preferred_address(self, forchange=False):
        if not forchange:
            consolidation_info = self.account.model.consolidationinfo_for(self.coin)
            if consolidation_info != None and consolidation_info.isreceiveaddress:
                return consolidation_info.address
        return self.coin.get_default_receive_address(self.account.model.pubkeyhash)

    @property
    def preferred_address(self):
        return self._preferred_address()

    @property
    def preferred_change_address(self):
        return self._preferred_address(forchange=True)

    def daemon(self):
        return connectionmanager.coindaemon(self.coin)

    def query_utxoset(self, colums, include_unconfirmed=False, include_immature=False, max_utxos=None):
        do_limit_utxos = lambda x: x if max_utxos is None else x.order_by(TransactionOutput.id).limit(max_utxos)

        if include_unconfirmed and include_immature:
            return do_limit_utxos(
                self.db.query(*colums).join(
                    Address
                ).join(
                    TransactionOutput.transaction
                ).join(
                    TransactionOutput.spenders,
                    isouter=True
                ).join(
                    Transaction.blockreferences,
                    isouter=True
                ).filter(
                    Address.id.in_(self.address_ids),
                    TransactionOutput.spentby_id == None,
                    TransactionInput.id == None,
                    or_(
                        BlockTransaction.block_id == None,
                        Transaction.confirmation_id != None
                    )
                )
            )

        if include_unconfirmed:
            return do_limit_utxos(
                self.db.query(*colums).join(
                    Address
                ).join(
                    TransactionOutput.transaction
                ).join(
                    TransactionOutput.spenders,
                    isouter=True
                ).join(
                    Transaction.coinbaseinfo,
                    isouter=True
                ).join(
                    CoinbaseInfo.block,
                    isouter=True
                ).filter(
                    Address.id.in_(self.address_ids),
                    TransactionOutput.spentby_id == None,
                    TransactionInput.id == None,
                    or_(
                        CoinbaseInfo.block_id == None,
                        Block.height <= self.coin.current_coinbase_confirmation_height()
                    )
                )
            )

        return do_limit_utxos(
            self.db.query(*colums).join(
                Address
            ).join(
                TransactionOutput.transaction
            ).join(
                TransactionOutput.spenders,
                isouter=True
            ).join(
                Transaction.coinbaseinfo,
                isouter=True
            ).join(
                CoinbaseInfo.block,
                isouter=True
            ).filter(
                Address.id.in_(self.address_ids),
                TransactionOutput.spentby_id == None,
                TransactionInput.id == None,
                Transaction.confirmation != None,
                or_(
                    CoinbaseInfo.block_id == None,
                    Block.height <= self.coin.current_coinbase_confirmation_height()
                )
            )
        )


    def balance(self, include_unconfirmed=False, include_immature=False):
        return self.query_utxoset(
            (
                func.sum(TransactionOutput.amount),
            ),
            include_unconfirmed=include_unconfirmed,
            include_immature=include_immature
        ).first()[0]

    def walletinfo(self, include_unconfirmed=False, include_immature=False):
        results = self.query_utxoset(
            (
                func.count(TransactionOutput.id),
                func.sum(TransactionOutput.amount),
                Address.address
            ),
            include_unconfirmed=include_unconfirmed,
            include_immature=include_immature
        ).group_by(Address.id).all()

        return { address: { 'balance': balance, 'utxos': utxos } for utxos, balance, address in results }

    def utxos(self, include_unconfirmed=False, max_utxos=None):
        return [{
                'txid':         hexlify(txid),
                'vout':         int(vout),
                'txouttype':    TXOUT_TYPES.resolve(txtype),
                'segwit':       TXOUT_TYPES.resolve(txtype) in [ TXOUT_TYPES.P2WPKH, TXOUT_TYPES.P2WSH ],
                'txin_vsize':   TXIN_VSIZES[TXOUT_TYPES.resolve(txtype)],
                'amount':       amount,
                'address':      address
            } for _, address, txid, vout, txtype, amount in self.query_utxoset(
                (
                    TransactionOutput.id,
                    Address.address,
                    Transaction.txid,
                    TransactionOutput.index,
                    TransactionOutput.type_id,
                    TransactionOutput.amount
                ),
                include_unconfirmed=include_unconfirmed,
                max_utxos=max_utxos
            ).all()
        ]

    def transaction(self, destination_address, amount, return_address=None, spend_unconfirmed=False, subsidized=False):
        if return_address is None:
            return_address = self.preferred_change_address

        tx = UnsignedTransactionBuilder(self.coin, feerate=(FEERATE_NETWORK if not subsidized or not self.coin.allow_tx_subsidy else FEERATE_POOLSUBSIDY))
        tx.add_output(destination_address, amount)
        tx.fund_transaction(self.utxos(include_unconfirmed=spend_unconfirmed), return_address)
        return self.sign_transaction(tx)

    def consolidate(self, destination_address=None, include_unconfirmed=False, subsidized=False, max_utxos=MAX_CONSOLIDATION_UTXOS):
        if destination_address is None:
            destination_address = self.preferred_change_address

        tx = UnsignedTransactionBuilder(self.coin, feerate=(FEERATE_NETWORK if not subsidized or not self.coin.allow_tx_subsidy else FEERATE_POOLSUBSIDY))

        for utxo in self.utxos(include_unconfirmed=include_unconfirmed, max_utxos=max_utxos):
            tx.add(UnsignedTransactionInput(utxo))

        tx.add_return_output(destination_address)
        return self.sign_transaction(tx).broadcast()

    def sign_transaction(self, transaction):
        daemon = self.daemon()
        encoded_private_key = self.coin.encode_private_key(self.account.model.private_key)
        return SignedTransaction(transaction, daemon.sign_transaction(hexlify(transaction.raw()), [ encoded_private_key ]), coindaemon=daemon)
