import atexit
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, cast

from configtool_secrets.handlers.command import CommandPolicy

from .constants import (
    HANDLER_TYPE_COMMAND,
    HANDLER_TYPE_FILE,
    HANDLER_TYPE_KEYVAULT,
    HANDLER_TYPE_VAULTWARDEN,
)
from .errors import SecretCredentialError, SecretTypeError
from .handlers.command import Command
from .handlers.file import File
from .handlers.keyvault import AzureKeyVault
from .handlers.vaultwarden import Vaultwarden
from .models import (
    CommandSecretConfigBlock,
    FileSecretConfigBlock,
    KeyVaultSecretConfigBlock,
    SecretConfigBlock,
    VaultwardenSecretConfigBlock,
)

SecretValueMap = dict[str, str]
SecretConfigMap = dict[str, SecretValueMap]
SecretNamespaceConfig = SecretConfigBlock
OperationTargets = dict[Any, SecretValueMap]
OperationPlan = dict[str, OperationTargets]
VaultwardenKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class ProviderRegistration:
    """Register resolver and factory callables for one secret provider type."""

    target_key_resolver: Callable[['Secrets', SecretNamespaceConfig], Any]
    provider_factory: Callable[['Secrets', Any], 'SecretHandler']


@dataclass
class SecretCacheManager:
    """Hold shared caches for reusable secret provider state."""

    vaultwarden_clients: dict[VaultwardenKey, Vaultwarden] = field(
        default_factory=lambda: cast(dict[VaultwardenKey, Vaultwarden], {})
    )
    unlock_cache: dict[str, Any] = field(default_factory=lambda: cast(dict[str, Any], {}))


class SecretHandler(Protocol):
    """Define the interface implemented by all secret providers."""

    def unlock(self, secret_config: SecretValueMap, /) -> SecretValueMap:
        """Return resolved secret values for one namespace config block."""
        ...


class Secrets:
    """Coordinate secret provider selection, batching, and value resolution."""

    def __init__(
        self,
        cache_manager: SecretCacheManager | None = None,
        command_policy: CommandPolicy | None = None,
    ):
        """Initialize secrets orchestrator with optional shared cache and policy."""
        self.cred_options: list[dict[str, Any]] = []
        self._cache_manager = cache_manager or SecretCacheManager()
        self._vaultwarden_clients = self._cache_manager.vaultwarden_clients
        self._unlock_cache = self._cache_manager.unlock_cache
        self._command_policy = command_policy
        self._provider_registry = self._build_provider_registry()
        atexit.register(self.close)

    @staticmethod
    def create_shared_cache_manager() -> SecretCacheManager:
        """Create a cache manager that can be reused across Secrets instances."""
        return SecretCacheManager()

    def register_provider(
        self,
        secret_type: str,
        target_key_resolver: Callable[['Secrets', SecretNamespaceConfig], Any],
        provider_factory: Callable[['Secrets', Any], SecretHandler],
        *,
        override: bool = False,
    ) -> None:
        """Register or override provider behavior for a secret type."""
        if not override and secret_type in self._provider_registry:
            raise SecretTypeError(
                f'Provider is already registered for secret type: {secret_type}'
            )
        self._provider_registry[secret_type] = ProviderRegistration(
            target_key_resolver=target_key_resolver,
            provider_factory=provider_factory,
        )

    def unlock(self, secret_config: SecretConfigMap, config: dict[str, SecretConfigBlock]):
        """
        secret_config (example) - namespace is the one used for secret lookup
        {
            'namespace_1': {
                'library.var_name': 'secret_lookup_val',
                'library.var_name_2': 'secret_lookup_val_2',
            },
            'namespace_2': {'library.var_name_3': 'secret_lookup_val_3'},
        }
        """
        self._config = config
        operations = self._plan_operations(secret_config)
        return self._execute_operations(operations)

    def _plan_operations(self, secret_config: SecretConfigMap) -> OperationPlan:
        """Group secret requests by provider type and provider target key."""
        operations: OperationPlan = {}
        for namespace in secret_config:
            namespace_payload = secret_config.get(namespace)
            if not namespace_payload:
                continue

            block = self._get_config_block(namespace)
            secret_type = block.secret_type
            if secret_type not in self._provider_registry:
                raise SecretTypeError(f'Unknown secret type: {secret_type}')

            operations.setdefault(secret_type, {})
            self._append_namespace_operations(
                operations=operations,
                secret_type=secret_type,
                block=block,
                namespace_payload=namespace_payload,
            )
        return operations

    def _append_namespace_operations(
        self,
        operations: OperationPlan,
        secret_type: str,
        block: SecretNamespaceConfig,
        namespace_payload: SecretValueMap,
    ) -> None:
        """Append one namespace payload to the grouped operation plan."""
        registration = self._provider_registry.get(secret_type)
        if not registration:
            raise SecretTypeError(f'Unknown secret type: {secret_type}')

        target_key = registration.target_key_resolver(self, block)
        self._append_payload(operations[secret_type], target_key, namespace_payload)

    @staticmethod
    def _append_payload(
        operation_targets: OperationTargets,
        target_key: Any,
        namespace_payload: SecretValueMap,
    ) -> None:
        """Merge one namespace payload into a target-key bucket."""
        if target_key not in operation_targets:
            operation_targets[target_key] = {}
        for app_var in namespace_payload:
            operation_targets[target_key][app_var] = namespace_payload[app_var]

    def _execute_operations(self, operations: OperationPlan) -> SecretValueMap:
        """Execute grouped operations and merge resolved secret values."""
        resolved: SecretValueMap = {}

        for secret_type, grouped_targets in operations.items():
            registration = self._provider_registry.get(secret_type)
            if not registration:
                raise SecretTypeError(f'Unknown secret type: {secret_type}')

            for target_key, payload in grouped_targets.items():
                provider = registration.provider_factory(self, target_key)
                resolved.update(provider.unlock(payload))

        return resolved

    @staticmethod
    def _resolve_standard_value_key(
        block: SecretNamespaceConfig, field_name: str
    ) -> str | list[str]:
        """Resolve provider target key from a standard block field."""
        if isinstance(block, KeyVaultSecretConfigBlock) and field_name == 'vault-uri':
            return block.vault_uri
        if isinstance(block, FileSecretConfigBlock) and field_name == 'file-path':
            return block.file_path
        if isinstance(block, CommandSecretConfigBlock) and field_name == 'command':
            return block.command
        raise SecretTypeError(
            f'Block type {type(block).__name__} does not expose field {field_name}'
        )

    def _resolve_vaultwarden_key(
        self, block: SecretNamespaceConfig
    ) -> tuple[str, str, str, str]:
        """Resolve Vaultwarden connection key from block and env credentials."""
        if not isinstance(block, VaultwardenSecretConfigBlock):
            raise SecretTypeError(
                f'Vaultwarden key requested for non-vaultwarden block: {type(block).__name__}'
            )

        vault_url = block.vault_url
        username = os.getenv('CFGT_VAULTWARDEN_USERNAME')
        password = os.getenv('CFGT_VAULTWARDEN_PASSWORD')
        folder_name = block.folder_name
        if not username or not password:
            raise SecretCredentialError(
                'Vaultwarden credentials not found in environment variables '
                'CFGT_VAULTWARDEN_USERNAME and CFGT_VAULTWARDEN_PASSWORD'
            )
        return vault_url, username, password, folder_name

    def _build_provider_registry(self) -> dict[str, ProviderRegistration]:
        """Build the default provider registry for supported secret handlers."""
        return {
            HANDLER_TYPE_KEYVAULT: ProviderRegistration(
                target_key_resolver=lambda s, block: s._resolve_standard_value_key(
                    block, 'vault-uri'
                ),
                provider_factory=lambda s, target_key: cast(
                    SecretHandler,
                    AzureKeyVault(target_key, cred_options=s.cred_options),
                ),
            ),
            HANDLER_TYPE_FILE: ProviderRegistration(
                target_key_resolver=lambda s, block: s._resolve_standard_value_key(
                    block, 'file-path'
                ),
                provider_factory=lambda _s, target_key: cast(
                    SecretHandler,
                    File(target_key),
                ),
            ),
            HANDLER_TYPE_COMMAND: ProviderRegistration(
                target_key_resolver=lambda s, block: s._resolve_standard_value_key(
                    block, 'command'
                ),
                provider_factory=lambda s, target_key: s._create_command_provider(
                    target_key
                ),
            ),
            HANDLER_TYPE_VAULTWARDEN: ProviderRegistration(
                target_key_resolver=lambda s, block: s._resolve_vaultwarden_key(block),
                provider_factory=lambda s, target_key: cast(
                    SecretHandler,
                    s._get_vaultwarden(target_key),
                ),
            ),
        }

    def _create_command_provider(self, command: str | list[str]) -> SecretHandler:
        """Create a command-based secret provider with policy compatibility fallback."""
        try:
            return cast(SecretHandler, Command(command, policy=self._command_policy))
        except TypeError:
            return cast(SecretHandler, Command(command))

    def _build_cache_key(self, secret_config: dict[str, Any]) -> str | None:
        """Build a stable cache key for secret config payloads when possible."""
        try:
            return json.dumps(secret_config, sort_keys=True, separators=(',', ':'))
        except (TypeError, ValueError):
            return None

    def _get_vaultwarden(self, vault_key: VaultwardenKey) -> Vaultwarden:
        """Get or create a cached Vaultwarden client for a vault key."""
        if vault_key in self._vaultwarden_clients:
            return self._vaultwarden_clients[vault_key]

        vault_url, username, password, folder_name = vault_key
        vaultwarden = Vaultwarden(
            vault_url=vault_url,
            username=username,
            password=password,
            folder_name=folder_name,
        )
        vaultwarden.login()
        self._vaultwarden_clients[vault_key] = vaultwarden
        return vaultwarden

    def close(self):
        """Close cached provider clients and clear runtime caches."""
        for vaultwarden in self._vaultwarden_clients.values():
            vaultwarden.close()
        self._vaultwarden_clients.clear()
        self._unlock_cache.clear()

    def _get_config_block(self, namespace: str) -> SecretConfigBlock:
        """Return typed secret config block for a namespace."""
        return self._config[namespace]
