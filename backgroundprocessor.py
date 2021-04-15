from binascii import hexlify
from datetime import datetime, timedelta
from sqlalchemy import func as sqlfunc, or_
from time import sleep

from coininfo import COINS
from connections import connectionmanager
from models import Account, AccountAddress
from wallet import WalletAccount, MIN_CONSOLIDATION_UTXOS, MAX_CONSOLIDATION_UTXOS

from indexer.logger import log_event
from indexer.models import Address, Block, CoinbaseInfo, Transaction, TransactionInput, TransactionOutput


MAX_QUEUED_TXS = 8


class CoinState(object):
    def __init__(self):
        self.lastcheck = datetime.utcfromtimestamp(0)
        self.lastblockhash = b''

    def update(self, blockhash):
        self.lastblockhash = blockhash
        now = datetime.now()

        if now - self.lastcheck < timedelta(seconds=60):
            return False

        self.lastcheck = now
        return True


def run_background_tasks_for_coin(coin, dbsession, max_work=MAX_QUEUED_TXS):
    for account_address_id, account, address, utxos in dbsession.query(
        AccountAddress.id,
        Account,
        Address.address,
        sqlfunc.count(TransactionOutput.id)
    ).join(
        AccountAddress.account
    ).join(
        Address,
        AccountAddress.address_id == Address.id
    ).join(
        TransactionOutput,
        Address.id == TransactionOutput.address_id,
        isouter=True
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
        AccountAddress.coin == coin.ticker,
        TransactionOutput.spentby_id == None,
        TransactionInput.id == None,
        or_(
            CoinbaseInfo.block_id == None,
            Block.height <= coin.current_coinbase_confirmation_height()
        )
    ).group_by(Address.id).having(
        sqlfunc.count(TransactionOutput.id) >= MIN_CONSOLIDATION_UTXOS
    ).all():
        log_event('Consol.', 'Addr', address, '%d utxos' % utxos)
        transaction_manager = WalletAccount(None, account).addresses[coin.ticker]
        txid = transaction_manager.consolidate(subsidized=True)
        log_event('Broadc.', 'Tx', txid)

        max_work -= 1
        if max_work <= 0:
            break


def main():
    STATE = { coin.ticker: CoinState() for coin in COINS }

    while True:
        sleep(10)
        try:
            for coin in COINS:
                state = STATE[coin.ticker]

                session = connectionmanager.database_session(coin=coin)
                lastblock = session.query(Block).order_by(Block.height.desc()).first()
                if lastblock.hash == state.lastblockhash:
                    continue

                log_event('New', 'Blk', hexlify(lastblock.hash), 'chain = ' + coin.ticker)
                should_run = state.update(lastblock.hash)

                if not should_run:
                    log_event('Ign', 'Blk', hexlify(lastblock.hash), 'too soon')
                    continue

                txs_queued = len(connectionmanager.coindaemon(coin).getrawmempool())
                max_work = MAX_QUEUED_TXS - txs_queued

                if max_work <= 0:
                    log_event('Ign', 'Blk', hexlify(lastblock.hash), 'mempool full')
                    continue

                log_event('Check', 'Chn', coin.ticker, '%d entries in mempool, max = %d' % (txs_queued, MAX_QUEUED_TXS))
                run_background_tasks_for_coin(coin, session, max_work=max_work)
                log_event('Finish', 'Chn', coin.ticker)

        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
