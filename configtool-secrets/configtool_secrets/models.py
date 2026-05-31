from dataclasses import dataclass
from typing import Any

from .constants import (
    HANDLER_TYPE_COMMAND,
    HANDLER_TYPE_FILE,
    HANDLER_TYPE_KEYVAULT,
    HANDLER_TYPE_VAULTWARDEN,
)
from .errors import SecretTypeError


@dataclass(frozen=True)
class SecretConfigBlock:
    """Base typed model for secret namespace configuration blocks."""

    secret_type: str


@dataclass(frozen=True)
class KeyVaultSecretConfigBlock(SecretConfigBlock):
    """Typed secret config block for Key Vault secrets."""

    vault_uri: str


@dataclass(frozen=True)
class FileSecretConfigBlock(SecretConfigBlock):
    """Typed secret config block for file-based secrets."""

    file_path: str


@dataclass(frozen=True)
class CommandSecretConfigBlock(SecretConfigBlock):
    """Typed secret config block for command-based secrets."""

    command: str | list[str]


@dataclass(frozen=True)
class VaultwardenSecretConfigBlock(SecretConfigBlock):
    """Typed secret config block for Vaultwarden secrets."""

    vault_url: str
    folder_name: str = ''


def _get_value(mapping: dict[str, dict[str, Any]], key: str) -> Any:
    """Extract nested value field for a required config key."""
    return mapping[key]['value']


def parse_secret_config_block(
    namespace: str, block: dict[str, dict[str, Any]]
) -> SecretConfigBlock:
    """Parse secret config block."""
    try:
        secret_type = _get_value(block, 'secret_type')
    except KeyError as exc:
        raise SecretTypeError(
            f'Missing required secret_type for namespace: {namespace}'
        ) from exc

    if secret_type == HANDLER_TYPE_KEYVAULT:
        return KeyVaultSecretConfigBlock(
            secret_type=secret_type,
            vault_uri=_get_value(block, 'vault-uri'),
        )

    if secret_type == HANDLER_TYPE_FILE:
        return FileSecretConfigBlock(
            secret_type=secret_type,
            file_path=_get_value(block, 'file-path'),
        )

    if secret_type == HANDLER_TYPE_COMMAND:
        return CommandSecretConfigBlock(
            secret_type=secret_type,
            command=_get_value(block, 'command'),
        )

    if secret_type == HANDLER_TYPE_VAULTWARDEN:
        return VaultwardenSecretConfigBlock(
            secret_type=secret_type,
            vault_url=_get_value(block, 'vault-url'),
            folder_name=block.get('folder-name', {}).get('value', ''),
        )

    raise SecretTypeError(f'Unknown secret type: {secret_type}')
