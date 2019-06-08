from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from coininfo import KEYSEEDER_INFO
from indexer.coindaemon import Daemon


class ConnectionManager(object):
    db_engines = {}

    def __init__(self):
        self.sql_debug = False

    @staticmethod
    def database_url(database_name):
        return '%s://%s@%s/%s' % (config.DATABASE_PROTOCOL, ':'.join(config.DATABASE_CREDENTIALS), config.DATABASE_HOST, database_name)

    def database_session(self, coin=None):
        database_name = config.DATABASE_WALLET_DB if coin is None else coin.db_table
        if not database_name in self.db_engines:
            self.db_engines[database_name] = create_engine(self.database_url(database_name), encoding='utf8', echo=self.sql_debug)
        return sessionmaker(self.db_engines[database_name])()

    @staticmethod
    def coindaemon_url(coin, credentials=config.COINDAEMON_CREDENTIALS):
        return 'http://%s@%s:%d' % (':'.join(credentials), coin.rpc_host, coin.rpc_port)

    def coindaemon(self, coin):
        return Daemon(self.coindaemon_url(coin))

    def keyseeder(self):
        return Daemon(self.coindaemon_url(KEYSEEDER_INFO, credentials=config.KEYSEEDER_CREDENTIALS))


connectionmanager = ConnectionManager()
