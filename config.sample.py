
GRLC = {
    'name':                 'Garlicoin',
    'ticker':               'GRLC',
    'database': {
        'name':             'grlc'
    },
    'coindaemon': {
        'hostname':         'garlicoind',
        'port':             42068
    },
    'address_version':      38,
    'p2sh_address_version': 50,
    'privkey_version':      176,
    'segwit_info': {
        'addresstype':      'base58',
        'address_version':  73,
        'receive_only':     True
    },
    'allow_tx_subsidy':     False
}


TGRLC = {
    'name':                 'Garlicoin Testnet',
    'ticker':               'tGRLC',
    'database': {
        'name':             'tgrlc'
    },
    'coindaemon': {
        'hostname':         'garlicoind-testnet',
        'port':             42070
    },
    'address_version':      111,
    'p2sh_address_version': 58,
    'privkey_version':      239,
    'segwit_info':          None,
    'allow_tx_subsidy':     False
}


TUX = {
    'name':                 'Tuxcoin',
    'ticker':               'TUX',
    'database': {
        'name':             'tux'
    },
    'coindaemon': {
        'hostname':         'tuxcoind',
        'port':             42072
    },
    'address_version':      65,
    'p2sh_address_version': 64,
    'privkey_version':      193,
    'segwit_info': {
        'addresstype':      'bech32',
        'address_prefix':   'tux',
        'receive_only':     False
    },
    'allow_tx_subsidy':     False
}


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
