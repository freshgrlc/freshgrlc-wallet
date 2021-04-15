from binascii import unhexlify
from decimal import Decimal
from struct import pack

from indexer.models import TXOUT_TYPES

from opcodes import *

FEERATE_NETWORK = Decimal('0.001')
FEERATE_POOLSUBSIDY = Decimal('0.00005')

DUST_LIMIT = Decimal('0.0005')


class InvalidHashException(Exception):
    pass

class FeeCalculationError(Exception):
    pass

class NotEnoughCoinsException(Exception):
    pass


def _op(*vargs):
    return b''.join([ pack('B', op) for op in vargs ])

def encode_varint(i):
    if i < 0xfd:
        return pack('B', i)
    if i < 0x10000:
        return pack('<BH', 0xfd, i)
    if i < 0x100000000:
        return pack('<BI', 0xfe, i)
    return pack('<BQ', 0xff, i)

def encode_int(i):
    return pack('I', i)

def encode_blob(raw):
    return encode_varint(len(raw)) + raw

def encode_hexblob(raw):
    return encode_blob(unhexlify(raw))

def encode_pushdata(hex):
    return _op(OP_PUSHDATA) + encode_hexblob(hex)


class TransactionInput(object):
    def __init__(self, utxo):
        self.address = utxo['address']
        self.amount = utxo['amount']
        self.txid = utxo['txid']
        self.raw_txid = unhexlify(utxo['txid'])
        self.vout = utxo['vout']
        self.estimated_size = utxo['txin_vsize']
        self.txout_type = utxo['txouttype']
        self.need_witness_section = utxo['segwit']

    def raw(self):
        return self.raw_txid[::-1] + encode_int(self.vout) + encode_varint(0) + encode_int(0xffffffff)


class TransactionOutput(object):
    def __init__(self, destination_hash, output_type, amount):
        self.set_amount(amount)
        self.script = self.build_output_script(destination_hash, output_type)

    def set_amount(self, value):
        self.amount = value
        self.satoshis = int(value * 100000000)

    def build_output_script(self, destination_hash, output_type):
        if output_type in [ TXOUT_TYPES.P2PKH, TXOUT_TYPES.P2SH, TXOUT_TYPES.P2WPKH ] and len(destination_hash) != 20:
            raise InvalidHashException('Hash "%s" invalid for transaction output type "%s"' % (destination_hash, output_type))

        if output_type in [ TXOUT_TYPES.P2WSH ] and len(destination_hash) != 32:
            raise InvalidHashException('Hash "%s" invalid for transaction output type "%s"' % (destination_hash, output_type))

        if output_type == TXOUT_TYPES.P2PKH:
            return _op(OP_DUP, OP_HASH160) + encode_blob(destination_hash) + _op(OP_EQUALVERIFY, OP_CHECKSIG)
        if output_type == TXOUT_TYPES.P2SH:
            return _op(OP_HASH160) + encode_blob(destination_hash) + _op(OP_EQUAL)
        if output_type == TXOUT_TYPES.P2WPKH:
            return _op(OP_0) + encode_blob(destination_hash)

        raise InvalidHashException('Unsupported transaction ouput type "%s"' % output_type)

    def raw(self):
        return pack('Q', self.satoshis) + encode_blob(self.script)


class UnsignedTransactionBuilder(object):
    VERSION = 2

    def __init__(self, coin, feerate=FEERATE_NETWORK):
        self.coin = coin
        self.inputs = []
        self.outputs = []
        self.feerate = feerate

    def estimated_size(self):
        length = len(self.raw())

        if len(filter(lambda txin: txin.need_witness_section, self.inputs)) > 0:
            length += 2     # Witness header flag

        length += sum([ txin.estimated_size - len(txin.raw()) for txin in self.inputs ])

        return length

    def raw(self):
        return  encode_int(self.VERSION) + \
                encode_varint(len(self.inputs)) + \
                b''.join([ txin.raw() for txin in self.inputs ]) + \
                encode_varint(len(self.outputs)) + \
                b''.join([ txout.raw() for txout in self.outputs ]) + \
                encode_int(0)

    def required_keys(self):
        return list(set([ txin.address for txin in self.inputs ]))

    def add(self, in_out):
        if isinstance(in_out, TransactionInput):
            self.inputs.append(in_out)
        elif isinstance(in_out, TransactionOutput):
            self.outputs.append(in_out)

    def add_output(self, address, amount):
        pubkeyhash, output_type = self.coin.decode_address_and_type(address)
        self.add(TransactionOutput(pubkeyhash, output_type, amount))

    def add_return_output(self, address):
        pubkeyhash, output_type = self.coin.decode_address_and_type(address)
        return_tx = TransactionOutput(pubkeyhash, output_type, 0)
        self.add(return_tx)
        return_tx.set_amount(self.total_in() - self.total_out() - self.required_fee())

        if not self.fee_is_sane():
            raise FeeCalculationError()

    def fund_transaction(self, utxos, return_address):
        # Step 1: Check if the payout target is within reach (assumes no dust inputs)
        for utxo in utxos:
            self.add(TransactionInput(utxo))

        if not self.funded():
            raise NotEnoughCoinsException('Need at least %f for outputs and fees, got only %f in funds' % (self.total_out() + self.required_fee(), self.total_in()))

        # Step 2: Start adding transactions until we hit the target, lowest inputs first

        self.inputs = []
        utxos.sort(cmp=lambda x, y: 1 if x['amount'] > y['amount'] else -1)

        for utxo in utxos:
            self.add(TransactionInput(utxo))
            if self.funded():
                break

        # Step 3: Remove unecessary inputs

        self.inputs.reverse()

        while not self.fee_is_sane():
            fee_mismatch = self.current_fee() - self.required_fee()

            for input in self.inputs:
                # Only remove input if it does not generate more tiny utxos, otherwise consolidate
                if input.amount > DUST_LIMIT and (input.amount * 2 < fee_mismatch or input.amount + 1 < fee_mismatch):
                    self.inputs.remove(input)
                    break
            break

        if self.current_fee() - self.required_fee() > DUST_LIMIT:
            self.add_return_output(return_address)

    def funded(self):
        amount_in = self.total_in()
        amount_out = self.total_out()
        fee_out = self.required_fee()
        min_amount_out = amount_out + fee_out
        max_amount_out = amount_out + 2 * fee_out
        min_amount_out_with_return_output = min_amount_out + DUST_LIMIT

        return (amount_in >= min_amount_out and amount_in <= max_amount_out) or amount_in >= min_amount_out_with_return_output

    def total_in(self):
        return sum([ txin.amount for txin in self.inputs ])

    def total_out(self):
        return sum([ txout.amount for txout in self.outputs ])

    def required_fee(self):
        return self.estimated_size() * self.feerate / 1000

    def current_fee(self):
        return self.total_in() - self.total_out()

    def fee_is_sane(self):
        curfee = self.current_fee()
        targetfee = self.required_fee()
        return curfee >= targetfee and curfee < targetfee * Decimal('1.1')


class SignedTransaction(object):
    def __init__(self, unsigned_tx_info, raw_signed_tx, coindaemon=None):
        self.inputs = unsigned_tx_info.inputs
        self.outputs = unsigned_tx_info.outputs
        self.total_in = unsigned_tx_info.total_in()
        self.total_out = unsigned_tx_info.total_out()
        self.fee = unsigned_tx_info.current_fee()
        self.target_feerate = unsigned_tx_info.feerate
        self.estimated_size = unsigned_tx_info.estimated_size()
        self.hex = raw_signed_tx
        self.raw = unhexlify(raw_signed_tx)
        self.size = len(self.raw)
        self.actual_feerate = self.fee / self.size * 1000
        self.coindaemon = coindaemon

    def broadcast(self, coindaemon=None):
        return (coindaemon if coindaemon is not None else self.coindaemon).sendrawtransaction(self.hex)

