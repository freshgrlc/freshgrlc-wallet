import functools

from base64 import b64decode
from binascii import unhexlify
from flask import Flask, abort, request
from hashlib import sha256
from httplib import NOT_FOUND, NO_CONTENT
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from time import time

from apiobjs import SendRequest, SetConsolidationInfoRequest, get_value
from coininfo import Coin, CoinNotDefinedException
from connections import connectionmanager
from models import AUTH_TOKEN_SIZE, WalletManager, Account, make_tx_ref
from wallet import Wallet

from indexer.models import Transaction
from indexer.postprocessor import QueryDataPostProcessor


class APIException(Exception):
    pass


webapp = Flask('wallet-api')


def authenticate_manager(api_func):
    @functools.wraps(api_func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            abort(401)
        auth_header = auth_header.split(' ')
        if len(auth_header) != 2 or auth_header[0] != 'Bearer':
            abort(401)
        try:
            token = b64decode(auth_header[1])
        except TypeError:
            abort(401)
        if len(token) != AUTH_TOKEN_SIZE:
            abort(401)

        tokenhash = sha256(sha256(token).digest()).digest()

        dbsession = connectionmanager.database_session()
        manager = dbsession.query(WalletManager).filter(WalletManager.tokenhash == tokenhash).first()

        if manager == None:
            abort(401)

        kwargs['manager'] = manager
        return api_func(*args, **kwargs)
    return wrapper


def walletapi(api_func):
    @functools.wraps(api_func)
    def wrapper(*args, **kwargs):
        if 'manager' in kwargs:
            kwargs['wallet'] = Wallet(kwargs['manager'])
            if 'user' in kwargs:
                account = kwargs['wallet'].account(kwargs['user'])
                if account != None:
                    kwargs['account'] = account
                else:
                    abort(404)

        return api_func(*args, **kwargs)
    return wrapper


@webapp.route('/accounts/', methods=['GET'])
@authenticate_manager
def list_accounts(manager):
    with QueryDataPostProcessor() as pp:
        return pp.process(manager.accounts).json()


@webapp.route('/accounts/<user>/', methods=['GET'])
@authenticate_manager
@walletapi
def get_account(manager, wallet, account, user):
    with QueryDataPostProcessor() as pp:
        return pp.process(account.model).json()


@webapp.route('/accounts/<user>/consolidationinfo/', methods=['GET'])
@authenticate_manager
@walletapi
def get_account_consolidationinfo(manager, wallet, account, user):
    with QueryDataPostProcessor() as pp:
        return pp.process(account.model.consolidationinfo).json()


@webapp.route('/accounts/<user>/consolidationinfo/<coin>/', methods=['GET'])
@authenticate_manager
@walletapi
def get_account_coin_consolidationinfo(manager, wallet, account, user, coin):
    with QueryDataPostProcessor() as pp:
        try:
            coin = Coin.by_ticker(coin)
        except CoinNotDefinedException:
            return pp.process_raw(None).json()
        return pp.process(account.model.consolidationinfo_for(coin)).json()


@webapp.route('/accounts/<user>/consolidationinfo/<coin>/', methods=['DELETE'])
@authenticate_manager
@walletapi
def delete_account_coin_consolidationinfo(manager, wallet, account, user, coin):
    try:
        coin = Coin.by_ticker(coin)
    except CoinNotDefinedException:
        return '', NO_CONTENT

    current_value = account.model.consolidationinfo_for(coin)
    if current_value == None:
        return '', NO_CONTENT

    db = wallet._dbsession
    db.delete(current_value)
    db.commit()
    return '', NO_CONTENT


@webapp.route('/accounts/<user>/consolidationinfo/<coin>/', methods=['PUT'])
@authenticate_manager
@walletapi
def set_account_coin_consolidationinfo(manager, wallet, account, user, coin):
    try:
        coin = Coin.by_ticker(coin)
    except CoinNotDefinedException:
        return '', NOT_FOUND

    requestobj = SetConsolidationInfoRequest(request.get_json())
    requestobj.set_context_info(account=account, coin=coin)

    db = wallet._dbsession

    current_value = account.model.consolidationinfo_for(coin)
    if current_value != None:
        db.delete(current_value)
        db.flush()

    consolidationinfo = requestobj.dbobject()
    db.add(consolidationinfo)
    db.commit()

    with QueryDataPostProcessor() as pp:
        return pp.process(consolidationinfo).json()


@webapp.route('/accounts/<user>/send/', methods=['POST'])
@authenticate_manager
@walletapi
def send(manager, wallet, account, user):
    requestobj = SendRequest(request.get_json())
    sender = account.addresses[requestobj.coin]
    requestobj.destination.set_context_info(wallet=wallet, coin=sender.coin)

    tx = sender.transaction(requestobj.destination.address, requestobj.amount, spend_unconfirmed=True, subsidized=requestobj.low_priority)
    txid = tx.broadcast()
    txid_raw = unhexlify(txid)
    sent = time()

    db = connectionmanager.database_session(coin=sender.coin)
    tx_internal_id = None

    while time() < sent + 10:
        db.rollback()
        txobj = db.query(Transaction).filter(Transaction.txid == txid_raw).first()
        if txobj != None:
            tx_internal_id = txobj.id
            break

    if tx_internal_id is None:
        raise APIException('Transaction created but not seen on network after 10 seconds')

    with QueryDataPostProcessor() as pp:
        return pp.process_raw({
            'error': None,
            'destination': dict(requestobj.destination),
            'transaction': {
                'txid': txid,
                'href': make_tx_ref(sender.coin, txid)
            }
        }).json()


@webapp.route('/accounts/', methods=['POST'])
@authenticate_manager
@walletapi
def create_account(manager, wallet):
    user = get_value(request.get_json(), 'user')

    try:
        private_key = get_value(request.get_json(), 'privkey')
    except ValueError:
        private_key = None

    db_session = connectionmanager.database_session()

    if private_key is None:
        new_account = wallet.create_account(user, db_session=db_session)
    else:
        new_account = wallet.import_account(user, private_key, db_session=db_session)

    with QueryDataPostProcessor() as pp:
        return pp.process(new_account.model).json()


