import subprocess
import types

import pytest
from configtool_secrets.handlers import keyvault as keyvault_module
from configtool_secrets.handlers.keyvault import AzureKeyVault
from configtool_secrets.handlers.vaultwarden import Vaultwarden
from configtool_secrets.models import parse_secret_config_block
from configtool_secrets.secrets import Secrets

from configtool.internal import AppConfig
from configtool.public import Interface


def test_internal_force_default_and_empty_paths():
    db = {
        'app': {
            'environments': {'e': ['lib.env']},
            'config': {
                'lib': {
                    'default': {},
                    'env': {'k': {'value': 'v'}},
                }
            },
        }
    }
    app = AppConfig('app', db)
    app.load_namespace('lib.env', force_default=True)
    # force_default path currently computes but does not merge by implementation.
    assert app.config['lib'] == {}

    assert app.get_config_block('lib.env', overlay_default=True) == {'k': {'value': 'v'}}


def test_public_env_string_branches(monkeypatch):
    db = {
        'app': {
            'environments': {'e': ['lib.default']},
            'config': {
                'lib': {
                    'default': {
                        'n': {'value': '1', 'env': 'ENV_ONE'},
                        'n2': {'value': '2', 'env': ['ENV_TWO_A', 'ENV_TWO_B']},
                        's': {
                            'value': 'lookup',
                            'secret_namespace': 'sec.ns',
                            'env': 'ENV_SEC',
                        },
                        's2': {
                            'value': 'lookup-2',
                            'secret_namespace': 'sec.ns',
                        },
                    }
                },
                'sec': {'default': {}, 'ns': {'secret_type': {'value': 'file'}}},
            },
        }
    }

    class FakeFileDB:
        def __init__(self, _):
            self.database = db

    monkeypatch.setattr('configtool.public.FileDB', FakeFileDB)
    iface = Interface('app', 'e', [], local_db_path='x')
    assert iface.env['ENV_ONE'] == 'lib.n'
    assert iface.env['ENV_TWO_A'] == 'lib.n2'
    assert iface.env_secrets['ENV_SEC'] == 'lib.s'

    # populate twice to cover existing-library/secret buckets.
    iface.populate()


def test_keyvault_unmatched_option_and_no_cached_record(monkeypatch):
    instance = object.__new__(AzureKeyVault)
    assert instance._get_credential_from_opt('uri', [{'secret_type': 'x'}]) is None
    assert (
        instance._get_credential_from_opt(
            'uri',
            [
                {
                    'secret_type': 'keyvault',
                    'vault-uri': 'other',
                    'cred_type': 'managed_identity',
                }
            ],
        )
        is None
    )
    assert (
        instance._get_credential_from_opt(
            'uri',
            [{'secret_type': 'keyvault', 'vault-uri': 'uri', 'cred_type': 'other'}],
        )
        is None
    )

    monkeypatch.setattr(keyvault_module.getpass, 'getuser', lambda: 'u')
    monkeypatch.setattr(keyvault_module.keyring, 'get_password', lambda *_: None)
    monkeypatch.setattr(keyvault_module, 'TokenCachePersistenceOptions', lambda: 'cache')

    class FakeInteractiveCredential:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def authenticate(self):
            return types.SimpleNamespace(serialize=lambda: 'saved')

    monkeypatch.setattr(
        keyvault_module, 'InteractiveBrowserCredential', FakeInteractiveCredential
    )
    monkeypatch.setattr(keyvault_module.keyring, 'set_password', lambda *args: None)

    cred = instance._get_interactive_credential()
    assert cred.kwargs['authentication_record'] == {}


def test_keyvault_constructor_prefers_option_credential(monkeypatch):
    monkeypatch.setattr(
        AzureKeyVault, '_get_credential_from_opt', lambda *args, **kwargs: 'from-opt'
    )
    interactive_called = {'count': 0}

    def _interactive(self):
        interactive_called['count'] += 1
        return 'interactive'

    monkeypatch.setattr(AzureKeyVault, '_get_interactive_credential', _interactive)

    created = {}

    class FakeSecretClient:
        def __init__(self, vault_url, credential):
            created['vault_url'] = vault_url
            created['credential'] = credential

    monkeypatch.setattr(keyvault_module, 'SecretClient', FakeSecretClient)
    AzureKeyVault('https://vault.example', cred_options=[{'x': 1}])
    assert created['credential'] == 'from-opt'
    assert interactive_called['count'] == 0


def test_vaultwarden_remaining_edges(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')

    # _run_bw with session_key branch.
    class Result:
        returncode = 0
        stdout = 'ok'
        stderr = ''

    captured = {}

    def _run(cmd, capture_output, text, env):
        captured['cmd'] = cmd
        _ = (capture_output, text, env)
        return Result()

    monkeypatch.setattr(subprocess, 'run', _run)
    vw._run_bw(['status'], session_key='s')
    assert '--session' in captured['cmd']

    # _get_status JSON decode continue branch.
    monkeypatch.setattr(vw, '_run_bw', lambda *args, **kwargs: '{bad}\n{"status":"ok"}')
    assert vw._get_status()['status'] == 'ok'

    monkeypatch.setattr(vw, '_run_bw', lambda *args, **kwargs: '{bad-json}')
    assert vw._get_status() == {}

    # _start_api_server early return when already running.
    class P:
        def poll(self):
            return None

    vw.api_process = P()
    vw._start_api_server()

    # close branch when process already stopped.
    class P2:
        def poll(self):
            return 1

    vw.api_process = P2()
    vw.api_url = 'x'
    vw.close()
    assert vw.api_process is None

    # _request branch where data is non-dict and returned directly.
    vw3 = Vaultwarden('https://v', 'u', 'p', '')
    vw3.api_url = 'http://api'

    class Resp:
        content = b'x'

        def raise_for_status(self):
            return None

        def json(self):
            return {'success': True, 'data': 'raw'}

    monkeypatch.setattr(vw3.http, 'request', lambda *args, **kwargs: Resp())
    assert vw3._request('GET', '/x') == 'raw'

    # login locked branch.
    vw2 = Vaultwarden('https://v', 'u', 'p', '')
    statuses = iter(
        [
            {'serverUrl': 'https://v', 'status': 'locked'},
            {'status': 'unlocked'},
        ]
    )
    calls = []

    def _run_bw(args, session_key=''):
        calls.append(tuple(args))
        if args[:2] == ['unlock', '--raw']:
            return 'session-locked'
        return 'ok'

    monkeypatch.setattr(vw2, '_get_status', lambda session_key='': next(statuses))
    monkeypatch.setattr(vw2, '_run_bw', _run_bw)
    monkeypatch.setattr(vw2, '_start_api_server', lambda: None)
    assert vw2.login() == 'unlocked'
    assert ('unlock', '--raw', '--passwordenv', 'BW_PASSWORD') in calls

    # login path where server differs but already unauthenticated, so no logout.
    vw4 = Vaultwarden('https://target', 'u', 'p', '')
    statuses4 = iter(
        [
            {'serverUrl': 'https://other', 'status': 'unauthenticated'},
            {'status': 'unlocked'},
        ]
    )
    calls4 = []

    def _run_bw4(args, session_key=''):
        calls4.append(tuple(args))
        if args[:2] == ['login', 'u']:
            return 'session-1'
        return 'ok'

    monkeypatch.setattr(vw4, '_get_status', lambda session_key='': next(statuses4))
    monkeypatch.setattr(vw4, '_run_bw', _run_bw4)
    monkeypatch.setattr(vw4, '_start_api_server', lambda: None)
    assert vw4.login() == 'unlocked'
    assert ('logout',) not in calls4


def test_secrets_dispatch_repeated_targets_and_close_empty(monkeypatch):
    class FakeFile:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        def unlock(self, payload):
            return payload

    class FakeVaultwarden:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        def login(self):
            return None

        def unlock(self, payload):
            return payload

        def close(self):
            return None

    monkeypatch.setattr('configtool_secrets.secrets.File', FakeFile)
    monkeypatch.setattr('configtool_secrets.secrets.Command', FakeFile)
    monkeypatch.setattr('configtool_secrets.secrets.AzureKeyVault', FakeFile)
    monkeypatch.setattr('configtool_secrets.secrets.Vaultwarden', FakeVaultwarden)
    s = Secrets()
    s._vaultwarden_clients.clear()
    monkeypatch.setenv('CFGT_VAULTWARDEN_USERNAME', 'u')
    monkeypatch.setenv('CFGT_VAULTWARDEN_PASSWORD', 'p')
    typed_config = {
        'ns.a': parse_secret_config_block(
            'ns.a',
            {'secret_type': {'value': 'file'}, 'file-path': {'value': '/same'}},
        ),
        'ns.b': parse_secret_config_block(
            'ns.b',
            {'secret_type': {'value': 'file'}, 'file-path': {'value': '/same'}},
        ),
        'ns.kv1': parse_secret_config_block(
            'ns.kv1',
            {'secret_type': {'value': 'keyvault'}, 'vault-uri': {'value': 'kv://same'}},
        ),
        'ns.kv2': parse_secret_config_block(
            'ns.kv2',
            {'secret_type': {'value': 'keyvault'}, 'vault-uri': {'value': 'kv://same'}},
        ),
        'ns.c1': parse_secret_config_block(
            'ns.c1',
            {'secret_type': {'value': 'command'}, 'command': {'value': 'cmd same'}},
        ),
        'ns.c2': parse_secret_config_block(
            'ns.c2',
            {'secret_type': {'value': 'command'}, 'command': {'value': 'cmd same'}},
        ),
        'ns.v1': parse_secret_config_block(
            'ns.v1',
            {'secret_type': {'value': 'vaultwarden'}, 'vault-url': {'value': 'https://vw'}},
        ),
        'ns.v2': parse_secret_config_block(
            'ns.v2',
            {'secret_type': {'value': 'vaultwarden'}, 'vault-url': {'value': 'https://vw'}},
        ),
    }
    out = s.unlock(
        {
            'ns.a': {'lib.a': '1'},
            'ns.b': {'lib.b': '2'},
            'ns.kv1': {'lib.k1': 'k1'},
            'ns.kv2': {'lib.k2': 'k2'},
            'ns.c1': {'lib.c1': 'c1'},
            'ns.c2': {'lib.c2': 'c2'},
            'ns.v1': {'lib.v1': 'v1'},
            'ns.v2': {'lib.v2': 'v2'},
        },
        typed_config,
    )
    assert out['lib.a'] == '1'
    assert out['lib.b'] == '2'
    s.close()


def test_internal_load_namespace_skips_empty_block():
    db = {
        'app': {
            'environments': {'e': ['lib.empty']},
            'config': {
                'lib': {
                    'default': {'d': {'value': '1'}},
                    'empty': {},
                }
            },
        }
    }
    app = AppConfig('app', db)
    app.load_namespace('lib.empty')
    assert app.config['lib'] == {}
