import importlib
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from ..errors import SecretConfigResolutionError, SecretsNotInitializedError
from ..services import SecretUnlockService
from ..types import SecretLookupMap

if TYPE_CHECKING:
    from configtool_secrets.models import SecretConfigBlock

    from ..types import InterfaceAdapter, SecretsAdapter


class _ConfigSecretsHost(Protocol):
    _interface: 'InterfaceAdapter'
    _command_policy: Any
    _secrets_cache_manager: Any
    _secrets_obj: 'SecretsAdapter | None'
    _secret_config_blocks: dict[str, 'SecretConfigBlock']

    @property
    def secrets(self) -> Mapping[str, Mapping[str, Any]]: ...

    @property
    def _secrets_mut(self) -> MutableMapping[str, dict[str, Any]]: ...

    def _build_selected_env_entries(
        self,
        enable_secrets: bool,
        libraries: list[str],
    ) -> list[tuple[str, str]]: ...

    def _resolve_env_entries_with_dotenv(
        self, entries: list[tuple[str, str]]
    ) -> list[tuple[str, str]]: ...

    @staticmethod
    def _split_lib_var(lib_var: str) -> tuple[str, str]: ...

    @staticmethod
    def _resolve_secret_config_block(namespace: str, *configs: Any) -> Any: ...

    @staticmethod
    def _create_secrets_adapter(
        command_policy: Any | None = None,
        secrets_cache_manager: Any | None = None,
    ) -> 'SecretsAdapter': ...

    @staticmethod
    def _get_config_block(namespace: str) -> Any: ...

    def _parse_secret_config_block(
        self, namespace: str, block: Any
    ) -> 'SecretConfigBlock': ...


class _ConfigSecretsClassHost(Protocol):
    @staticmethod
    def _import_configtool_secrets_module() -> Any: ...


class ConfigSecretsMixin:
    """Provide secret parsing, selection, and unlock helpers."""

    @property
    def secret_config_blocks(self) -> dict[str, 'SecretConfigBlock']:
        """Return resolved secret config blocks for active secret namespaces."""
        host = cast(_ConfigSecretsHost, self)
        if host._secret_config_blocks:
            rtrn = host._secret_config_blocks.copy()
        else:
            rtrn = {}
        for namespace in host.secrets:
            try:
                raw_block = host._get_config_block(namespace)
                resolved_block = self._resolve_secret_config_block_values(raw_block)
                rtrn[namespace] = host._parse_secret_config_block(
                    namespace,
                    resolved_block,
                )
            except KeyError:
                continue
        host._secret_config_blocks = rtrn
        return rtrn

    def _resolve_secret_config_block_values(self, block: Any) -> Any:
        """Resolve dotenv interpolation in secret config block string value fields."""
        host = cast(_ConfigSecretsHost, self)
        if not isinstance(block, Mapping):
            return block

        env_entries = host._build_selected_env_entries(enable_secrets=False, libraries=[])

        secret_entries: list[tuple[str, str]] = []
        secret_keys: list[tuple[str, str, str]] = []
        for index, (field_name, field_value) in enumerate(block.items()):
            if not isinstance(field_value, Mapping):
                continue
            raw_value = field_value.get('value')
            if not isinstance(raw_value, str):
                continue
            secret_key = f'CFGT_SECRET_BLOCK_{field_name.upper()}_{index}'
            secret_keys.append((field_name, secret_key, raw_value))
            secret_entries.append((secret_key, raw_value))

        if not secret_entries:
            return block

        resolved = dict(
            host._resolve_env_entries_with_dotenv(
                [
                    *env_entries,
                    *secret_entries,
                ]
            )
        )

        resolved_block: dict[str, Any] = dict(block)
        for field_name, secret_key, raw_value in secret_keys:
            field_value = block.get(field_name)
            if not isinstance(field_value, Mapping):
                continue
            updated_field = dict(field_value)
            updated_field['value'] = resolved.get(secret_key, raw_value)
            resolved_block[field_name] = updated_field

        return resolved_block

    @staticmethod
    def _is_typed_secret_config_block(block: Any) -> bool:
        """Return whether the value is already a typed secret config block."""
        return hasattr(block, 'secret_type')

    def _parse_secret_config_block(self, namespace: str, block: Any) -> 'SecretConfigBlock':
        """Parse a raw secret config block into the typed model."""
        if self._is_typed_secret_config_block(block):
            return block

        cast(_ConfigSecretsClassHost, type(self))._import_configtool_secrets_module()
        models = importlib.import_module('configtool_secrets.models')
        return models.parse_secret_config_block(namespace, block)

    def unlock_secrets(self, libraries: list[str] | None = None) -> None:
        """Resolve and apply secrets for all or selected libraries."""
        SecretUnlockService.unlock(cast(Any, self), libraries=libraries)

    def add_secrets_cred(self, cred_option: dict[str, Any]) -> None:
        """Add one credential option to the active secrets adapter."""
        host = cast(_ConfigSecretsHost, self)
        self._init_secrets()

        if not host._secrets_obj:
            raise SecretsNotInitializedError('Secrets object is not initialized')

        host._secrets_obj.cred_options.append(cred_option)

    def _init_secrets(self):
        """Initialize the secrets adapter lazily if needed."""
        host = cast(_ConfigSecretsHost, self)
        if not host._secrets_obj:
            host._secrets_obj = host._create_secrets_adapter(
                command_policy=host._command_policy,
                secrets_cache_manager=host._secrets_cache_manager,
            )

    def _select_secrets(self, libraries: list[str]) -> SecretLookupMap:
        """Select secret lookup mappings for all or selected libraries."""
        host = cast(_ConfigSecretsHost, self)
        if not libraries:
            return dict(host._secrets_mut)

        selected_secrets: SecretLookupMap = {}
        for namespace, namespace_mapping in host._secrets_mut.items():
            selected: dict[str, Any] = {}
            for lib_var, lookup_value in namespace_mapping.items():
                library, _ = host._split_lib_var(lib_var)
                if library in libraries:
                    selected[lib_var] = lookup_value
            if selected:
                selected_secrets[namespace] = selected
        return selected_secrets

    def _resolve_secret_config_blocks(
        self, secrets: SecretLookupMap
    ) -> dict[str, 'SecretConfigBlock']:
        """Resolve and validate secret config blocks for selected namespaces."""
        host = cast(_ConfigSecretsHost, self)
        secret_config_blocks = {
            namespace: host._parse_secret_config_block(namespace, block)
            for namespace, block in host._secret_config_blocks.copy().items()
        }
        for namespace in secrets:
            if namespace in secret_config_blocks:
                continue
            resolved = host._resolve_secret_config_block(namespace, cast(Any, self))
            if resolved is not None:
                resolved = self._resolve_secret_config_block_values(resolved)
                secret_config_blocks[namespace] = host._parse_secret_config_block(
                    namespace,
                    resolved,
                )

        missing_namespaces = [ns for ns in secrets if ns not in secret_config_blocks]
        if missing_namespaces:
            missing_sorted = ', '.join(sorted(missing_namespaces))
            raise SecretConfigResolutionError(
                f'Missing config blocks for secret namespaces: {missing_sorted}'
            )
        return secret_config_blocks
