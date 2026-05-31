import json
import os
import subprocess
import types

import pytest
import requests

from configtool_secrets.handlers.vaultwarden import Vaultwarden


def test_bw_env_sets_password():
    vw = Vaultwarden('https://v', 'u', 'p', '')
    env = vw._bw_env()
    assert env['BW_PASSWORD'] == 'p'


def test_run_bw_success_and_failure(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')

    class Result:
        def __init__(self, rc=0, out='ok', err=''):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    assert vw._run_bw(['status']) == 'ok'

    monkeypatch.setattr(
        subprocess,
        'run',
        lambda *args, **kwargs: Result(rc=1, out='', err='boom'),
    )
    with pytest.raises(RuntimeError, match='boom'):
        vw._run_bw(['status'])


def test_get_status_parses_last_json_line(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    monkeypatch.setattr(
        vw,
        '_run_bw',
        lambda *args, **kwargs: 'debug\nnot json\n{"status":"unlocked"}',
    )
    assert vw._get_status()['status'] == 'unlocked'


def test_find_free_port_returns_int():
    vw = Vaultwarden('https://v', 'u', 'p', '')
    port = vw._find_free_port()
    assert isinstance(port, int)
    assert port > 0


def test_request_variants(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')

    with pytest.raises(RuntimeError, match='not running'):
        vw._request('GET', '/x')

    vw.api_url = 'http://127.0.0.1:1234'

    class Resp:
        def __init__(self, payload, content=True):
            self._payload = payload
            self.content = b'x' if content else b''

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    payloads = [
        {'success': True, 'data': {'template': {'t': 1}}},
        {'success': True, 'data': {'object': 'list', 'data': [1, 2]}},
        {'success': True, 'data': {'a': 1}},
        {'x': 1},
    ]

    def _request(method, url, timeout):
        _ = (method, url, timeout)
        return Resp(payloads.pop(0))

    monkeypatch.setattr(vw.http, 'request', _request)
    assert vw._request('GET', '/a') == {'t': 1}
    assert vw._request('GET', '/a') == [1, 2]
    assert vw._request('GET', '/a') == {'a': 1}
    assert vw._request('GET', '/a') == {'x': 1}

    monkeypatch.setattr(vw.http, 'request', lambda *args, **kwargs: Resp({}, content=False))
    assert vw._request('GET', '/a') is None


def test_start_api_server_success(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    vw.session_key = 'session'

    class P:
        def __init__(self):
            self._poll = None

        def poll(self):
            return self._poll

    monkeypatch.setattr(vw, '_find_free_port', lambda: 4444)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: P())
    statuses = iter([{}, {'status': 'unlocked'}])
    monkeypatch.setattr(vw, '_request', lambda *args, **kwargs: next(statuses))
    monkeypatch.setattr('time.monotonic', lambda: 0)
    monkeypatch.setattr('time.sleep', lambda _: None)

    vw._start_api_server()
    assert vw.api_url == 'http://127.0.0.1:4444'


def test_start_api_server_exits_early(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    vw.session_key = 'session'

    class P:
        def poll(self):
            return 1

    monkeypatch.setattr(vw, '_find_free_port', lambda: 4444)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: P())
    monkeypatch.setattr('time.monotonic', lambda: 0)

    with pytest.raises(RuntimeError, match='exited before becoming ready'):
        vw._start_api_server()


def test_start_api_server_timeout(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    vw.session_key = 'session'

    class P:
        def poll(self):
            return None

    monkeypatch.setattr(vw, '_find_free_port', lambda: 4444)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: P())

    ticks = iter([0, 5, 11])
    monkeypatch.setattr('time.monotonic', lambda: next(ticks))
    monkeypatch.setattr(vw, '_request', lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException('x')))
    monkeypatch.setattr('time.sleep', lambda _: None)

    with pytest.raises(RuntimeError, match='Timed out'):
        vw._start_api_server()


def test_close_paths(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    closed = {'http': False}
    monkeypatch.setattr(vw.http, 'close', lambda: closed.update({'http': True}))

    vw.close()
    assert closed['http'] is True

    class P:
        def __init__(self):
            self.killed = False
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            if not self.killed:
                raise subprocess.TimeoutExpired('x', timeout)
            return 0

        def kill(self):
            self.killed = True

    p = P()
    vw.api_process = p
    vw.api_url = 'url'
    vw.close()
    assert p.terminated is True
    assert p.killed is True
    assert vw.api_process is None
    assert vw.api_url is None


def test_login_paths(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    called = []

    statuses = iter([
        {'serverUrl': 'https://other', 'status': 'locked'},
        {'status': 'unlocked'},
    ])

    monkeypatch.setattr(vw, '_get_status', lambda session_key='': next(statuses))

    def _run_bw(args, session_key=''):
        called.append((tuple(args), session_key))
        if args[:2] == ['unlock', '--raw']:
            return 'session-from-unlock'
        return 'ok'

    monkeypatch.setattr(vw, '_run_bw', _run_bw)
    monkeypatch.setattr(vw, '_start_api_server', lambda: called.append(('start', '')))

    status = vw.login()
    assert status == 'unlocked'
    assert ('start', '') in called


def test_login_uses_bw_session_for_already_unlocked(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    monkeypatch.setenv('BW_SESSION', 'session-env')
    statuses = iter([
        {'serverUrl': 'https://v', 'status': 'unlocked'},
        {'status': 'unlocked'},
    ])
    monkeypatch.setattr(vw, '_get_status', lambda session_key='': next(statuses))
    monkeypatch.setattr(vw, '_run_bw', lambda *args, **kwargs: 'ok')
    monkeypatch.setattr(vw, '_start_api_server', lambda: None)

    assert vw.login() == 'unlocked'
    assert vw.session_key == 'session-env'


def test_login_failure_paths(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', '')
    statuses = iter([
        {'serverUrl': 'https://v', 'status': 'unauthenticated'},
        {'status': 'locked'},
    ])
    monkeypatch.setattr(vw, '_get_status', lambda session_key='': next(statuses))
    monkeypatch.setattr(vw, '_run_bw', lambda *args, **kwargs: 'session')

    with pytest.raises(RuntimeError, match='login failed'):
        vw.login()

    vw2 = Vaultwarden('https://v', 'u', 'p', '')
    statuses2 = iter([
        {'serverUrl': 'https://v', 'status': 'unauthenticated'},
        {'status': 'unlocked'},
    ])
    monkeypatch.setattr(vw2, '_get_status', lambda session_key='': next(statuses2))
    monkeypatch.setattr(vw2, '_run_bw', lambda *args, **kwargs: '')
    with pytest.raises(IndexError):
        vw2.login()

    vw3 = Vaultwarden('https://v', 'u', 'p', '')
    statuses3 = iter([
        {'serverUrl': 'https://v', 'status': 'unlocked'},
        {'status': 'unlocked'},
    ])
    monkeypatch.setattr(vw3, '_get_status', lambda session_key='': next(statuses3))
    monkeypatch.delenv('BW_SESSION', raising=False)
    monkeypatch.setattr(vw3, '_run_bw', lambda *args, **kwargs: 'ok')
    with pytest.raises(RuntimeError, match='no session key'):
        vw3.login()


def test_unlock_paths(monkeypatch):
    vw = Vaultwarden('https://v', 'u', 'p', 'folder')

    with pytest.raises(RuntimeError, match='Not logged in'):
        vw.unlock({'lib.a': 'x'})

    vw_no_api = Vaultwarden('https://v', 'u', 'p', '')
    vw_no_api.session_key = 's'
    with pytest.raises(RuntimeError, match='Not logged in'):
        vw_no_api.unlock({'lib.a': 'x'})

    vw.session_key = 's'
    vw.api_url = 'http://api'
    monkeypatch.setattr(vw, '_request', lambda *args, **kwargs: {'status': 'locked'})
    with pytest.raises(RuntimeError, match='not unlocked'):
        vw.unlock({'lib.a': 'x'})

    responses = iter([
        {'status': 'unlocked'},
        [{'name': 'folder', 'id': 'f1'}],
        [
            {'name': 'item1', 'folderId': 'f1', 'login': {'username': 'u1', 'password': 'p1'}},
            {'name': 'item2', 'folderId': 'f1', 'login': {'username': 'u2', 'password': 'p2'}},
        ],
    ])
    monkeypatch.setattr(vw, '_request', lambda *args, **kwargs: next(responses))
    out = vw.unlock({'lib.username': 'item1', 'lib.password': 'item2'})
    assert out == {'lib.username': 'u1', 'lib.password': 'p2'}

    vw2 = Vaultwarden('https://v', 'u', 'p', 'missing-folder')
    vw2.session_key = 's'
    vw2.api_url = 'http://api'
    responses2 = iter([
        {'status': 'unlocked'},
        [{'name': 'other', 'id': 'f2'}],
    ])
    monkeypatch.setattr(vw2, '_request', lambda *args, **kwargs: next(responses2))
    with pytest.raises(RuntimeError, match='folder missing-folder was not found'):
        vw2.unlock({'lib.password': 'item'})

    vw3 = Vaultwarden('https://v', 'u', 'p', '')
    vw3.session_key = 's'
    vw3.api_url = 'http://api'
    responses3 = iter([
        {'status': 'unlocked'},
        [
            {'name': 'item1', 'folderId': None, 'login': {'username': 'u1', 'password': ''}},
        ],
    ])
    monkeypatch.setattr(vw3, '_request', lambda *args, **kwargs: next(responses3))
    with pytest.raises(RuntimeError, match='No password found'):
        vw3.unlock({'lib.password': 'item1'})

    vw4 = Vaultwarden('https://v', 'u', 'p', '')
    vw4.session_key = 's'
    vw4.api_url = 'http://api'
    responses4 = iter([
        {'status': 'unlocked'},
        [],
    ])
    monkeypatch.setattr(vw4, '_request', lambda *args, **kwargs: next(responses4))
    with pytest.raises(RuntimeError, match='Item x not found'):
        vw4.unlock({'lib.password': 'x'})