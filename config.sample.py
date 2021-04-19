from coinsupport.coins import GRLC, TGRLC, TUX


GRLC['database']['name'] = 'grlc'
GRLC['coindaemon']['hostname'] = '172.0.0.1'
GRLC['allow_tx_subsidy'] = False

TGRLC['database']['name'] = 'tgrlc'
TGRLC['coindaemon']['hostname'] = '172.0.0.1'
TGRLC['allow_tx_subsidy'] = False

TUX['database']['name'] = 'tux'
TUX['coindaemon']['hostname'] = '172.0.0.1'
TUX['allow_tx_subsidy'] = False


KEYSEEDER = {
    'name':                 'Keyseeder',
    'ticker':               None,
    'database':             None,
    'coindaemon': {
        'hostname':         'keyseeder',
        'port':             GRLC['coindaemon']['port']
    },
    'address_version':      GRLC['address_version'],
    'p2sh_address_version': GRLC['p2sh_address_version'],
    'privkey_version':      GRLC['privkey_version'],
    'segwit_info':          None,
    'allow_tx_subsidy':     False
}


DATABASE_PROTOCOL   = 'mysql+pymysql'
DATABASE_HOST       = 'mariadb'
DATABASE_WALLET_DB  = 'wallets'
ENCRYPTION_KEY      = '00112233445566778899aabbccddeeff'


DATABASE_CREDENTIALS    = ('wallet', 'databasepassword')
COINDAEMON_CREDENTIALS  = ('rpc', 'rpcpassword')
KEYSEEDER_CREDENTIALS   = ('rpc', 'rpcpassword')


COINS = [ GRLC, TUX, TGRLC ]


API_ENDPOINT = ''
INDEXER_API_ENDPOINT = ''
INDEXER_ADDRESS_API_PATH = '/address'
INDEXER_TRANSACTION_API_PATH = '/transactions'
