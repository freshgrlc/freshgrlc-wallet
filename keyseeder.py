from coinsupport.addresscodecs import decode_base58_address, decode_privkey

import config
from coininfo import KEYSEEDER_INFO
from connections import connectionmanager

def generate_key():
    daemon = connectionmanager.keyseeder()
    address = daemon.getnewaddress()
    privkey = daemon.dumpprivkey(address)
    _, pubkeyhash = decode_base58_address(address.encode('utf-8'), verify_version=KEYSEEDER_INFO.address_version)
    _, privkey, _ = decode_privkey(privkey.encode('utf-8'), verify_version=KEYSEEDER_INFO.privkey_version)
    return privkey, pubkeyhash
