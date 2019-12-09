import datetime
import logging

import rapidjson as json
from aiohttp import log, web
from tortoise.transactions import in_transaction

import config
from db.models.wallet import Wallet, WalletLocked, WalletNotFound, AccountAlreadyExists
from network.rpc_client import AccountNotFound, BlockNotFound, RPCClient
from util.crypt import DecryptionError
from util.random import RandomUtil
from util.validators import Validators
from util.wallet import (InsufficientBalance, ProcessFailed, WalletUtil,
                         WorkFailed)


class PippinServer(object):
    """API for wallet requests"""
    def __init__(self, host: str, port: int):
        self.app = web.Application(middlewares=[web.normalize_path_middleware()])
        self.app.add_routes([
            web.post('/', self.gateway)
        ])
        self.host = host
        self.port = port

    async def stop(self):
        await self.app.shutdown()

    def json_response(self, data: dict):
        """Wrapper for json responses using custom json parser"""
        return web.json_response(
            data=data,
            dumps=json.dumps
        )

    def generic_error(self):
        """The node returns this generic error when the request is bad"""
        return self.json_response(
            data={
                'error':"Unable to parse json"
            }
        )

    async def gateway(self, request: web.Request):
        """Gateway route to mimic nano's API of specifying action in a string"""
        request_json = await request.json(loads=json.loads)      
        if 'action' in request_json:
            # Sanitize action
            request_json['action'] = request_json['action'].lower().strip()

            # Handle wallet RPCs
            if request_json['action'] == 'wallet_create':
                return await self.wallet_create(request, request_json)
            elif request_json['action'] == 'account_create':
                return await self.account_create(request, request_json)
            elif request_json['action'] == 'accounts_create':
                return await self.accounts_create(request, request_json)
            elif request_json['action'] == 'account_list':
                return await self.account_list(request, request_json)
            elif request_json['action'] == 'receive':
                return await self.receive(request, request_json)
            elif request_json['action'] == 'send':
                return await self.send(request, request_json)
            elif request_json['action'] == 'account_representative_set':
                return await self.account_representative_set(request, request_json)
            elif request_json['action'] == 'password_change':
                return await self.password_change(request, request_json)
            elif request_json['action'] == 'password_enter':
                return await self.password_enter(request, request_json)
            elif request_json['action'] == 'password_valid':
                return await self.password_valid(request, request_json)
            elif request_json['action'] == 'wallet_representative_set':
                return await self.wallet_representative_set(request, request_json)
            elif request_json['action'] == 'wallet_add':
                return await self.wallet_add(request, request_json)
            elif request_json['action'] == 'wallet_lock':
                return await self.wallet_lock(request, request_json)
            elif request_json['action'] == 'wallet_locked':
                return await self.wallet_locked(request, request_json)
            elif request_json['action'] in ['account_move', 'account_remove', 'receive_minimum', 'receive_minimum_set', 'search_pending', 'search_pending_all', 'wallet_add_watch', 'wallet_balances', 'wallet_change_seed', 'wallet_contains', 'wallet_destroy', 'wallet_export', 'wallet_frontiers', 'wallet_history', 'wallet_info', 'wallet_ledger', 'wallet_pending', 'wallet_representative', 'wallet_republish', 'wallet_work_get', 'work_get', 'work_set']:
                # Prevent unimplemented wallet RPCs from going to the node directly
                return self.json_response(
                    data = {
                        'error': 'not_implemented'
                    }
                )

            # Proxy other requests to the node
            resp_json = await RPCClient.instance().make_request(request_json)
            return self.json_response(
                data = resp_json
            )

        return self.generic_error()

    async def wallet_create(self, request: web.Request, request_json: dict):
        """Route for creating new wallet"""
        if 'seed' in request_json:
            if not Validators.is_valid_block_hash(request_json['seed']):
                return self.json_response(
                    data = {'error': 'Invalid seed'}
                )
            new_seed = request_json['seed']
        else:
            new_seed = RandomUtil.generate_seed()
        async with in_transaction() as conn:
            wallet = Wallet(
                seed=new_seed
            )
            await wallet.save(using_db=conn)
            await wallet.account_create(using_db=conn)
        return self.json_response(
            data = {
                'wallet': str(wallet.id)
            }
        )

    async def account_create(self, request: web.Request, request_json: dict):
        """Route for creating new wallet"""
        if 'wallet' not in request_json:
            return self.generic_error()

        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Create account
        async with in_transaction() as conn:
            account = await wallet.account_create(using_db=conn)
        return self.json_response(
            data = {
                'account': account
            }
        )

    async def accounts_create(self, request: web.Request, request_json: dict):
        """Route for creating new wallet"""
        if 'wallet' not in request_json or 'count' not in request_json or not isinstance(request_json['count'], int):
            return self.generic_error()

        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Create account
        async with in_transaction() as conn:
            accounts = await wallet.accounts_create(count=request_json['count'], using_db=conn)
        return self.json_response(
            data = {
                'accounts': accounts
            }
        )

    async def account_list(self, request: web.Request, request_json: dict):
        """Route for creating new wallet"""
        if 'wallet' not in request_json:
            return self.generic_error()
        elif 'count' in request_json and isinstance(request_json['acount'], int):
            count = request_json['count']
        else:
            count = 1000

        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        return self.json_response(
            data = {'accounts': [a.address for a in await wallet.accounts.all().limit(count)]}
        )

    async def receive(self, request: web.Request, request_json: dict):
        """RPC receive for account"""
        if 'wallet' not in request_json or 'account' not in request_json or 'block' not in request_json:
            return self.generic_error()
        elif not Validators.is_valid_address(request_json['account']):
            return self.json_response(
                data={'error': 'Invalid address'}
            )
        elif not Validators.is_valid_block_hash(request_json['block']):
            return self.json_response(
                data={'error': 'Invalid block'}
            )

        work = request_json['work'] if 'work' in request_json else None

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Retrieve account on wallet
        account = await wallet.get_account(request_json['account'])
        if account is None:
            return self.json_response(
                data={'error': 'Account not found'}
            )

        # Try to receive block
        wallet = WalletUtil(account, wallet)
        try:
            response = await wallet.receive(request_json['block'], work=work)
        except BlockNotFound:
            return self.json_response(
                data={'error': 'Block not found'}
            )
        except WorkFailed:
            return self.json_response(
                data={'error': 'Failed to generate work'}
            )
        except ProcessFailed:
            return self.json_response(
                data={'error': 'RPC Process failed'}
            )

        if response is None:
            return self.json_response(
                data={'error': 'Unable to receive block'}
            )

        return self.json_response(
            data=response
        )

    async def send(self, request: web.Request, request_json: dict):
        """RPC send for account"""
        if 'wallet' not in request_json or 'source' not in request_json or 'destination' not in request_json or 'amount' not in request_json:
            return self.generic_error()
        elif not Validators.is_valid_address(request_json['source']):
            return self.json_response(
                data={'error': 'Invalid source'}
            )
        elif not Validators.is_valid_address(request_json['destination']):
            return self.json_response(
                data={'error': 'Invalid destination'}
            )

        id = request_json['id'] if 'id' in request_json else None
        work = request_json['work'] if 'work' in request_json else None

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Retrieve account on wallet
        account = await wallet.get_account(request_json['source'])
        if account is None:
            return self.json_response(
                data={'error': 'Account not found'}
            )

        # Try to create and publish send block
        wallet = WalletUtil(account, wallet)
        try:
            resp = await wallet.send(int(request_json['amount']), request_json['destination'], id=id, work=work)
        except AccountNotFound:
            return self.json_response(
                data={'error': 'Account not found'}
            )
        except BlockNotFound:
            return self.json_response(
                data={'error': 'Block not found'}
            )
        except WorkFailed:
            return self.json_response(
                data={'error': 'Failed to generate work'}
            )
        except ProcessFailed:
            return self.json_response(
                data={'error': 'RPC Process failed'}
            )
        except InsufficientBalance:
            return self.json_response(
                data={'error': 'insufficient balance'}
            )

        if resp is None:
            return self.json_response(
                data={'error': 'Unable to create send block'}
            )

        return self.json_response(
            data=resp
        )

    async def account_representative_set(self, request: web.Request, request_json: dict):
        """RPC account_representative_set for account"""
        if 'wallet' not in request_json or 'account' not in request_json or 'representative' not in request_json:
            return self.generic_error()
        elif not Validators.is_valid_address(request_json['account']):
            return self.json_response(
                data={'error': 'Invalid account'}
            )
        elif not Validators.is_valid_address(request_json['representative']):
            return self.json_response(
                data={'error': 'Invalid representative'}
            )

        work = request_json['work'] if 'work' in request_json else None

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Retrieve account on wallet
        account = await wallet.get_account(request_json['account'])
        if account is None:
            return self.json_response(
                data={'error': 'Account not found'}
            )

        # Try to create and publish CHANGE block
        wallet = WalletUtil(account, wallet)
        try:
            resp = await wallet.representative_set(request_json['representative'], work=work)
        except AccountNotFound:
            return self.json_response(
                data={'error': 'Account not found'}
            )
        except WorkFailed:
            return self.json_response(
                data={'error': 'Failed to generate work'}
            )
        except ProcessFailed:
            return self.json_response(
                data={'error': 'RPC Process failed'}
            )

        if resp is None:
            return self.json_response(
                data={'error': 'Unable to create change block'}
            )

        return self.json_response(
            data=resp
        )

    async def password_change(self, request: web.Request, request_json: dict):
        """RPC password_change for account"""
        if 'wallet' not in request_json or 'password' not in request_json:
            return self.generic_error()

        # Retrieve wallet
        wallet = await Wallet.filter(id=request_json['wallet']).first()
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Encrypt
        await wallet.encrypt_wallet(request_json['password'])

        return self.json_response(
            data={'changed': '1'}
        )

    async def password_enter(self, request: web.Request, request_json: dict):
        """RPC password_enter for account"""
        if 'wallet' not in request_json or 'password' not in request_json:
            return self.generic_error()

        # Retrieve wallet
        wallet = await Wallet.filter(id=request_json['wallet']).first()
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
            return self.json_response(
                data={
                    'error': 'wallet not locked'
                }
            )
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked as w:
            wallet = w.wallet

        try:
            await wallet.unlock_wallet(request_json['password'])
        except DecryptionError:
            return self.json_response(
                data={'valid': '0'}
            )

        return self.json_response(
            data={'valid': '1'}
        )

    async def password_valid(self, request: web.Request, request_json: dict):
        """RPC password_valid for account"""
        if 'wallet' not in request_json:
            return self.generic_error()

        # Retrieve wallet
        wallet = await Wallet.filter(id=request_json['wallet']).first()
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
            if not wallet.encrypted:
                return self.json_response(
                    data={
                        'error': 'wallet not locked'
                    }
                )
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={'valid': '0'}
            )

        return self.json_response(
            data={'valid': '1'}
        )

    async def wallet_representative_set(self, request: web.Request, request_json: dict):
        """RPC wallet_representative_set for account"""
        if 'wallet' not in request_json or 'representative' not in request_json or ('update_existing_accounts' in request_json and not isinstance(request_json['update_existing_accounts'], bool)):
            return self.generic_error()
        elif not Validators.is_valid_address(request_json['representative']):
            return self.json_response(
                data={'error': 'Invalid address'}
            )

        update_existing = False
        if 'update_existing_accounts' in request_json:
            update_existing = request_json['update_existing_accounts']

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        wallet.representative = request_json['representative']
        await wallet.save(update_fields=['representative'])

        if update_existing:
            await wallet.bulk_representative_update(request_json['representative'])

        return self.json_response(
            data={'set': '1'}
        )

    async def wallet_add(self, request: web.Request, request_json: dict):
        """RPC wallet_add for account"""
        if 'wallet' not in request_json or 'key' not in request_json:
            return self.generic_error()
        elif not Validators.is_valid_block_hash(request_json['key']):
            return self.json_response(
                data={'error': 'Invalid key'}
            )

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={
                    'error': 'wallet locked'
                }
            )

        # Add account
        try:
            address = await wallet.adhoc_account_create(request_json['key'])
        except AccountAlreadyExists:
            return self.json_response(
                data={
                    'error': 'account already exists'
                }
            )

        return self.json_response(
            data={'account':address}
        )

    async def wallet_lock(self, request: web.Request, request_json: dict):
        """RPC wallet_lock for account"""
        if 'wallet' not in request_json:
            return self.generic_error()

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked as we:
            wallet = we.wallet

        await wallet.lock_wallet()

        return self.json_response(
            data={'locked':'1'}
        )

    async def wallet_locked(self, request: web.Request, request_json: dict):
        """RPC wallet_locked for account"""
        if 'wallet' not in request_json:
            return self.generic_error()

        # Retrieve wallet
        try:
            wallet = await Wallet.get_wallet(request_json['wallet'])
        except WalletNotFound:
            return self.json_response(
                data={
                    'error': 'wallet not found'
                }
            )
        except WalletLocked:
            return self.json_response(
                data={'locked': '1'}
            )

        return self.json_response(
            data={'locked':'0'}
        )

    async def start(self):
        """Start the server"""
        runner = web.AppRunner(self.app, access_log = None if not config.Config.instance().debug else log.server_logger)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()