from gevent import monkey; monkey.patch_all()

import functools
import json

from base64 import b64decode
from binascii import unhexlify
from flask import Flask, abort, request, Response
from hashlib import sha256
from httplib import NO_CONTENT, BAD_REQUEST, UNAUTHORIZED, NOT_FOUND, INTERNAL_SERVER_ERROR
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from time import time, sleep

from apiobjs import SendRequest, SetAutoPayInfoRequest, get_value
from coininfo import Coin, CoinNotDefinedException
from connections import connectionmanager
from models import AUTH_TOKEN_SIZE, WalletManager, Account, make_tx_ref
from wallet import Wallet

from indexer.models import Transaction
from indexer.postprocessor import QueryDataPostProcessor


webapp = Flask('wallet-api')


def _json(obj, code=200):
    return Response(json.dumps(obj), code, mimetype='application/json')


def exception_handler(error, code):
    try:
        error = error.original_exception
    except AttributeError: pass
    return _json({
        'code': code,
        'error': {
            'type': error.__class__.__name__,
            'message': str(error)
        }
    }, code)

@webapp.errorhandler(BAD_REQUEST)
def bad_request_handler(e):
    return exception_handler(e, BAD_REQUEST)

@webapp.errorhandler(UNAUTHORIZED)
def unauthorized_handler(e):
    return exception_handler(e, UNAUTHORIZED)

@webapp.errorhandler(INTERNAL_SERVER_ERROR)
def internal_server_error_handler(e):
    return exception_handler(e, INTERNAL_SERVER_ERROR)

@webapp.errorhandler(NOT_FOUND)
def not_found_handler(_):
    return _json(None, NOT_FOUND)



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


@webapp.route('/accounts/<user>/autopayments/', methods=['GET'])
@authenticate_manager
@walletapi
def get_account_autopayments(manager, wallet, account, user):
    with QueryDataPostProcessor() as pp:
        return pp.process_raw(account.model.autopayments).json()


@webapp.route('/accounts/<user>/autopayments/<coin>/', methods=['GET'])
@authenticate_manager
@walletapi
def get_account_coin_autopayments(manager, wallet, account, user, coin):
    with QueryDataPostProcessor() as pp:
        try:
            coin = Coin.by_ticker(coin)
        except CoinNotDefinedException:
            return pp.process_raw(None).json()
        return pp.process(account.model.autopayments_for(coin)).json()


@webapp.route('/accounts/<user>/autopayments/<coin>/', methods=['DELETE'])
@authenticate_manager
@walletapi
def delete_account_coin_autopayments(manager, wallet, account, user, coin):
    try:
        coin = Coin.by_ticker(coin)
    except CoinNotDefinedException:
        return '', NO_CONTENT

    current = account.model.autopayments_for(coin)
    if len(current) == 0:
        return '', NO_CONTENT

    db = wallet._dbsession
    for autopay_config in current:
        db.delete(autopay_config)
    db.commit()
    return '', NO_CONTENT


@webapp.route('/accounts/<user>/autopayments/<coin>/', methods=['POST'])
@authenticate_manager
@walletapi
def add_account_coin_autopayment(manager, wallet, account, user, coin):
    try:
        coin = Coin.by_ticker(coin)
    except CoinNotDefinedException:
        return '', NOT_FOUND

    autopayment_info = SetAutoPayInfoRequest(request.get_json())
    autopayment_info.set_context_info(account=account, coin=coin)

    db = wallet._dbsession

    autopayment = autopayment_info.dbobject()
    db.add(autopayment)
    db.commit()

    with QueryDataPostProcessor() as pp:
        return pp.process(autopayment).json()


@webapp.route('/accounts/<user>/autopayments/<coin>/', methods=['PUT'])
@authenticate_manager
@walletapi
def set_account_coin_autopayments(manager, wallet, account, user, coin):
    try:
        coin = Coin.by_ticker(coin)
    except CoinNotDefinedException:
        return '', NOT_FOUND

    db = wallet._dbsession

    for autopayment in account.model.autopayments_for(coin):
        db.delete(autopayment)

    autopayments = []
    for info in request.get_json():
        autopayment_info = SetAutoPayInfoRequest(info)
        autopayment_info.set_context_info(account=account, coin=coin)
        autopayment = autopayment_info.dbobject()
        db.add(autopayment)
        autopayments.append(autopayment)

    db.commit()

    with QueryDataPostProcessor() as pp:
        return pp.process(autopayments).json()


@webapp.route('/accounts/<user>/send/', methods=['POST'])
@authenticate_manager
@walletapi
def send(manager, wallet, account, user):
    requestobj = SendRequest(request.get_json())
    sender = account.addresses[requestobj.coin]
    requestobj.destination.set_context_info(wallet=wallet, coin=sender.coin)

    tx = sender.transaction(requestobj.destination.address, requestobj.amount, spend_unconfirmed=True, subsidized=requestobj.low_priority)
    txid = tx.broadcast(wait_until_seen_on_network=True)

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


