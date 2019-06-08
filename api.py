import functools

from base64 import b64decode
from flask import Flask, abort, request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from connections import connectionmanager
from models import AUTH_TOKEN_SIZE, WalletManager

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


@webapp.route('/accounts/')
@authenticate_manager
def list_accounts(manager):
    with QueryDataPostProcessor() as pp:
        return pp.process(manager.accounts).json()



