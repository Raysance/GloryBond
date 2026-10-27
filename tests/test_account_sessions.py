"""Credential integrity and login lifecycle tests; no QQ/game traffic."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import yaml

from login_console import store, providers
from login_console.manager import Manager, Limited, PREFIX


class MemoryRedis:
    def __init__(self):
        self.values = {}
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = str(value).encode()
        return True
    def get(self, key):
        return self.values.get(key)
    def ttl(self, key):
        return 30
    def eval(self, script, count, key, token, *rest):
        if self.values.get(key) == token.encode():
            del self.values[key]
        return 1
    def close(self):
        pass


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / '.env'
        self.env.write_text("OTHER='preserve'\nHOK_WZRY_TOKEN='old'\n")
        self.config = self.root / 'config.yaml'
        self.config.write_text(yaml.safe_dump({'Redis': {'REDIS_HOST': 'localhost', 'REDIS_PORT': 6379, 'REDIS_DB': 0}, 'QQBot': {'bot_qid': '12345', 'super_qid': '99999'}}))
        self.redis = MemoryRedis()
        with patch('login_console.manager.redis.Redis', return_value=self.redis):
            self.manager = Manager(self.root, self.env, self.config, self.root / 'data')
        self.addCleanup(self.manager.close)
        self.client = Mock()
        self.client.start.return_value = b'\x89PNG\r\n\x1a\nmock'
        self.client.poll.return_value = ('authenticated', {'HOK_WZRY_TOKEN': 'new'})
        self.provider = patch.object(self.manager, 'provider', return_value=self.client)
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def test_json_roundtrip_preserves_backslashes_quotes_and_other_settings(self):
        value = json.dumps({'raw': 'quoted\' " \\n literal', 'nested': json.dumps({'quote': '"'})}, ensure_ascii=False)
        store.save_secrets(self.env, {'HOK_CAMP_SESSION_JSON': value}, self.root)
        values = store.secrets(self.env)
        self.assertEqual(values['HOK_CAMP_SESSION_JSON'], value)
        self.assertEqual(json.loads(values['HOK_CAMP_SESSION_JSON']), json.loads(value))
        self.assertEqual(values['OTHER'], 'preserve')
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)

    def test_refuses_unmanaged_keys_and_multiline_values(self):
        before = self.env.read_bytes()
        for updates in ({'OTHER': 'changed'}, {'HOK_WZRY_TOKEN': 'secret\nNEW=1'}):
            with self.assertRaises(ValueError):
                store.save_secrets(self.env, updates, self.root)
        self.assertEqual(self.env.read_bytes(), before)

    def test_atomic_compare_and_swap_prevents_overwrite(self):
        before = self.env.read_bytes()
        with self.assertRaises(ValueError):
            store.save_secrets(self.env, {'HOK_WZRY_TOKEN': 'new'}, self.root, expected={'HOK_WZRY_TOKEN': 'stale'})
        self.assertEqual(self.env.read_bytes(), before)

    def test_qr_reuses_session_and_secret_stays_unchanged_until_verified(self):
        before = self.env.read_bytes()
        first = self.manager.start('camp')
        second = self.manager.start('camp')
        self.assertEqual(first, second)
        self.assertEqual(self.client.start.call_count, 1)
        self.assertEqual(self.env.read_bytes(), before)
        reply = self.manager.poll('camp', first['challenge_id'])
        self.assertEqual(reply['state'], 'authenticated')
        self.assertEqual(store.secrets(self.env)['HOK_WZRY_TOKEN'], 'new')
        self.assertNotIn('camp', self.manager.active)
        self.assertIsNone(self.redis.get(PREFIX+'camp:lease'))
        self.assertFalse((self.manager.directory / first['challenge_id']).exists())

    def test_unverified_login_does_not_replace_credentials(self):
        qr = self.manager.start('camp')
        self.client.poll.side_effect = RuntimeError()
        before = self.env.read_bytes()
        with self.assertRaises(RuntimeError):
            self.manager.poll('camp', qr['challenge_id'])
        self.assertEqual(self.env.read_bytes(), before)
        self.assertNotIn('camp', self.manager.active)

    def test_foreign_challenge_and_repeated_polls_make_no_extra_request(self):
        qr = self.manager.start('camp')
        self.client.poll.return_value = ('waiting_scan', None)
        self.assertEqual(self.manager.poll('camp', 'bad')['state'], 'expired')
        self.client.poll.assert_not_called()
        self.manager.poll('camp', qr['challenge_id'])
        with self.assertRaises(Limited):
            self.manager.poll('camp', qr['challenge_id'])
        self.assertEqual(self.client.poll.call_count, 1)

    def test_expired_qr_and_lost_lease_cannot_save(self):
        qr = self.manager.start('camp')
        self.redis.values.pop(PREFIX+'camp:lease')
        self.assertEqual(self.manager.poll('camp', qr['challenge_id'])['state'], 'expired')
        self.client.poll.assert_not_called()

    def test_concurrent_credentials_change_is_preserved(self):
        qr = self.manager.start('camp')
        store.save_secrets(self.env, {'HOK_WZRY_TOKEN': 'other-login'}, self.root)
        with self.assertRaises(ValueError):
            self.manager.poll('camp', qr['challenge_id'])
        self.assertEqual(store.secrets(self.env)['HOK_WZRY_TOKEN'], 'other-login')

    def test_network_error_is_unknown_and_never_exposed(self):
        self.client.check.side_effect = RuntimeError('SECRET-TOKEN private response')
        result = self.manager.check('camp')
        self.assertIsNone(result['authenticated'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_cached_status_expires_and_admin_can_switch_a_healthy_account(self):
        self.manager.record('camp', providers.status(True, 'valid'))
        self.assertEqual(self.manager.start('camp')['state'], 'waiting_scan')
        self.client.start.assert_called_once()
        with patch('login_console.manager.time.time', return_value=time.time()+301):
            self.assertIsNone(self.manager.cached('camp')['authenticated'])

    def test_second_process_cannot_create_another_qr(self):
        self.redis.set(PREFIX+'camp:lease', 'other', ex=300)
        with self.assertRaises(Limited):
            self.manager.start('camp')
        self.client.start.assert_not_called()

    def test_napcat_only_accepts_loopback_and_uses_latest_scanned_qq(self):
        config = {'QQBot': {'bot_qid': '12345'}, 'AccountSessions': {'napcat': {'base_url': 'https://external.example'}}}
        with self.assertRaises(providers.NotConfigured):
            providers.NapCat(config, {'HOK_NAPCAT_WEBUI_TOKEN': 'dummy'}, self.root)
        config['AccountSessions']['napcat']['base_url'] = 'http://127.0.0.1:6099'
        client = providers.NapCat(config, {'HOK_NAPCAT_WEBUI_TOKEN': 'dummy'}, self.root)
        self.addCleanup(client.close)
        client.credential = 'authorized'
        client.call = Mock(side_effect=[{'isLogin': True}, {'uin': '45678'}])
        self.assertIs(client.check()["authenticated"], True)
        self.assertEqual(client.account["uin"], "45678")
        client.call = Mock(return_value={'isLogin': False, 'qrcodeurl': 'PRIVATE-QR'})
        result = client.check()
        self.assertIs(result['authenticated'], False)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_official_switch_validates_new_game_account_before_saving(self):
        client = providers.Official.__new__(providers.Official)
        client.client = Mock()
        client.client.poll_qq_login.return_value.code = 0
        client.client.msdk_session.openid = 'new-account'
        client.session = Mock(openid='old-account')
        client.verify = Mock()
        client.routing = {'server_id': 2033, 'tree_index': 0}
        client.session_path = self.root/'new-session.json'
        store.write_json(client.session_path, {'kind':'msdk_session','response':{'openid':'new-account'}})
        state, updates = client.poll()
        self.assertEqual(state, 'authenticated')
        client.verify.assert_called_once_with(new_account=True)
        client.client.msdk_session.save.assert_called_once_with(client.session_path)
        self.assertEqual(json.loads(updates['HOK_PLAYER_CLIENT_ACCOUNT_JSON'])['server_id'], 2033)

    def test_camp_public_projection_whitelists_fields(self):
        state = {'token': 'token', 'encode_res': 'encoderes', 'userId': '123', 'openId': 'open',
                 'profile': {'version_name': 'v', 'version_code': 1, 'sdk': 32, 'os_version': '12', 'hardware': 'x'},
                 'login_response': {'private': 'SECRET'}, 'userKey': 'SECRET'}
        projected = store.camp_overrides(state)
        self.assertNotIn('SECRET', json.dumps(projected))
        self.assertEqual(projected['userid'], '123')


class PinnedTlsTests(unittest.TestCase):
    def test_local_https_requires_exact_certificate_before_credentials_are_sent(self):
        import datetime
        import hashlib
        import http.server
        import ssl
        import threading
        import requests
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'local-test')])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
                    .not_valid_after(now+datetime.timedelta(hours=1)).sign(key, hashes.SHA256()))
            cert_file, key_file = root/'cert.pem', root/'key.pem'
            cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
            received = []
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_POST(self):
                    received.append(self.headers.get('Authorization'))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'ok')
                def log_message(self, *args):
                    pass
            server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_file, key_file)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'https://127.0.0.1:{server.server_port}'
                with requests.Session() as session:
                    session.trust_env = False
                    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
                    session.mount(url+'/', providers.PinnedLoopbackAdapter(fingerprint))
                    self.assertEqual(session.post(url, headers={'Authorization': 'Bearer TEST'}, timeout=3).status_code, 200)
                self.assertEqual(received, ['Bearer TEST'])
                with requests.Session() as session:
                    session.trust_env = False
                    session.mount(url+'/', providers.PinnedLoopbackAdapter('0'*64))
                    with self.assertRaises(requests.exceptions.SSLError):
                        session.post(url, headers={'Authorization': 'Bearer NEVER-SEND'}, timeout=3)
                self.assertEqual(received, ['Bearer TEST'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


class CredentialHotReloadTests(unittest.TestCase):
    def test_camp_credentials_replace_stale_process_values(self):
        config = {'wzry': {'token': 'old', 'encoderes': 'old', 'userid': '123', 'pubkey': 'keep'}}
        state = {'token': 'new', 'encode_res': 'new-encode', 'userId': '123', 'openId': 'same-account',
                 'profile': {'version_name': 'new-version', 'version_code': 5, 'sdk': 32, 'os_version': '12', 'hardware': 'x'},
                 'role': {'gameOpenId': 'game-account', 'gameRoleId': 1, 'gameAreaId': 1, 'gameServerId': 2}}
        store.apply_credentials(config, {'HOK_CAMP_SESSION_JSON': json.dumps(state)})
        self.assertEqual(config['wzry']['token'], 'new')
        self.assertEqual(config['wzry']['encoderes'], 'new-encode')
        self.assertEqual(config['wzry']['client_headers']['cclientversionname'], 'new-version')
        self.assertEqual(config['wzry']['pubkey'], 'keep')

    def test_expired_official_session_does_not_attempt_a_game_login(self):
        client = providers.Official.__new__(providers.Official)
        client.session = Mock(raw={'token_expire_time': time.time()-1})
        client.client = Mock()
        client.verify = Mock()
        self.assertIs(client.check()['authenticated'], False)
        client.client.use_msdk_session.assert_not_called()
        client.verify.assert_not_called()


class AccountSwitchTests(unittest.TestCase):
    def state(self, role=None):
        return {'token':'new-token','encode_res':'new-encode','userId':'222222','openId':'new-camp-openid',
                'log_id':'new-log-id','userKey':'private-key',
                'profile':{'version_name':'v','version_code':2,'sdk':32,'os_version':'12','hardware':'x'},
                'role':role or {'gameOpenId':'new-game-openid','gameRoleId':99,'gameAreaId':2,
                                'gameServerId':2001,'gameUserSex':0,'kohDimGender':1}}

    def test_save_updates_all_identity_fields_preserving_permissions_and_players(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);env=root/'.env';config=root/'config.yaml'
            env.write_text("OTHER='preserve'\nHOK_WZRY_TOKEN='old'\n")
            config.write_text('# keep comment\nwzry:\n  userid: old\n  pubkey: keep\nQQBot:\n  bot_qid: "12345"\n  super_qid: "99999"\nPlayerClient:\n  server_id: 1\n  tree_index: 1\n  players:\n    friend: {uid: 1}\n')
            state=self.state()
            updates={'HOK_CAMP_SESSION_JSON':json.dumps(state),'HOK_WZRY_TOKEN':state['token'],
                     'HOK_WZRY_ENCODERES':state['encode_res'],
                     'HOK_NAPCAT_ACCOUNT_JSON':json.dumps({'uin':'67890'}),
                     'HOK_PLAYER_CLIENT_ACCOUNT_JSON':json.dumps({'server_id':7,'tree_index':0})}
            store.save_secrets(env,updates,root/'private',config_file=config)
            saved=yaml.safe_load(config.read_text())
            for key,value in {'userid':'222222','openid':'new-camp-openid','gameopenid':'new-game-openid',
                              'gameroleid':'99','roleid':'99','gameserverid':2001,'gameareaid':2}.items():
                self.assertEqual(saved['wzry'][key],value)
            self.assertEqual(saved['QQBot'],{'bot_qid':'67890','super_qid':'99999'})
            self.assertEqual(saved['PlayerClient']['players'],{'friend':{'uid':1}})
            self.assertEqual(saved['PlayerClient']['server_id'],7)
            self.assertIn('# keep comment',config.read_text())
            self.assertNotIn('new-token',config.read_text())
            self.assertEqual(store.secrets(env)['OTHER'],'preserve')

    def test_projection_failure_rolls_back_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);env=root/'.env';config=root/'config.yaml'
            env.write_text("HOK_WZRY_TOKEN='old'\n");config.write_text('wzry: {}\n')
            original=store.atomic_write
            def fail_config(path, value):
                if Path(path)==config:
                    raise OSError('disk failure')
                original(path,value)
            with patch.object(store,'atomic_write',side_effect=fail_config):
                with self.assertRaises(OSError):
                    store.save_secrets(env,{'HOK_WZRY_TOKEN':'new'},root/'private',config_file=config)
            self.assertEqual(store.secrets(env)['HOK_WZRY_TOKEN'],'old')

    def test_no_role_clears_every_old_role_field(self):
        config={'wzry':{'gameopenid':'old','gameroleid':'old','roleid':'old'}}
        state=self.state({'gameOpenId':'','gameRoleId':0,'gameAreaId':0,'gameServerId':0,'gameUserSex':0,'kohDimGender':1})
        store.apply_credentials(config,{'HOK_CAMP_SESSION_JSON':json.dumps(state)})
        self.assertEqual(config['wzry']['gameopenid'],'')
        self.assertEqual(config['wzry']['gameroleid'],'0')
        self.assertEqual(config['wzry']['roleid'],'0')

    def test_camp_switch_fetches_new_roles_instead_of_reusing_old_role(self):
        client=providers.Camp.__new__(providers.Camp);client.client=Mock();client.pending_roles=None
        client.client.poll_login.return_value={'state':'authenticated'}
        client.client._post.return_value=({'data':[{'openid':'new','roleId':99,'areaId':2,'serverId':2001,'isMainRole':1}]},0)
        client._complete=Mock(return_value=('authenticated',{'fresh':'credentials'}))
        self.assertEqual(client.poll()[0],'authenticated')
        self.assertEqual(client._complete.call_args.args[0]['gameOpenId'],'new')
        client.client._post.assert_called_once_with('/game/roles',{'gameId':20001})

    def test_ambiguous_roles_require_admin_selection_without_replaying_qq_exchange(self):
        client=providers.Camp.__new__(providers.Camp);client.client=Mock();client.pending_roles=None
        client.client.poll_login.return_value={'state':'authenticated'}
        rows=[{'openid':'one','roleId':1,'areaId':1,'serverId':2},
              {'openid':'two','roleId':3,'areaId':2,'serverId':4}]
        client.client._post.return_value=({'data':{'roles':rows}},0)
        client._complete=Mock(return_value=('authenticated',{}))
        self.assertEqual(client.poll(),('select_role',None))
        self.assertEqual(client.poll(),('select_role',None))
        self.assertEqual(len(client.role_choices),2)
        self.assertNotIn('openid',json.dumps(client.role_choices))
        client.select_role(1)
        self.assertEqual(client._complete.call_args.args[0]['gameOpenId'],'two')
        client.client.poll_login.assert_called_once()
        with self.assertRaises(ValueError):
            client.select_role(10)


class RoleSelectionLifecycleTests(unittest.TestCase):
    setUp = LoginTests.setUp
    def test_role_selection_retains_lease_and_commits_only_after_choice(self):
        qr=self.manager.start('camp')
        self.client.poll.return_value=('select_role',None)
        self.client.role_choices=[{'choice':0,'label':'角色 A'},{'choice':1,'label':'角色 B'}]
        before=self.env.read_bytes()
        result=self.manager.poll('camp',qr['challenge_id'])
        self.assertEqual(result['state'],'select_role')
        self.assertEqual(self.env.read_bytes(),before)
        self.assertIn('camp',self.manager.active)
        self.assertTrue(self.redis.get(PREFIX+'camp:lease'))
        self.redis.values.pop(PREFIX+'camp:poll')
        self.client.select_role.return_value=('authenticated',{'HOK_WZRY_TOKEN':'selected'})
        result=self.manager.dispatch({'provider':'camp','action':'select_role','challenge_id':qr['challenge_id'],'role_choice':1})
        self.assertEqual(result['state'],'authenticated')
        self.assertEqual(store.secrets(self.env)['HOK_WZRY_TOKEN'],'selected')
        self.client.select_role.assert_called_once_with(1)

    def test_online_napcat_sync_saves_current_identity_and_releases_lease(self):
        self.client.start.return_value=None
        self.client.poll.return_value=('authenticated',{'HOK_NAPCAT_ACCOUNT_JSON':json.dumps({'uin':'67890'}),
                                                       'NAPCAT_QUICK_ACCOUNT':'67890'})
        result=self.manager.start('napcat')
        self.assertEqual(result['state'],'authenticated')
        config=yaml.safe_load(self.config.read_text())
        self.assertEqual(config['QQBot'],{'bot_qid':'67890','super_qid':'99999'})
        self.assertEqual(store.secrets(self.env)['NAPCAT_QUICK_ACCOUNT'],'67890')
        self.assertIsNone(self.redis.get(PREFIX+'napcat:lease'))
        self.assertNotIn('napcat',self.manager.active)


class NapCatAccountPersistenceTests(unittest.TestCase):
    def test_successful_scan_updates_restart_account_from_verified_identity(self):
        client=providers.NapCat.__new__(providers.NapCat)
        client.check=Mock(return_value={'authenticated':True})
        client.account={'uin':'67890'}
        client.previous_qq='67890'
        client.onebot_config=None
        client.call=Mock()
        state,updates=client.poll()
        self.assertEqual(state,'authenticated')
        self.assertEqual(updates['NAPCAT_QUICK_ACCOUNT'],'67890')
        self.assertEqual(json.loads(updates['HOK_NAPCAT_ACCOUNT_JSON'])['uin'],'67890')
        client.call.assert_called_once_with('QQLogin/SetQuickLoginQQ',{'uin':'67890'})

    def test_online_sync_does_not_request_qr_or_log_out(self):
        client=providers.NapCat.__new__(providers.NapCat)
        client.check=Mock(return_value={'authenticated':True})
        client.call=Mock()
        self.assertIsNone(client.start(None))
        client.call.assert_not_called()

    def test_changed_qq_keeps_existing_bot_transport_and_saves_private_template(self):
        client=providers.NapCat.__new__(providers.NapCat)
        client.check=Mock(return_value={'authenticated':True})
        client.account={'uin':'67890'}
        client.previous_qq='12345'
        client.onebot_config={'network':{'websocketClients':[{'enable':True,'url':'ws://127.0.0.1/bot','token':'PRIVATE'}]}}
        client.call=Mock()
        state,updates=client.poll()
        self.assertEqual(state,'authenticated')
        self.assertEqual(json.loads(updates['HOK_NAPCAT_ONEBOT_JSON']),client.onebot_config)
        self.assertEqual(client.call.call_args_list[0].args[0],'OB11Config/SetConfig')
        self.assertEqual(client.call.call_args_list[1].args[0],'QQLogin/SetQuickLoginQQ')

    def test_missing_bot_transport_does_not_claim_complete_account_switch(self):
        client=providers.NapCat.__new__(providers.NapCat)
        client.check=Mock(return_value={'authenticated':True})
        client.account={'uin':'67890'};client.previous_qq='12345';client.onebot_config=None;client.call=Mock()
        with self.assertRaises(providers.NotConfigured):
            client.poll()
        client.call.assert_not_called()
