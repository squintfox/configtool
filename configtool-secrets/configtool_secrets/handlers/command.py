import os
from collections.abc import Mapping, Sequence
from typing import Protocol

from configtool_secrets.errors import SecretCommandExecutionError


class CommandPolicy(Protocol):
    """Define policy behavior for resolving command execution mode."""

    def resolve_run_mode(
        self, command: str | Sequence[str]
    ) -> tuple[str | list[str], bool]:
        """Resolve command arguments and whether shell execution is required."""
        ...


class EnvironmentCommandPolicy:
    """Resolve command execution behavior from environment settings."""

    def resolve_run_mode(
        self, command: str | Sequence[str]
    ) -> tuple[str | list[str], bool]:
        """Resolve command arguments and shell mode from policy rules."""
        if isinstance(command, str):
            allow_shell = os.getenv('CFGT_ALLOW_SHELL_COMMANDS', '').casefold() in {
                '1',
                'true',
                'yes',
                'on',
            }
            if not allow_shell:
                raise PermissionError(
                    'String shell commands are disabled by default. '
                    'Pass a sequence command (recommended) or set '
                    'CFGT_ALLOW_SHELL_COMMANDS=true for compatibility mode.'
                )
            return command, True

        return list(command), False


class Command:
    """Secret handler that executes a command and returns its output."""

    def __init__(
        self,
        command: str | Sequence[str],
        policy: CommandPolicy | None = None,
    ):
        """Initialize command handler with command and execution policy."""
        self._command = command
        self._policy = policy or EnvironmentCommandPolicy()

    @classmethod
    def _resolve_run_mode(
        cls,
        command: str | Sequence[str],
        policy: CommandPolicy | None = None,
    ) -> tuple[str | list[str], bool]:
        """Resolve command arguments and shell mode with policy enforcement."""
        resolved_policy = policy or EnvironmentCommandPolicy()
        try:
            return resolved_policy.resolve_run_mode(command)
        except PermissionError as exc:
            raise SecretCommandExecutionError(str(exc)) from exc

    @classmethod
    def _execute(cls, command: str | Sequence[str]) -> str:
        """Executes the shell command stored in self._command and returns the output."""
        import subprocess

        command_arg, shell_mode = cls._resolve_run_mode(command)

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
            raise SecretCommandExecutionError(e.stderr)

    def unlock(self, secret_config: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
        """
        secret_config (example) - namespace is the one used for secret lookup
        {
            'namespace_1': {
                'library.var_name': 'secret_lookup_val',
                'library.var_name_2': 'secret_lookup_val_2',
            },
            'namespace_2': {'library.var_name_3': 'secret_lookup_val_3'},
        }

        secret_lookup_val is not used for command handler since the command is already provided
        in the config block, but it is still required in the secret_config for consistency
        with other handlers and to allow for potential future use cases where the lookup value
        might be needed.
        """
        rtrn: dict[str, str] = {}
        for app_namespace in secret_config:
            command_arg, shell_mode = self._resolve_run_mode(
                self._command,
                policy=self._policy,
            )
            rtrn[app_namespace] = self._execute_with_run_mode(
                command_arg, shell_mode
            ).strip()
        return rtrn

    @classmethod
    def _execute_with_run_mode(cls, command_arg: str | list[str], shell_mode: bool) -> str:
        """Execute command with the provided shell mode and return stdout."""
        import subprocess

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
            raise SecretCommandExecutionError(e.stderr)
