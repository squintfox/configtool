import json
import subprocess

import pytest

from configtool.command_policy import CommandExecutionPolicy
from configtool.db import CommandDB, FileDB
from configtool.errors import CommandExecutionError, InvalidCommandOutputError


def test_filedb_loads_yaml(tmp_path):
    db_file = tmp_path / 'db.yml'
    db_file.write_text('app:\n  environments: {}\n  config: {}\n', encoding='utf-8')

    db = FileDB(str(db_file))
    assert db.database['app']['config'] == {}


def test_filedb_missing_file_raises_import_error(tmp_path):
    with pytest.raises(ImportError):
        FileDB(str(tmp_path / 'missing.yml'))


def test_commanddb_loads_json(monkeypatch):
    class Result:
        stdout = json.dumps(
            {
                'app': {
                    'environments': {'dev': ['root.default']},
                    'config': {'root': {'default': {'x': {'value': '1'}}}},
                }
            }
        )

    monkeypatch.setattr(
        subprocess,
        'run',
        lambda *args, **kwargs: Result(),
    )

    db = CommandDB(['echo', '{"ok": true}'])
    assert db.database['app']['environments']['dev'] == ['root.default']


def test_commanddb_raises_command_execution_error_on_command_failure(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'bad', stderr='boom')

    monkeypatch.setattr(subprocess, 'run', _raise)

    with pytest.raises(CommandExecutionError, match='boom'):
        CommandDB(['bad'])


def test_commanddb_preserves_runtime_error_compatibility(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'bad', stderr='boom')

    monkeypatch.setattr(subprocess, 'run', _raise)

    with pytest.raises(RuntimeError, match='boom'):
        CommandDB(['bad'])


def test_commanddb_raises_value_error_on_invalid_json(monkeypatch):
    class Result:
        stdout = 'not-json'

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())

    with pytest.raises(ValueError, match='not valid JSON'):
        CommandDB(['echo', 'not-json'])


def test_commanddb_blocks_string_shell_commands_by_default(monkeypatch):
    monkeypatch.delenv('CFGT_ALLOW_SHELL_COMMANDS', raising=False)
    with pytest.raises(CommandExecutionError, match='disabled by default'):
        CommandDB('echo {"ok": true}')


def test_commanddb_accepts_explicit_policy_for_string_commands(monkeypatch):
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
    db = CommandDB(
        'echo {"app": {"environments": {}, "config": {}}}',
        policy=CommandExecutionPolicy(allow_shell_strings=True),
    )
    assert 'app' in db.database


def test_commanddb_rejects_invalid_database_shape(monkeypatch):
    class Result:
        stdout = json.dumps({'app': {'environments': []}})

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    with pytest.raises(InvalidCommandOutputError, match='must include mapping field'):
        CommandDB(['echo', '{"app": {"environments": []}}'])


def test_commanddb_rejects_invalid_variable_spec_shape(monkeypatch):
    class Result:
        stdout = json.dumps(
            {
                'app': {
                    'environments': {'dev': ['root.default']},
                    'config': {
                        'root': {
                            'default': {
                                'x': {'value': '1', 'env': 123},
                            }
                        }
                    },
                }
            }
        )

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    with pytest.raises(InvalidCommandOutputError, match='field "env" must be a string'):
        CommandDB(['echo', 'ignored'])
