import os
import types

import configtool_client
import pytest
from configtool_client.config import Config, LocalConfigFile
from configtool_secrets.models import parse_secret_config_block


class FakeInterface:
    def __init__(self, app, environment, additional_namespaces, **kwargs):
        self.init_args = (app, environment, additional_namespaces, kwargs)
        self.libraries = {'lib': {'x': '1'}}
        self.secrets = {'sec.ns': {'lib.secret': 'lookup'}}
        self.env = {'ENV_X': 'lib.x'}
        self.env_secrets = {'ENV_SECRET': 'lib.secret'}
        self._app = types.SimpleNamespace(
            _config_blocks={
                'sec': {
                    'ns': {
                        'secret_type': {'value': 'file'},
                        'file-path': {'value': '/tmp/s'},
                    }
                }
            }
        )

    def get_config_block(self, namespace, overlay_default=False):
        if namespace == 'sec.ns':
            return {'secret_type': {'value': 'file'}, 'file-path': {'value': '/tmp/s'}}
        raise KeyError(namespace)

    def load_namespace(self, namespace, **kwargs):
        root = namespace.split('.', 1)[0]
        self.libraries.setdefault(root, {})['dynamic'] = '2'

    def populate(self, libraries=None):
        if libraries and 'lib' in libraries:
            self.libraries['lib']['pop'] = 'ok'


class FakeSecrets:
    def __init__(self):
        self.cred_options = []

    def unlock(self, secrets, blocks):
        _ = blocks
        unlocked = {}
        for namespace in secrets:
            for lib_var in secrets[namespace]:
                unlocked[lib_var] = f"resolved-{lib_var}"
        return unlocked


class CapturingSecrets(FakeSecrets):
    captured_blocks = None

    def unlock(self, secrets, blocks):
        type(self).captured_blocks = blocks
        return super().unlock(secrets, blocks)


class InterpolatingSecretInterface(FakeInterface):
    def __init__(self, app, environment, additional_namespaces, **kwargs):
        super().__init__(app, environment, additional_namespaces, **kwargs)
        self.libraries = {
            'lib': {
                'dns_domain': 'stuffthatsfine.com',
                'x': '1',
            }
        }
        self.env = {'HPI_DNS_DOMAIN': 'lib.dns_domain'}

    def get_config_block(self, namespace, overlay_default=False):
        if namespace == 'sec.ns':
            return {
                'secret_type': {'value': 'vaultwarden'},
                'vault-url': {'value': 'https://vault.${HPI_DNS_DOMAIN}:444'},
            }
        raise KeyError(namespace)


class BaseMergeSecretInterface(FakeInterface):
    def __init__(self, app, environment, additional_namespaces, **kwargs):
        super().__init__(app, environment, additional_namespaces, **kwargs)
        self.libraries = {'shared': {'dns_domain': 'stuffthatsfine.com'}}
        self.secrets = {}
        self.env = {'HPI_DNS_DOMAIN': 'shared.dns_domain'}
        self.env_secrets = {}
        self._app = types.SimpleNamespace(
            _config_blocks={
                'homepi_secrets': {
                    'vault': {
                        'secret_type': {'value': 'vaultwarden'},
                        'vault-url': {'value': 'https://vault.${HPI_DNS_DOMAIN}:444'},
                    }
                }
            }
        )

    def get_config_block(self, namespace, overlay_default=False):
        if namespace == 'homepi_secrets.vault':
            return {
                'secret_type': {'value': 'vaultwarden'},
                'vault-url': {'value': 'https://vault.${HPI_DNS_DOMAIN}:444'},
            }
        raise KeyError(namespace)


class ChildMergeSecretInterface(FakeInterface):
    def __init__(self, app, environment, additional_namespaces, **kwargs):
        super().__init__(app, environment, additional_namespaces, **kwargs)
        self.libraries = {'code': {'x': '1'}}
        self.secrets = {'homepi_secrets.vault': {'code.secret': 'lookup'}}
        self.env = {}
        self.env_secrets = {}
        self._app = types.SimpleNamespace(_config_blocks={'code': {'default': {}}})

    def get_config_block(self, namespace, overlay_default=False):
        raise KeyError(namespace)


def _write_local_config(tmp_path, additional='  - lib.extra\n'):
    cfg = tmp_path / 'configtool.yml'
    cfg.write_text(
        'app: app\n' 'environment: env\n' 'additional_namespaces:\n' f'{additional}',
        encoding='utf-8',
    )
    return cfg


def test_package_exports_config():
    assert hasattr(configtool_client, 'Config')


def test_local_config_file_reads_values(tmp_path):
    cfg = _write_local_config(tmp_path)
    local = LocalConfigFile(str(cfg))
    assert local.app == 'app'
    assert local.environment == 'env'
    assert local.additional_namespaces == ['lib.extra']


def test_local_config_file_default_additional_namespaces(tmp_path):
    cfg = tmp_path / 'configtool.yml'
    cfg.write_text('app: app\nenvironment: env\n', encoding='utf-8')
    local = LocalConfigFile(str(cfg))
    assert local.additional_namespaces == []


def test_config_requires_db_or_command_path(tmp_path):
    cfg = _write_local_config(tmp_path)
    with pytest.raises(NotImplementedError):
        Config(str(cfg))


def test_config_raises_when_configtool_missing(tmp_path, monkeypatch):
    cfg = _write_local_config(tmp_path)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'configtool':
            raise ModuleNotFoundError('missing')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    with pytest.raises(ModuleNotFoundError, match='Unable to find configtool'):
        Config(str(cfg), local_db_path='db.yml')


def test_config_raises_when_configtool_missing_for_command_path(tmp_path, monkeypatch):
    cfg = _write_local_config(tmp_path)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'configtool':
            raise ModuleNotFoundError('missing')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    with pytest.raises(ModuleNotFoundError, match='Unable to find configtool'):
        Config(str(cfg), local_command_path='db-command')


def test_config_init_and_accessors_with_db(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    fake_module = types.SimpleNamespace(Interface=FakeInterface)
    monkeypatch.setitem(__import__('sys').modules, 'configtool', fake_module)

    config = Config(str(cfg), local_db_path='db.yml')
    assert config.libraries['lib']['x'] == '1'
    assert config.secrets['sec.ns']['lib.secret'] == 'lookup'
    assert config.env['ENV_X'] == 'lib.x'
    assert config.env_secrets['ENV_SECRET'] == 'lib.secret'


def test_config_init_with_command(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    fake_module = types.SimpleNamespace(Interface=FakeInterface)
    monkeypatch.setitem(__import__('sys').modules, 'configtool', fake_module)
    config = Config(str(cfg), local_command_path='db-command')
    assert config.get_library_hash('lib')


def test_config_update_getters_and_hash(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    old_hash = config.get_library_hash('lib')
    config.update({'lib.x': '2'})
    assert config.get_value('lib', 'x') == '2'
    assert config.get_library('lib')['x'] == '2'
    assert config.get_library_hash('lib') != old_hash


def test_config_merge(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    left = Config(str(cfg), local_db_path='db.yml')
    right = Config(str(cfg), local_db_path='db.yml')
    right.update({'lib.x': '77'})
    right.set_secret_lookup('other.ns', 'lib.other', 'lookup2')
    right.set_env_mapping('ENV_NEW', 'lib.x')
    right.set_env_mapping('ENV_SECRET2', 'lib.secret', secret=True)
    right._merge_config_blocks({'root': {'default': {'v': {'value': '1'}}}})
    right.set_library_value('newlib', 'n', '1')
    right.set_secret_lookup('new.ns', 'newlib.secret', 'lookup3')

    left.merge(right)
    assert left.libraries['lib']['x'] == '77'
    assert 'other.ns' in left.secrets
    assert 'ENV_NEW' in left.env
    assert 'ENV_SECRET2' in left.env_secrets
    assert left.libraries['newlib']['n'] == '1'
    assert 'new.ns' in left.secrets


def test_secret_config_blocks_caches_and_skips_missing(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')
    config.set_secret_lookup('missing.ns', 'lib.z', 'lookup')

    blocks = config.secret_config_blocks
    assert 'sec.ns' in blocks
    assert 'missing.ns' not in blocks

    config._secret_config_blocks = {
        'cached.ns': parse_secret_config_block(
            'cached.ns',
            {
                'secret_type': {'value': 'file'},
                'file-path': {'value': '/tmp/cached-secret'},
            },
        )
    }
    blocks2 = config.secret_config_blocks
    assert 'cached.ns' in blocks2


def test_unlock_secrets_and_add_credentials(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    config.add_secrets_cred({'secret_type': 'keyvault'})
    assert config._secrets_obj is not None
    assert config._secrets_obj.cred_options == [{'secret_type': 'keyvault'}]

    config.unlock_secrets()
    assert config.get_value('lib', 'secret').startswith('resolved-')


def test_unlock_secrets_missing_namespace_raises(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')
    config._secrets_mut.clear()
    config._secrets_mut.update({'bad.ns': {'lib.secret': 'x'}})

    with pytest.raises(KeyError, match='Missing config blocks'):
        config.unlock_secrets()


def test_unlock_secrets_no_selected_libraries_is_noop(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')
    config.unlock_secrets(libraries=['nonexistent'])
    assert 'secret' not in config.libraries['lib']


def test_unlock_secrets_with_library_filter_hits_selected(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')
    config.unlock_secrets(libraries=['lib'])
    assert config.libraries['lib']['secret'].startswith('resolved-')


def test_unlock_secrets_uses_cached_secret_blocks(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')
    config._secret_config_blocks = {
        'sec.ns': parse_secret_config_block(
            'sec.ns',
            {
                'secret_type': {'value': 'file'},
                'file-path': {'value': '/tmp/s'},
            },
        )
    }
    config.unlock_secrets()
    assert config.libraries['lib']['secret'].startswith('resolved-')


def test_load_namespace_updates_and_optionally_unlocks(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    config.load_namespace('lib.extra', unlock=False)
    assert config.libraries['lib']['pop'] == 'ok'

    config.load_namespace('lib.extra', unlock=True)
    assert config.libraries['lib']['secret'].startswith('resolved-')


def test_init_secrets_missing_module_raises(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'configtool_secrets':
            raise ModuleNotFoundError('missing')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    with pytest.raises(ModuleNotFoundError, match='Unable to find configtool-secrets'):
        config._init_secrets()


def test_unlock_and_add_credentials_runtime_error_paths(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    monkeypatch.setattr(config, '_init_secrets', lambda: None)
    with pytest.raises(RuntimeError, match='not initialized'):
        config.unlock_secrets()
    with pytest.raises(RuntimeError, match='not initialized'):
        config.add_secrets_cred({'x': 1})


def test_deploy_env_and_env_file(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    config.unlock_secrets()
    config.set_library_value('lib', 'amp', "a&b'c")
    config.set_env_mapping('ENV_AMP', 'lib.amp')
    config.deploy_env(enable_secrets=True)
    assert os.environ['ENV_X'] == '1'
    assert os.environ['ENV_SECRET'].startswith('resolved-')

    env_file = tmp_path / '.env'
    config.deploy_env_file(str(env_file), enable_secrets=True)
    content = env_file.read_text(encoding='utf-8')
    assert 'ENV_X=1' in content
    assert 'ENV_SECRET=' in content
    assert "ENV_AMP='a&b\\'c'" in content


def test_deploy_env_and_file_with_library_filters(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=FakeSecrets),
    )
    config = Config(str(cfg), local_db_path='db.yml')
    config.unlock_secrets()

    os.environ.pop('ENV_X', None)
    os.environ.pop('ENV_SECRET', None)
    config.deploy_env(enable_secrets=False, libraries=['other'])
    assert 'ENV_X' not in os.environ
    assert 'ENV_SECRET' not in os.environ

    config.deploy_env(enable_secrets=True, libraries=['lib'])
    assert os.environ['ENV_X'] == '1'
    assert os.environ['ENV_SECRET'].startswith('resolved-')

    env_file = tmp_path / '.filtered.env'
    config.deploy_env_file(str(env_file), enable_secrets=False, libraries=['other'])
    assert env_file.read_text(encoding='utf-8') == ''

    config.deploy_env_file(str(env_file), enable_secrets=True, libraries=['lib'])
    text = env_file.read_text(encoding='utf-8')
    assert 'ENV_X=1' in text
    assert 'ENV_SECRET=' in text


def test_deploy_env_file_applies_dotenv_interpolation(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    config.set_library_value('lib', 'dns_domain', 'stuffthatsfine.com')
    config.set_library_value('lib', 'vault_url', 'https://vault.${HPI_DNS_DOMAIN}:444')
    config.set_env_mapping('HPI_DNS_DOMAIN', 'lib.dns_domain')
    config.set_env_mapping('HPI_VAULT_URL', 'lib.vault_url')

    env_file = tmp_path / '.expanded.env'
    config.deploy_env_file(str(env_file), enable_secrets=False)

    text = env_file.read_text(encoding='utf-8')
    assert 'HPI_DNS_DOMAIN=' in text
    assert 'stuffthatsfine.com' in text
    assert 'HPI_VAULT_URL=' in text
    assert 'vault.stuffthatsfine.com:444' in text


def test_deploy_env_matches_env_file_dotenv_interpolation(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    config.set_library_value('lib', 'dns_domain', 'stuffthatsfine.com')
    config.set_library_value('lib', 'vault_url', 'https://vault.${HPI_DNS_DOMAIN}:444')
    config.set_env_mapping('HPI_DNS_DOMAIN', 'lib.dns_domain')
    config.set_env_mapping('HPI_VAULT_URL', 'lib.vault_url')

    os.environ.pop('HPI_DNS_DOMAIN', None)
    os.environ.pop('HPI_VAULT_URL', None)

    config.deploy_env(enable_secrets=False)
    assert os.environ['HPI_DNS_DOMAIN'] == 'stuffthatsfine.com'
    assert os.environ['HPI_VAULT_URL'] == 'https://vault.stuffthatsfine.com:444'

    env_file = tmp_path / '.parity.env'
    config.deploy_env_file(str(env_file), enable_secrets=False)
    text = env_file.read_text(encoding='utf-8')
    assert 'HPI_DNS_DOMAIN=' in text
    assert 'stuffthatsfine.com' in text
    assert 'HPI_VAULT_URL=' in text
    assert 'https://vault.stuffthatsfine.com:444' in text


def test_runtime_values_apply_dotenv_interpolation(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    config.set_library_value('lib', 'dns_domain', 'stuffthatsfine.com')
    config.set_library_value('lib', 'vault_url', 'https://vault.${HPI_DNS_DOMAIN}:444')
    config.set_env_mapping('HPI_DNS_DOMAIN', 'lib.dns_domain')

    assert config.get_value('lib', 'vault_url') == 'https://vault.stuffthatsfine.com:444'
    assert config.get_library('lib')['vault_url'] == 'https://vault.stuffthatsfine.com:444'
    assert config.libraries['lib']['vault_url'] == 'https://vault.stuffthatsfine.com:444'


def test_unlock_secrets_resolves_dotenv_in_secret_config_blocks(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=InterpolatingSecretInterface),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=CapturingSecrets),
    )
    CapturingSecrets.captured_blocks = None

    config = Config(str(cfg), local_db_path='db.yml')
    config.unlock_secrets()

    assert CapturingSecrets.captured_blocks is not None
    block = CapturingSecrets.captured_blocks['sec.ns']
    assert block.vault_url == 'https://vault.stuffthatsfine.com:444'


def test_unlock_secrets_resolves_dotenv_for_blocks_cached_during_merge(
    monkeypatch, tmp_path
):
    cfg = _write_local_config(tmp_path)

    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=BaseMergeSecretInterface),
    )
    base = Config(str(cfg), local_db_path='db.yml')

    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=ChildMergeSecretInterface),
    )
    target = Config(str(cfg), local_db_path='db.yml')

    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool_secrets',
        types.SimpleNamespace(Secrets=CapturingSecrets),
    )
    CapturingSecrets.captured_blocks = None

    target.merge(base)
    target.unlock_secrets()

    assert CapturingSecrets.captured_blocks is not None
    block = CapturingSecrets.captured_blocks['homepi_secrets.vault']
    assert block.vault_url == 'https://vault.stuffthatsfine.com:444'


def test_private_helpers(monkeypatch, tmp_path):
    cfg = _write_local_config(tmp_path)
    monkeypatch.setitem(
        __import__('sys').modules,
        'configtool',
        types.SimpleNamespace(Interface=FakeInterface),
    )
    config = Config(str(cfg), local_db_path='db.yml')

    assert Config._resolve_secret_config_block('sec.ns', config) is not None
    assert Config._resolve_secret_config_block('nope', config) is None

    with pytest.raises(KeyError):
        config._get_config_block('missing.ns')

    config._merged_config_blocks = {'sec': {}}
    with pytest.raises(KeyError):
        config._get_config_block('sec.unknown')

    config._merge_config_blocks({'sec': {'extra': {'k': {'value': '1'}}}})
    assert config._get_config_block('sec.extra') == {'k': {'value': '1'}}

    all_blocks = config._get_all_config_blocks()
    assert 'sec' in all_blocks

    config._interface._app = None
    all_blocks_none = config._get_all_config_blocks()
    assert isinstance(all_blocks_none, dict)

    config._merge_config_blocks({'sec': {'extra2': {'k2': {'value': '2'}}}})
    assert config._merged_config_blocks['sec']['extra2']['k2']['value'] == '2'

    old_hash = config.get_library_hash('lib')
    config.set_library_value('lib', 'x', '99')
    assert config.get_library_hash('lib') != old_hash


def test_merge_nested_runtime_map_fallback_deepcopy():
    destination = {}
    source = {'ns': {'k': []}}

    Config._merge_nested_runtime_map(destination, source)
    source['ns']['k'].append('changed')

    assert destination['ns']['k'] == []


def test_merge_nested_runtime_map_prefers_merge_from():
    class MergeAwareNested(dict):
        def __init__(self):
            super().__init__()
            self.called = False

        def merge_from(self, source):
            self.called = True
            for namespace, values in source.items():
                self[namespace] = dict(values)

    destination = MergeAwareNested()
    source = {'ns': {'k': 'v'}}

    Config._merge_nested_runtime_map(destination, source)

    assert destination.called is True
    assert destination['ns']['k'] == 'v'


def test_merge_flat_runtime_map_prefers_merge_from_and_fallback():
    class MergeAwareFlat(dict):
        def __init__(self):
            super().__init__()
            self.called = False

        def merge_from(self, source):
            self.called = True
            self.update(dict(source))

    merge_aware = MergeAwareFlat()
    Config._merge_flat_runtime_map(merge_aware, {'ENV_A': 'lib.a'})
    assert merge_aware.called is True
    assert merge_aware['ENV_A'] == 'lib.a'

    plain = {}
    Config._merge_flat_runtime_map(plain, {'ENV_B': 'lib.b'})
    assert plain['ENV_B'] == 'lib.b'
