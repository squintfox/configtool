import types

import pytest

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from configtool_secrets.constants import HANDLER_TYPE_KEYVAULT
from configtool_secrets.handlers import keyvault as keyvault_module
from configtool_secrets.handlers.keyvault import AzureKeyVault


def test_get_credential_from_options_and_managed_identity(monkeypatch):
    monkeypatch.setattr(
        keyvault_module,
        'ManagedIdentityCredential',
        lambda client_id=None, additionally_allowed_tenants=None: {
            'client_id': client_id,
            'tenants': additionally_allowed_tenants,
        },
    )
    instance = object.__new__(AzureKeyVault)
    cred = instance._get_credential_from_opt(
        'uri',
        [
            {
                'secret_type': HANDLER_TYPE_KEYVAULT,
                'vault-uri': 'uri',
                'cred_type': 'managed_identity',
                'identity': 'abc',
            }
        ],
    )
    assert cred['client_id'] == 'abc'

    cred_default = instance._get_credential_from_opt(
        'uri',
        [
            {
                'secret_type': HANDLER_TYPE_KEYVAULT,
                'vault-uri': 'uri',
                'cred_type': 'managed_identity',
            }
        ],
    )
    assert cred_default['client_id'] is None


def test_get_interactive_credential_valid_cached_record(monkeypatch):
    monkeypatch.setattr(keyvault_module.getpass, 'getuser', lambda: 'u')
    monkeypatch.setattr(keyvault_module.keyring, 'get_password', lambda *_: 'serialized')
    monkeypatch.setattr(
        keyvault_module.AuthenticationRecord,
        'deserialize',
        lambda r: {'record': r},
    )
    monkeypatch.setattr(keyvault_module, 'TokenCachePersistenceOptions', lambda: 'cache')

    class FakeInteractiveCredential:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def authenticate(self):
            return types.SimpleNamespace(serialize=lambda: 'saved')

    monkeypatch.setattr(
        keyvault_module,
        'InteractiveBrowserCredential',
        FakeInteractiveCredential,
    )
    saved = {}
    monkeypatch.setattr(
        keyvault_module.keyring,
        'set_password',
        lambda service, user, value: saved.update({(service, user): value}),
    )

    instance = object.__new__(AzureKeyVault)
    cred = instance._get_interactive_credential()
    assert isinstance(cred, FakeInteractiveCredential)
    assert saved[(HANDLER_TYPE_KEYVAULT, 'u')] == 'saved'


def test_get_interactive_credential_invalid_cache_falls_back(monkeypatch):
    monkeypatch.setattr(keyvault_module.getpass, 'getuser', lambda: 'u')
    monkeypatch.setattr(keyvault_module.keyring, 'get_password', lambda *_: 'bad')

    def _raise(_):
        raise Exception('bad cache')

    monkeypatch.setattr(keyvault_module.AuthenticationRecord, 'deserialize', _raise)
    monkeypatch.setattr(keyvault_module, 'TokenCachePersistenceOptions', lambda: 'cache')

    class FakeInteractiveCredential:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def authenticate(self):
            return types.SimpleNamespace(serialize=lambda: 'saved')

    monkeypatch.setattr(keyvault_module, 'InteractiveBrowserCredential', FakeInteractiveCredential)
    monkeypatch.setattr(keyvault_module.keyring, 'set_password', lambda *args: None)

    instance = object.__new__(AzureKeyVault)
    cred = instance._get_interactive_credential()
    assert isinstance(cred, FakeInteractiveCredential)
    assert cred.kwargs['authentication_record'] == {}


def test_constructor_uses_interactive_when_no_option(monkeypatch):
    monkeypatch.setattr(AzureKeyVault, '_get_credential_from_opt', lambda *args, **kwargs: None)
    monkeypatch.setattr(AzureKeyVault, '_get_interactive_credential', lambda self: 'interactive')

    created = {}

    class FakeSecretClient:
        def __init__(self, vault_url, credential):
            created['vault_url'] = vault_url
            created['credential'] = credential

    monkeypatch.setattr(keyvault_module, 'SecretClient', FakeSecretClient)

    AzureKeyVault('https://vault.example', cred_options=[])
    assert created['credential'] == 'interactive'


def test_unlock_success_and_errors(monkeypatch):
    instance = object.__new__(AzureKeyVault)

    class FakeSecretClient:
        def __init__(self):
            self.mode = 'ok'

        def get_secret(self, name):
            if self.mode == 'missing':
                raise ResourceNotFoundError('missing')
            if self.mode == 'http':
                raise HttpResponseError('http')
            return types.SimpleNamespace(value=f'value-{name}')

    client = FakeSecretClient()
    instance._secret_client = client

    assert instance.unlock({'lib.a': 's1'}) == {'lib.a': 'value-s1'}

    client.mode = 'missing'
    with pytest.raises(ResourceNotFoundError, match='not found'):
        instance.unlock({'lib.a': 's1'})

    client.mode = 'http'
    with pytest.raises(HttpResponseError, match='Unknown Key Vault error'):
        instance.unlock({'lib.a': 's1'})