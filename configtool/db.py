import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import yaml

from .command_policy import CommandExecutionPolicy
from .errors import CommandExecutionError, DatabaseNotFoundError, InvalidCommandOutputError


@dataclass(frozen=True)
class AppDatabaseModel:
    """Normalized representation of one app block from the config database."""

    environments: dict[str, list[str]]
    config: dict[str, dict[str, dict[str, dict[str, object]]]]

    @classmethod
    def from_mapping(cls, app_name: str, data: object) -> 'AppDatabaseModel':
        """Validate and normalize a single app payload from an untyped mapping."""

        if not isinstance(data, Mapping):
            raise InvalidCommandOutputError(
                f'Command output app block for "{app_name}" must be a mapping.'
            )

        data_map = cast(Mapping[str, object], data)
        environments_obj = data_map.get('environments')
        config_obj = data_map.get('config')

        if not isinstance(environments_obj, Mapping):
            raise InvalidCommandOutputError(
                f'Command output app "{app_name}" must include mapping field "environments".'
            )
        if not isinstance(config_obj, Mapping):
            raise InvalidCommandOutputError(
                f'Command output app "{app_name}" must include mapping field "config".'
            )

        environments_map = cast(Mapping[str, object], environments_obj)
        config_map = cast(Mapping[str, object], config_obj)

        normalized_environments: dict[str, list[str]] = {}
        for environment, namespaces in environments_map.items():
            if not isinstance(namespaces, list):
                raise InvalidCommandOutputError(
                    f'Command output app "{app_name}" environment "{environment}" '
                    'must map to a list of namespace strings.'
                )

            namespaces_list = cast(list[object], namespaces)
            if not all(isinstance(namespace, str) for namespace in namespaces_list):
                raise InvalidCommandOutputError(
                    f'Command output app "{app_name}" environment "{environment}" '
                    'must map to a list of namespace strings.'
                )
            normalized_environments[environment] = cast(list[str], namespaces_list)

        normalized_config: dict[str, dict[str, dict[str, dict[str, object]]]] = {}
        for root, namespace_blocks in config_map.items():
            if not isinstance(namespace_blocks, Mapping):
                raise InvalidCommandOutputError(
                    f'Command output app "{app_name}" config entries must be nested mappings.'
                )

            namespace_blocks_map = cast(Mapping[str, object], namespace_blocks)
            normalized_config[root] = {}
            for namespace, block in namespace_blocks_map.items():
                if not isinstance(block, Mapping):
                    raise InvalidCommandOutputError(
                        f'Command output app "{app_name}" config namespace blocks '
                        'must be mappings keyed by strings.'
                    )

                block_map = cast(Mapping[str, object], block)
                validated_block: dict[str, dict[str, object]] = {}
                for variable, variable_spec in block_map.items():
                    validated_spec = VariableSpecModel.from_mapping(
                        app_name=app_name,
                        root=root,
                        namespace=namespace,
                        variable=variable,
                        payload=variable_spec,
                    )
                    validated_block[variable] = validated_spec.to_mapping()

                normalized_config[root][namespace] = validated_block

        return cls(environments=normalized_environments, config=normalized_config)


@dataclass(frozen=True)
class VariableSpecModel:
    """Normalized variable specification used in namespace config blocks."""

    value: object
    secret_namespace: str | None = None
    env: str | list[str] | None = None

    @classmethod
    def from_mapping(
        cls,
        *,
        app_name: str,
        root: str,
        namespace: str,
        variable: str,
        payload: object,
    ) -> 'VariableSpecModel':
        """Validate and normalize one variable specification mapping."""

        location = (
            f'app "{app_name}" root "{root}" namespace "{namespace}" '
            f'variable "{variable}"'
        )
        if not isinstance(payload, Mapping):
            raise InvalidCommandOutputError(
                f'Command output {location} must map to a variable specification object.'
            )

        payload_map = cast(Mapping[str, object], payload)
        if 'value' not in payload_map:
            raise InvalidCommandOutputError(
                f'Command output {location} must include required field "value".'
            )

        secret_namespace = payload_map.get('secret_namespace')
        if secret_namespace is not None and not isinstance(secret_namespace, str):
            raise InvalidCommandOutputError(
                f'Command output {location} field "secret_namespace" must be a string '
                'when provided.'
            )

        env = payload_map.get('env')
        if env is not None:
            if isinstance(env, str):
                normalized_env: str | list[str] | None = env
            elif isinstance(env, list):
                env_list = cast(list[object], env)
                if not all(isinstance(item, str) for item in env_list):
                    raise InvalidCommandOutputError(
                        f'Command output {location} field "env" must be a string or list '
                        'of strings when provided.'
                    )
                normalized_env = cast(list[str], env_list)
            else:
                raise InvalidCommandOutputError(
                    f'Command output {location} field "env" must be a string or list '
                    'of strings when provided.'
                )
        else:
            normalized_env = None

        return cls(
            value=payload_map['value'],
            secret_namespace=secret_namespace,
            env=normalized_env,
        )

    def to_mapping(self) -> dict[str, object]:
        """Serialize the model back to a plain mapping for downstream use."""

        payload: dict[str, object] = {'value': self.value}
        if self.secret_namespace is not None:
            payload['secret_namespace'] = self.secret_namespace
        if self.env is not None:
            payload['env'] = self.env
        return payload


@dataclass(frozen=True)
class CommandDatabasePayloadModel:
    """Top-level validated command payload keyed by application name."""

    apps: dict[str, AppDatabaseModel]

    @classmethod
    def from_mapping(cls, payload: object) -> 'CommandDatabasePayloadModel':
        """Validate command output payload and convert it into typed app models."""

        if not isinstance(payload, Mapping):
            raise InvalidCommandOutputError(
                'Command output must be a mapping of app names to app config blocks.'
            )

        payload_map = cast(Mapping[str, object], payload)
        apps: dict[str, AppDatabaseModel] = {}
        for app_name, app_payload in payload_map.items():
            apps[app_name] = AppDatabaseModel.from_mapping(app_name, app_payload)
        return cls(apps=apps)

    def to_mapping(self) -> dict[str, object]:
        """Serialize the top-level payload model to plain nested mappings."""

        output: dict[str, object] = {}
        for app_name, app in self.apps.items():
            output[app_name] = {
                'environments': app.environments,
                'config': app.config,
            }
        return output


class FileDB:
    """File-backed database loader for YAML-based configtool data."""

    def __init__(self, database_path: str):
        """Load and parse the YAML database file from disk."""

        if os.path.exists(database_path):
            with open(database_path, encoding='utf-8') as f:
                self._local_db = yaml.safe_load(f)
        else:
            raise DatabaseNotFoundError('Cannot locate database.')

    @property
    def database(self) -> object:
        """Return the parsed database payload loaded from the file."""

        return self._local_db


class CommandDB:
    """Command-backed database loader that consumes JSON command output."""

    def __init__(
        self,
        command: str | Sequence[str],
        policy: CommandExecutionPolicy | None = None,
    ):
        """Execute the command and cache the validated database payload."""

        self._policy = policy or CommandExecutionPolicy.from_environment()
        self._command_db = self._execute(command)

    @classmethod
    def _resolve_run_mode(
        cls,
        command: str | Sequence[str],
        policy: CommandExecutionPolicy | None = None,
    ) -> tuple[str | list[str], bool]:
        """Resolve command arguments and shell mode under the current policy."""

        resolved_policy = policy or CommandExecutionPolicy.from_environment()
        try:
            return resolved_policy.resolve_run_mode(command)
        except PermissionError as exc:
            raise CommandExecutionError(str(exc)) from exc

    @classmethod
    def _run_command(
        cls,
        command: str | Sequence[str],
        policy: CommandExecutionPolicy | None = None,
    ) -> str:
        """Run the command and return stdout, wrapping process failures."""

        command_arg, shell_mode = cls._resolve_run_mode(command, policy=policy)
        try:
            result = subprocess.run(
                command_arg,
                shell=shell_mode,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise CommandExecutionError(e.stderr)

    def _execute(self, command: str | Sequence[str]) -> dict[str, object]:
        """Execute, parse, and validate command output into a database mapping."""
        output = self._run_command(command, policy=self._policy)

        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            raise InvalidCommandOutputError('Command output is not valid JSON.')

        model = CommandDatabasePayloadModel.from_mapping(parsed)
        return model.to_mapping()

    @property
    def database(self) -> dict[str, object]:
        """Return the validated database payload produced by command execution."""

        return self._command_db
