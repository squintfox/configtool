import os

import pytest
from configtool_secrets.constants import (
    HANDLER_TYPE_COMMAND,
    HANDLER_TYPE_FILE,
    HANDLER_TYPE_KEYVAULT,
    HANDLER_TYPE_VAULTWARDEN,
    HANDLERS,
)
from configtool_secrets.models import SecretConfigBlock, parse_secret_config_block
from configtool_secrets.secrets import SecretCacheManager, Secrets


def test_constants_are_wired():
    assert HANDLER_TYPE_KEYVAULT in HANDLERS
    assert HANDLER_TYPE_FILE in HANDLERS
    assert HANDLER_TYPE_COMMAND in HANDLERS
    assert HANDLER_TYPE_VAULTWARDEN in HANDLERS


def test_secrets_unlock_dispatches_all_handlers(monkeypatch):
    class FakeKeyVault:
        def __init__(self, vault_uri, cred_options):
            self.vault_uri = vault_uri
            self.cred_options = cred_options

        def unlock(self, payload):
            return {k: f'kv-{v}' for k, v in payload.items()}

    class FakeFile:
        def __init__(self, file_path):
            self.file_path = file_path

        def unlock(self, payload):
            return {k: f'file-{v}' for k, v in payload.items()}

    class FakeCommand:
        def __init__(self, command):
            self.command = command

        def unlock(self, payload):
            return {k: f'cmd-{v}' for k, v in payload.items()}

    class FakeVaultwarden:
        def __init__(self, vault_url, username, password, folder_name=''):
            self.vault_url = vault_url
            self.username = username
            self.password = password
            self.folder_name = folder_name
            self.closed = False

        def login(self):
            return 'ok'

        def unlock(self, payload):
            return {k: f'vw-{v}' for k, v in payload.items()}

        def close(self):
            self.closed = True

    monkeypatch.setattr('configtool_secrets.secrets.AzureKeyVault', FakeKeyVault)
    monkeypatch.setattr('configtool_secrets.secrets.File', FakeFile)
    monkeypatch.setattr('configtool_secrets.secrets.Command', FakeCommand)
    monkeypatch.setattr('configtool_secrets.secrets.Vaultwarden', FakeVaultwarden)

    monkeypatch.setenv('CFGT_VAULTWARDEN_USERNAME', 'u')
    monkeypatch.setenv('CFGT_VAULTWARDEN_PASSWORD', 'p')

    s = Secrets()
    s.cred_options.append({'secret_type': 'keyvault'})

    secret_config = {
        'ns.kv': {'lib.a': 'akv'},
        'ns.file': {'lib.b': 'afile'},
        'ns.command': {'lib.c': 'acmd'},
        'ns.vw': {'lib.username': 'item1'},
        'ns.empty': {},
    }
    config = {
        'ns.kv': {
            'secret_type': {'value': 'keyvault'},
            'vault-uri': {'value': 'https://kv'},
        },
        'ns.file': {
            'secret_type': {'value': 'file'},
            'file-path': {'value': '/tmp/secret'},
        },
        'ns.command': {'secret_type': {'value': 'command'}, 'command': {'value': 'echo 1'}},
        'ns.vw': {
            'secret_type': {'value': 'vaultwarden'},
            'vault-url': {'value': 'https://vw'},
            'folder-name': {'value': 'f'},
        },
        'ns.empty': {
            'secret_type': {'value': 'file'},
            'file-path': {'value': '/tmp/empty'},
        },
    }

    typed_config = {
        namespace: parse_secret_config_block(namespace, block)
        for namespace, block in config.items()
    }

    out = s.unlock(secret_config, typed_config)
    assert out['lib.a'] == 'kv-akv'
    assert out['lib.b'] == 'file-afile'
    assert out['lib.c'] == 'cmd-acmd'
    assert out['lib.username'] == 'vw-item1'


def test_secrets_unknown_type_raises():
    s = Secrets()
    with pytest.raises(NotImplementedError, match='Unknown secret type'):
        s.unlock(
            {'ns': {'lib.a': 'x'}},
            {'ns': SecretConfigBlock(secret_type='unknown')},
        )


def test_package_exports_secret_config_block_model():
    import configtool_secrets

    assert hasattr(configtool_secrets, 'SecretConfigBlock')


def test_secrets_vaultwarden_missing_env_vars_raises(monkeypatch):
    monkeypatch.delenv('CFGT_VAULTWARDEN_USERNAME', raising=False)
    monkeypatch.delenv('CFGT_VAULTWARDEN_PASSWORD', raising=False)

    s = Secrets()
    typed = {
        'ns': parse_secret_config_block(
            'ns',
            {
                'secret_type': {'value': 'vaultwarden'},
                'vault-url': {'value': 'https://vw'},
            },
        )
    }
    with pytest.raises(RuntimeError, match='credentials not found'):
        s.unlock({'ns': {'lib.a': 'x'}}, typed)


def test_build_cache_key_and_invalid_input():
    s = Secrets()
    assert s._build_cache_key({'a': 1}) == '{"a":1}'

    class Bad:
        pass

    assert s._build_cache_key({'a': Bad()}) is None


def test_get_vaultwarden_reuses_cached_client(monkeypatch):
    created = {'count': 0}

    class FakeVaultwarden:
        def __init__(self, vault_url, username, password, folder_name=''):
            _ = (vault_url, username, password, folder_name)
            created['count'] += 1

        def login(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr('configtool_secrets.secrets.Vaultwarden', FakeVaultwarden)
    s = Secrets()
    s._vaultwarden_clients.clear()
    key = ('https://vw', 'u', 'p', 'f')
    one = s._get_vaultwarden(key)
    two = s._get_vaultwarden(key)
    assert one is two
    assert created['count'] == 1


def test_secrets_do_not_share_caches_by_default():
    left = Secrets()
    right = Secrets()

    left._unlock_cache['k'] = 'v'
    assert right._unlock_cache == {}


def test_secrets_can_share_caches_with_explicit_cache_manager():
    shared = SecretCacheManager()
    left = Secrets(cache_manager=shared)
    right = Secrets(cache_manager=shared)

    left._unlock_cache['k'] = 'v'
    assert right._unlock_cache['k'] == 'v'


def test_close_clears_cached_clients(monkeypatch):
    closed = {'count': 0}

    class FakeVaultwarden:
        def close(self):
            closed['count'] += 1

    s = Secrets()
    s._vaultwarden_clients[('k',)] = FakeVaultwarden()
    s._unlock_cache['x'] = 'y'
    s.close()
    assert closed['count'] == 1
    assert s._vaultwarden_clients == {}
    assert s._unlock_cache == {}


def test_register_provider_extension_hook():
    class CustomProvider:
        def unlock(self, payload):
            return {k: f'custom-{v}' for k, v in payload.items()}

    s = Secrets()
    s.register_provider(
        'custom',
        target_key_resolver=lambda _s, _b: 'target',
        provider_factory=lambda _s, _target: CustomProvider(),
    )
    out = s.unlock(
        {'ns.custom': {'lib.a': 'x'}},
        {'ns.custom': SecretConfigBlock(secret_type='custom')},
    )
    assert out['lib.a'] == 'custom-x'


def test_register_provider_duplicate_requires_override():
    s = Secrets()
    with pytest.raises(NotImplementedError, match='already registered'):
        s.register_provider(
            HANDLER_TYPE_FILE,
            target_key_resolver=lambda _s, _b: 'unused',
            provider_factory=lambda _s, _target: None,
        )


def test_get_config_block_returns_namespace():
    s = Secrets()
    s._config = {'ns': SecretConfigBlock(secret_type='file')}
    assert s._get_config_block('ns').secret_type == 'file'
