import json
import subprocess

from configtool.db import CommandDB, FileDB
from configtool.public import DatabaseSource
from configtool_secrets.models import parse_secret_config_block
from configtool_secrets.secrets import SecretHandler, Secrets


def _assert_database_source_contract(source: DatabaseSource) -> None:
    assert isinstance(source.database, dict)


def _assert_secret_handler_contract(handler: SecretHandler) -> None:
    out = handler.unlock({'lib.a': 'x'})
    assert isinstance(out, dict)


def test_database_source_contract_with_filedb(tmp_path):
    db_file = tmp_path / 'db.yml'
    db_file.write_text(
        'app:\n  environments:\n    dev: [root.default]\n  config:\n    root:\n      default:\n        x:\n          value: 1\n',
        encoding='utf-8',
    )
    _assert_database_source_contract(FileDB(str(db_file)))


def test_database_source_contract_with_commanddb(monkeypatch):
    class Result:
        stdout = json.dumps(
            {
                'app': {
                    'environments': {'dev': ['root.default']},
                    'config': {'root': {'default': {'x': {'value': '1'}}}},
                }
            }
        )

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    _assert_database_source_contract(CommandDB(['echo', 'ignored']))


def test_provider_registration_contract_for_custom_provider():
    class CustomProvider:
        def unlock(self, payload):
            return {k: f'custom-{v}' for k, v in payload.items()}

    s = Secrets()
    s.register_provider(
        'custom-contract',
        target_key_resolver=lambda _s, _block: 'custom-target',
        provider_factory=lambda _s, _target: CustomProvider(),
    )

    registration = s._provider_registry['custom-contract']
    provider = registration.provider_factory(s, 'custom-target')
    _assert_secret_handler_contract(provider)


def test_builtin_provider_registration_contracts(monkeypatch):
    class FakeProvider:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        def unlock(self, payload):
            return payload

    monkeypatch.setattr('configtool_secrets.secrets.AzureKeyVault', FakeProvider)
    monkeypatch.setattr('configtool_secrets.secrets.File', FakeProvider)
    monkeypatch.setattr('configtool_secrets.secrets.Command', FakeProvider)

    class FakeVaultwarden(FakeProvider):
        def login(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr('configtool_secrets.secrets.Vaultwarden', FakeVaultwarden)
    monkeypatch.setenv('CFGT_VAULTWARDEN_USERNAME', 'u')
    monkeypatch.setenv('CFGT_VAULTWARDEN_PASSWORD', 'p')

    s = Secrets()

    typed_blocks = {
        'ns.kv': parse_secret_config_block(
            'ns.kv',
            {'secret_type': {'value': 'keyvault'}, 'vault-uri': {'value': 'https://kv'}},
        ),
        'ns.file': parse_secret_config_block(
            'ns.file',
            {'secret_type': {'value': 'file'}, 'file-path': {'value': '/tmp/f'}},
        ),
        'ns.command': parse_secret_config_block(
            'ns.command',
            {'secret_type': {'value': 'command'}, 'command': {'value': ['echo', '1']}},
        ),
        'ns.vw': parse_secret_config_block(
            'ns.vw',
            {'secret_type': {'value': 'vaultwarden'}, 'vault-url': {'value': 'https://vw'}},
        ),
    }

    for namespace, block in typed_blocks.items():
        registration = s._provider_registry[block.secret_type]
        target_key = registration.target_key_resolver(s, block)
        provider = registration.provider_factory(s, target_key)
        _assert_secret_handler_contract(provider)
