import json
import logging
import os
import socket
import subprocess
import time
from collections.abc import Mapping
from typing import cast

import requests

logger = logging.getLogger(__name__)

JsonDict = dict[str, object]


class Vaultwarden:
    """Secret handler that retrieves secrets from Vaultwarden via bw CLI."""

    def __init__(
        self,
        vault_url: str,
        username: str,
        password: str,
        folder_name: str = '',
    ):
        """
        Initialize Vaultwarden handler.

        Args:
            vault_url: Full URL to the Bitwarden/Vaultwarden instance
            username: Email or username for authentication
            password: Master password for authentication
            folder_name: Optional folder name to search for items
        """
        self.vault_url = vault_url
        self.username = username
        self.password = password
        self.folder_name = folder_name
        self.folder_id: str | None = None
        self.http = requests.Session()
        self.api_process: subprocess.Popen[str] | None = None
        self.api_url: str | None = None
        self.session_key = ''

    def _bw_env(self) -> dict[str, str]:
        """Build environment variables for bw CLI execution."""
        env = os.environ.copy()
        env['BW_PASSWORD'] = self.password
        return env

    def _run_bw(self, args: list[str], session_key: str = '') -> str:
        """Run a bw CLI command and return stripped stdout."""
        command = ['bw', *args, '--nointeraction']
        if session_key:
            command.extend(['--session', session_key])

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=self._bw_env(),
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(message or f"Bitwarden command failed: {' '.join(command)}")
        return result.stdout.strip()

    def _get_status(self, session_key: str = '') -> JsonDict:
        """Get vault status from bw output, tolerating debug noise."""
        output = self._run_bw(['status'], session_key=session_key)
        # When BITWARDENCLI_DEBUG=true, debug lines are mixed into stdout.
        # Find the last line that parses as JSON.
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith('{'):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        return cast(JsonDict, parsed)
                except json.JSONDecodeError:
                    continue
        return {}

    def _find_free_port(self) -> int:
        """Find an available local TCP port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen(1)
            return sock.getsockname()[1]

    def _request(self, method: str, path: str) -> object | None:
        """Issue a request to bw serve API and normalize wrapped responses."""
        if not self.api_url:
            raise RuntimeError("Bitwarden API server is not running")

        response = self.http.request(
            method=method,
            url=f'{self.api_url}{path}',
            timeout=2,
        )
        response.raise_for_status()

        if not response.content:
            return None

        payload_obj: object = response.json()

        # bw serve wraps responses as { success, data: ... }.
        if isinstance(payload_obj, dict):
            raw_payload = cast(dict[object, object], payload_obj)
            payload: JsonDict = {str(key): value for key, value in raw_payload.items()}
        else:
            return payload_obj

        if 'success' in payload and 'data' in payload:
            data: object = payload.get('data')
            if isinstance(data, dict):
                raw_data = cast(dict[object, object], data)
                data_dict: JsonDict = {str(key): value for key, value in raw_data.items()}
                if 'template' in data_dict:
                    return data_dict.get('template')
                if data_dict.get('object') == 'list' and 'data' in data_dict:
                    return data_dict.get('data')
                return data_dict
            return data

        return payload

    def _start_api_server(self) -> None:
        """Start bw serve API and wait until vault status is unlocked."""
        if self.api_process and self.api_process.poll() is None:
            return

        port = self._find_free_port()
        self.api_url = f'http://127.0.0.1:{port}'
        self.api_process = subprocess.Popen(
            [
                'bw',
                'serve',
                '--hostname',
                '127.0.0.1',
                '--port',
                str(port),
                '--session',
                self.session_key,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.api_process.poll() is not None:
                raise RuntimeError("Bitwarden API server exited before becoming ready")
            try:
                status_obj = self._request('GET', '/status')
                if not isinstance(status_obj, dict):
                    continue
                status = cast(JsonDict, status_obj)
                if status.get('status') == 'unlocked':
                    return
            except requests.RequestException:
                pass
            time.sleep(0.1)

        raise RuntimeError("Timed out waiting for Bitwarden API server to start")

    def close(self) -> None:
        """Close HTTP/session resources and stop bw serve process."""
        self.http.close()

        if not self.api_process:
            return

        if self.api_process.poll() is None:
            self.api_process.terminate()
            try:
                self.api_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.api_process.kill()
                self.api_process.wait(timeout=5)

        self.api_process = None
        self.api_url = None

    def login(self) -> str:
        """
        Authenticate with Bitwarden/Vaultwarden.
        Checks current status and logs in if needed.
        """
        current_status = self._get_status()
        current_server_value = current_status.get('serverUrl', '')
        current_server = str(current_server_value) if current_server_value else ''
        status = str(current_status.get('status', ''))

        # Configure server only if the URL differs from the current configuration.
        # bw config server requires the vault to be logged out first.
        if current_server.rstrip('/') != self.vault_url.rstrip('/'):
            if status != 'unauthenticated':
                self._run_bw(['logout'])
                status = 'unauthenticated'
            self._run_bw(['config', 'server', self.vault_url])

        if status == 'unauthenticated':
            self.session_key = self._run_bw(
                ['login', self.username, self.password, '--raw']
            ).splitlines()[-1]
        elif status == 'locked':
            self.session_key = self._run_bw(
                ['unlock', '--raw', '--passwordenv', 'BW_PASSWORD']
            ).splitlines()[-1]

        if not self.session_key and status == 'unlocked':
            self.session_key = os.environ.get('BW_SESSION', '')

        status = str(self._get_status(session_key=self.session_key).get('status', ''))
        if status != 'unlocked':
            raise RuntimeError(f"Bitwarden login failed: vault status is {status}")

        if not self.session_key:
            raise RuntimeError("Bitwarden login succeeded but no session key was returned")

        self._run_bw(['sync'])
        self._start_api_server()

        logger.info("Login successful. Vault status: %s", status)
        return status

    def unlock(self, secret_config: Mapping[str, str]) -> dict[str, str]:
        """
        Unlock vault and retrieve secrets.

        secret_config (example) - maps app namespace to item name in Bitwarden:
        {
            'namespace_1': 'item_name_1',
            'namespace_2': 'item_name_2',
        }

        Args:
            secret_config: Dictionary mapping namespaces to Bitwarden item names

        Returns:
            Dictionary mapping namespaces to their retrieved passwords
        """
        if not self.session_key:
            raise RuntimeError("Not logged in. Call login() first.")

        if not self.api_url:
            raise RuntimeError("Not logged in. Call login() first.")

        status_response_obj = self._request('GET', '/status')
        if not isinstance(status_response_obj, dict):
            raise RuntimeError('Bitwarden API status response was not an object')
        status_response = cast(JsonDict, status_response_obj)
        status = str(status_response.get('status', ''))
        if status != 'unlocked':
            raise RuntimeError(f"Bitwarden API is not unlocked. Current status: {status}")

        # Get folder information
        if self.folder_name:
            folders_response_obj = self._request('GET', '/list/object/folders')
            folders: list[JsonDict] = []
            if isinstance(folders_response_obj, list):
                for folder in cast(list[object], folders_response_obj):
                    if isinstance(folder, dict):
                        folders.append(cast(JsonDict, folder))
            folder = next((f for f in folders if f.get('name') == self.folder_name), None)
            if not folder:
                raise RuntimeError(f"Bitwarden folder {self.folder_name} was not found")
            folder_id = folder.get('id')
            self.folder_id = str(folder_id) if folder_id else None
        else:
            self.folder_id = None

        # Retrieve all items and filter by folder
        all_items_response_obj = self._request('GET', '/list/object/items')
        all_items: list[JsonDict] = []
        if isinstance(all_items_response_obj, list):
            for item in cast(list[object], all_items_response_obj):
                if isinstance(item, dict):
                    all_items.append(cast(JsonDict, item))
        folder_items = {
            i.get('name'): i
            for i in all_items
            if i.get('folderId') == self.folder_id or self.folder_id is None
            if isinstance(i.get('name'), str)
        }

        # Extract secrets for each requested item
        rtrn: dict[str, str] = {}
        for app_namespace, item_name in secret_config.items():
            if item_name not in folder_items:
                raise RuntimeError(
                    f"Item {item_name} not found in folder {self.folder_name}"
                )
            # vaultwarden items contain both username and pw, if 'username' is in
            # the variable name, return the corresponding username value, otherwise return the
            # password
            item = folder_items[item_name]
            login_obj = item.get('login')
            login: JsonDict = (
                cast(JsonDict, login_obj) if isinstance(login_obj, dict) else {}
            )
            username = str(login.get('username', ''))
            password = str(login.get('password', ''))

            if 'username' in app_namespace:
                rtrn[app_namespace] = username
                continue
            elif not password:
                raise RuntimeError(
                    f"No password found for item {item_name} in namespace {app_namespace}"
                )
            rtrn[app_namespace] = password
        return rtrn
