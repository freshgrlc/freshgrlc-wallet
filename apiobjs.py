from datetime import datetime, timedelta
from decimal import Decimal

from coininfo import COINS
from models import AutomaticPayment


class _NoDefault(object): pass
NoDefault = _NoDefault()


def get_value(container, name, default=NoDefault):
    if container is not None and name in container and container[name] is not None:
        return container[name]
    if default == NoDefault:
        raise ValueError('Missing "%s"' % name)
    return default


class Destination(object):
    TYPES = []

    def __init__(self):
        self.wallet = None
        self.coin = None

    @classmethod
    def register(cls, dest_type):
        cls.TYPES.append(dest_type)

    @classmethod
    def parse(cls, json):
        destination_type = get_value(json, 'type')
        for destination_cls in cls.TYPES:
            if destination_cls.TYPE == destination_type:
                return destination_cls(json)
        raise ValueError('Invalid destination type "%s"' % destination_type)

    def set_context_info(self, wallet, coin):
        self.wallet = wallet
        self.coin = coin

        if not self.coin.valid_address(self.address):
            raise ValueError('Invalid destination address: %s' % self.address)


class AccountDestination(Destination):
    TYPE = 'account'

    def __init__(self, json):
        super(AccountDestination, self).__init__()
        self.user = get_value(json, 'user')
        self.allow_creation = bool(get_value(json, 'allowCreateNew', False))
        self._address = None
        self.created = False

    @property
    def address(self):
        if self._address is None:
            if self.wallet is None:
                raise Exception('Cannot get destination address without context information')

            account = self.wallet.account(self.user)
            if account == None:
                if self.allow_creation:
                    account = self.wallet.create_account(self.user)
                    self.created = True
                else:
                    raise ValueError('Unknown account/user: %s' % self.user)

            self._address = account.addresses[self.coin.ticker].preferred_address
        return self._address

    def __iter__(self):
        yield 'type', self.TYPE
        yield 'address', self.address
        yield 'user', self.user
        yield 'created', self.created


class AddressDestination(Destination):
    TYPE = 'address'

    def __init__(self, json):
        super(AddressDestination, self).__init__()
        self.address = str(get_value(json, 'address'))

    def __iter__(self):
        yield 'type', self.TYPE
        yield 'address', self.address


Destination.register(AccountDestination)
Destination.register(AddressDestination)


class SendRequest(object):
    def __init__(self, json):
        self.destination = Destination.parse(get_value(json, 'destination'))
        self.coin = str(get_value(json, 'coin')).lower()
        self.amount = Decimal(get_value(json, 'amount'))
        self.priority = str(get_value(json, 'priority', 'normal')).lower()

        if self.coin not in [ coin.ticker.lower() for coin in COINS ]:
            raise ValueError('Invalid coin "%s"' % self.coin)
        self.coin = { coin.ticker.lower(): coin for coin in COINS }[self.coin].ticker

        if self.priority not in ['normal', 'low', 'high']:
            raise ValueError('Invalid priority "%s"' % self.priority)

    @property
    def low_priority(self):
        self.priority == 'low'


class SetAutoPayInfoRequest(object):
    def __init__(self, json):
        self.address = str(get_value(json, 'address'))
        self.transaction = get_value(json, 'transaction')
        self.interval = get_value(json, 'interval')
        self.nextpayment = get_value(json, 'nextpayment', None)
        self.coin = None
        self.account = None

        if self.nextpayment is None:
            self.nextpayment = datetime.now()
        else:
            self.nextpayment = datetime(1970, 1, 1) + timedelta(seconds=int(self.nextpayment))

    def set_context_info(self, account, coin):
        self.account = account
        self.coin = coin

        if not self.coin.valid_address(self.address):
            raise ValueError('Invalid address "%s" for %s' % (self.address, self.coin.ticker))

    def dbobject(self):
        info = AutomaticPayment()
        info.account_id = self.account.model.id
        info.coin = self.coin.ticker
        info.address = self.address
        info.transaction = self.transaction
        info.interval = self.interval
        info.nextpayment = self.nextpayment
        return info
