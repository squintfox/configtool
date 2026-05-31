import os
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandExecutionPolicy:
    """Policy for whether command execution may use shell string mode."""

    allow_shell_strings: bool = False

    @classmethod
    def from_environment(cls) -> 'CommandExecutionPolicy':
        """Build policy from CFGT_ALLOW_SHELL_COMMANDS environment setting."""
        allow_shell = os.getenv('CFGT_ALLOW_SHELL_COMMANDS', '').casefold() in {
            '1',
            'true',
            'yes',
            'on',
        }
        return cls(allow_shell_strings=allow_shell)

    def resolve_run_mode(
        self, command: str | Sequence[str]
    ) -> tuple[str | list[str], bool]:
        """Resolve command arguments and shell mode based on current policy."""
        if isinstance(command, str):
            if not self.allow_shell_strings:
                raise PermissionError(
                    'String shell commands are disabled by default. '
                    'Pass a sequence command (recommended) or set '
                    'CFGT_ALLOW_SHELL_COMMANDS=true for compatibility mode.'
                )
            return command, True

        return list(command), False
