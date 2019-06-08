import functools

from base64 import b64decode
from flask import Flask, abort, request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from connections import connectionmanager
from models import AUTH_TOKEN_SIZE, WalletManager, Account
from wallet import Wallet

from indexer.postprocessor import QueryDataPostProcessor


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

        dbsession = connectionmanager.database_session()
        manager = dbsession.query(WalletManager).filter(WalletManager.token == token).first()

        if manager == None:
            abort(401)

        kwargs['manager'] = manager
        return api_func(*args, **kwargs)
    return wrapper


@webapp.route('/accounts/', methods=['GET'])
@authenticate_manager
def list_accounts(manager):
    with QueryDataPostProcessor() as pp:
        return pp.process(manager.accounts).json()


@webapp.route('/accounts/<user>/', methods=['GET'])
@authenticate_manager
def get_account(manager, user):
    dbsession = Session.object_session(manager)
    with QueryDataPostProcessor() as pp:
        return pp.process(
            dbsession.query(Account).filter(
                Account.manager_id == manager.id,
                Account.user == user
            ).first()
        ).json()


@webapp.route('/accounts/', methods=['POST'])
@authenticate_manager
def create_account(manager):
    user = request.get_json()['user']
    wallet = Wallet(manager)
    new_account = wallet.create_account(user)

    with QueryDataPostProcessor() as pp:
        return pp.process(new_account.account).json()


