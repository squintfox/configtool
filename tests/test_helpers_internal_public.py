import types

import pytest

import configtool
from configtool.helpers import namespace_is_default
from configtool.internal import AppConfig
from configtool.public import (
    EnvMappings,
    Interface,
    Libraries,
    RuntimeFlatMap,
    RuntimeNestedMap,
    Secrets,
)


@pytest.fixture
def sample_database():
    return {
        'app': {
            'environments': {'base': ['lib.default', 'lib.env', 'other.default']},
            'config': {
                'lib': {
                    'default': {
                        'a': {'value': 'A', 'env': 'ENV_A'},
                        'secret': {
                            'value': 'lookup-secret',
                            'secret_namespace': 'secrets.lookup',
                            'env': ['ENV_SECRET_1', 'ENV_SECRET_2'],
                        },
                    },
                    'env': {'b': {'value': 'B'}},
                },
                'other': {
                    'default': {'x': {'value': 'X'}},
                },
                'secrets': {
                    'default': {},
                    'lookup': {
                        'secret_type': {'value': 'file'},
                        'file-path': {'value': '/a'},
                    },
                },
            },
        }
    }


def test_package_exports_interface():
    assert hasattr(configtool, 'Interface')


def test_namespace_is_default_variants():
    assert namespace_is_default('lib') is True
    assert namespace_is_default('lib.default') is True
    assert namespace_is_default('lib.other') is False


def test_appconfig_load_and_overlay(sample_database):
    app = AppConfig('app', sample_database)
    app.load_namespace('lib.default')
    assert app.config['lib']['a']['value'] == 'A'

    app.load_namespace('lib.env')
    assert app.config['lib']['b']['value'] == 'B'

    # First non-default load on a fresh root overlays default first.
    app2 = AppConfig('app', sample_database)
    app2.load_namespace('lib.env')
    assert 'a' in app2.config['lib']
    assert 'b' in app2.config['lib']


def test_appconfig_get_config_block_overlay_default(sample_database):
    app = AppConfig('app', sample_database)
    block = app.get_config_block('lib.env', overlay_default=True)
    assert 'a' in block
    assert 'b' in block


def test_interface_raises_without_input_source():
    with pytest.raises(NotImplementedError):
        Interface('app', 'base', [], local_db_path=None, local_command_path=None)


def test_interface_loads_from_file_db_and_populates(monkeypatch, sample_database):
    class FakeFileDB:
        def __init__(self, _path):
            self.database = sample_database

    monkeypatch.setattr('configtool.public.FileDB', FakeFileDB)

    iface = Interface(
        'app', 'base', additional_namespaces=['lib.env'], local_db_path='db.yml'
    )
    assert iface.libraries['lib']['a'] == 'A'
    assert iface.libraries['lib']['b'] == 'B'
    assert iface.secrets['secrets.lookup']['lib.secret'] == 'lookup-secret'
    assert iface.env['ENV_A'] == 'lib.a'
    assert iface.env_secrets['ENV_SECRET_1'] == 'lib.secret'
    assert iface.get_config_block('lib.env', overlay_default=False) == {'b': {'value': 'B'}}


def test_interface_loads_from_command_db(monkeypatch, sample_database):
    class FakeCommandDB:
        def __init__(self, _command):
            self.database = sample_database

    monkeypatch.setattr('configtool.public.CommandDB', FakeCommandDB)
    iface = Interface(
        'app',
        'base',
        additional_namespaces=[],
        local_command_path='get-db',
    )
    assert iface.libraries['other']['x'] == 'X'


def test_interface_populate_with_library_filter(monkeypatch, sample_database):
    class FakeFileDB:
        def __init__(self, _path):
            self.database = sample_database

    monkeypatch.setattr('configtool.public.FileDB', FakeFileDB)
    iface = Interface('app', 'base', [], local_db_path='db.yml')
    iface.libraries.clear()
    iface.populate(libraries=['other'])
    assert 'other' in iface.libraries
    assert 'lib' not in iface.libraries


def test_interface_load_namespace_passthrough(monkeypatch, sample_database):
    class FakeFileDB:
        def __init__(self, _path):
            self.database = sample_database

    monkeypatch.setattr('configtool.public.FileDB', FakeFileDB)
    iface = Interface('app', 'base', [], local_db_path='db.yml')
    iface.load_namespace('lib.env')
    assert 'lib' in iface.libraries


def test_runtime_nested_map_mapping_and_data_semantics():
    source = {'lib': {'value': {'k': 'v'}}}
    model = RuntimeNestedMap(source)

    assert model.data['lib']['value']['k'] == 'v'
    source['lib']['value']['k'] = 'changed'
    assert model.data['lib']['value']['k'] == 'v'

    model['extra'] = {'x': 1}
    assert model['extra']['x'] == 1
    assert set(iter(model)) == {'lib', 'extra'}
    assert len(model) == 2

    del model['extra']
    assert 'extra' not in model


def test_runtime_flat_map_mapping_and_data_semantics():
    source = {'A': 'lib.a'}
    model = RuntimeFlatMap(source)

    assert model.data['A'] == 'lib.a'
    source['A'] = 'lib.changed'
    assert model.data['A'] == 'lib.a'

    model['B'] = 'lib.b'
    assert model['B'] == 'lib.b'
    assert set(iter(model)) == {'A', 'B'}
    assert len(model) == 2

    del model['B']
    assert 'B' not in model


def test_runtime_model_subclasses_expose_merge_from():
    libraries = Libraries()
    secrets = Secrets()
    env = EnvMappings()

    libraries.merge_from({'lib': {'x': '1'}})
    secrets.merge_from({'sec.ns': {'lib.secret': 'lookup'}})
    env.merge_from({'ENV_X': 'lib.x'})

    assert libraries['lib']['x'] == '1'
    assert secrets['sec.ns']['lib.secret'] == 'lookup'
    assert env['ENV_X'] == 'lib.x'


def test_interface_rejects_invalid_variable_spec_schema(monkeypatch, sample_database):
    class FakeFileDB:
        def __init__(self, _path):
            broken = sample_database.copy()
            broken['app'] = sample_database['app'].copy()
            broken['app']['config'] = sample_database['app']['config'].copy()
            broken['app']['config']['lib'] = sample_database['app']['config']['lib'].copy()
            broken['app']['config']['lib']['default'] = {
                'a': {'value': 'A', 'env': {'bad': 'shape'}}
            }
            self.database = broken

    monkeypatch.setattr('configtool.public.FileDB', FakeFileDB)
    with pytest.raises(ValueError, match='field "env" must be a string'):
        Interface('app', 'base', additional_namespaces=[], local_db_path='db.yml')
