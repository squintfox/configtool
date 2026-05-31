import subprocess

import configtool_secrets
import pytest
from configtool_secrets.errors import SecretCommandExecutionError
from configtool_secrets.handlers.command import Command
from configtool_secrets.handlers.file import File


class AllowAllPolicy:
    def resolve_run_mode(self, command):
        return command, isinstance(command, str)


def test_package_exports_secrets():
    assert hasattr(configtool_secrets, 'Secrets')
    assert hasattr(configtool_secrets, 'SecretCommandExecutionError')


def test_command_execute_and_unlock(monkeypatch):
    class Result:
        stdout = 'secret\n'

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    handler = Command(['echo', 'secret'])
    assert handler._execute(['echo', 'secret']) == 'secret\n'
    assert handler.unlock({'lib.a': 'x', 'lib.b': 'y'}) == {
        'lib.a': 'secret',
        'lib.b': 'secret',
    }


def test_command_execute_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'bad', stderr='boom')

    monkeypatch.setattr(subprocess, 'run', _raise)
    with pytest.raises(SecretCommandExecutionError, match='boom'):
        Command(['bad'])._execute(['bad'])


def test_command_execute_error_preserves_runtime_error_compatibility(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'bad', stderr='boom')

    monkeypatch.setattr(subprocess, 'run', _raise)
    with pytest.raises(RuntimeError, match='boom'):
        Command(['bad'])._execute(['bad'])


def test_command_handler_blocks_string_shell_commands_by_default(monkeypatch):
    monkeypatch.delenv('CFGT_ALLOW_SHELL_COMMANDS', raising=False)
    with pytest.raises(SecretCommandExecutionError, match='disabled by default'):
        Command('echo secret')._execute('echo secret')


def test_command_handler_accepts_explicit_policy_for_string_commands(monkeypatch):
    class Result:
        stdout = 'secret\n'

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    handler = Command('echo secret', policy=AllowAllPolicy())
    assert handler.unlock({'lib.a': 'x'}) == {'lib.a': 'secret'}


def test_file_read_and_unlock(tmp_path):
    p = tmp_path / 'secret.txt'
    p.write_text('secret\n', encoding='utf-8')
    handler = File(str(p))
    assert handler._read_file(str(p)) == 'secret\n'
    assert handler.unlock({'lib.a': 'x'}) == {'lib.a': 'secret'}


def test_file_read_missing_raises(tmp_path):
    handler = File(str(tmp_path / 'none.txt'))
    with pytest.raises(FileNotFoundError, match='not found'):
        handler._read_file(str(tmp_path / 'none.txt'))
