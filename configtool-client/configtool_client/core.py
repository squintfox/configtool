# pyright: reportPrivateUsage=false

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from .errors import (
    BackendDependencyError,
    SourceConfigurationError,
)
from .local_config import LocalConfigFile
from .mixins.env import ConfigEnvironmentMixin
from .mixins.merge import ConfigMergeBlocksMixin
from .mixins.runtime import ConfigRuntimeMixin
from .mixins.secrets import ConfigSecretsMixin
from .types import (
    ConfigBlockMap,
    InterfaceAdapter,
    SecretsAdapter,
)

if TYPE_CHECKING:
    from configtool import CommandExecutionPolicy
    from configtool_secrets.models import SecretConfigBlock
    from configtool_secrets.secrets import SecretCacheManager


class Config(
    ConfigRuntimeMixin,
    ConfigEnvironmentMixin,
    ConfigSecretsMixin,
    ConfigMergeBlocksMixin,
):
    """Client facade for loading, merging, and projecting configtool data."""

    def __init__(
        self,
        local_file_path: str,  # path to configtool file
        local_db_path: str | None = None,  # path to configtool_db file
        local_command_path: str | Sequence[str] | None = None,  # command handler
        command_policy: 'CommandExecutionPolicy | None' = None,
        secrets_cache_manager: 'SecretCacheManager | None' = None,
    ):
        """Initialize client runtime state from local config and selected source."""
        local_config = LocalConfigFile(local_file_path)

        self._command_policy = command_policy
        self._secrets_cache_manager = secrets_cache_manager

        self._interface: InterfaceAdapter = self._create_interface(
            local_config=local_config,
            local_db_path=local_db_path,
            local_command_path=local_command_path,
            command_policy=command_policy,
        )

        self._secrets_obj: SecretsAdapter | None = None
        self._library_hashes: dict[str, str] = {}
        self._secret_config_blocks: dict[str, 'SecretConfigBlock'] = {}
        self._merged_config_blocks: ConfigBlockMap = {}
        # add hashes on initial load
        for library in self._libraries_mut:
            self._update_library_hash(library)

    @staticmethod
    def _import_configtool_module() -> Any:
        """Import and return the configtool backend module."""
        try:
            import configtool
        except ModuleNotFoundError:
            raise BackendDependencyError('Unable to find configtool.  Is it installed?')
        return configtool

    @classmethod
    def _create_interface(
        cls,
        local_config: LocalConfigFile,
        local_db_path: str | None = None,
        local_command_path: str | Sequence[str] | None = None,
        command_policy: 'CommandExecutionPolicy | None' = None,
    ) -> InterfaceAdapter:
        """Create the backend interface using file or command database source."""
        configtool = cls._import_configtool_module()
        if local_db_path:
            return cast(
                InterfaceAdapter,
                configtool.Interface(
                    local_config.app,
                    local_config.environment,
                    local_config.additional_namespaces,
                    local_db_path=local_db_path,
                    command_policy=command_policy,
                ),
            )
        if local_command_path:
            return cast(
                InterfaceAdapter,
                configtool.Interface(
                    local_config.app,
                    local_config.environment,
                    local_config.additional_namespaces,
                    local_command_path=local_command_path,
                    command_policy=command_policy,
                ),
            )
        raise SourceConfigurationError(
            'Must specify local DB path or command path.'
        )  # TODO: cloud config?

    @staticmethod
    def _import_configtool_secrets_module() -> Any:
        """Import and return the optional configtool-secrets module."""
        try:
            import configtool_secrets
        except ModuleNotFoundError:
            raise BackendDependencyError(
                'Unable to find configtool-secrets.  Is it installed?'
            )
        return configtool_secrets

    @classmethod
    def _create_secrets_adapter(
        cls,
        command_policy: 'CommandExecutionPolicy | None' = None,
        secrets_cache_manager: 'SecretCacheManager | None' = None,
    ) -> SecretsAdapter:
        """Create a secrets adapter with optional policy and shared cache."""
        configtool_secrets = cls._import_configtool_secrets_module()
        try:
            return cast(
                SecretsAdapter,
                configtool_secrets.Secrets(
                    command_policy=command_policy,
                    cache_manager=secrets_cache_manager,
                ),
            )
        except TypeError:
            # Backward compatibility for older/mock adapters without injected args.
            return cast(SecretsAdapter, configtool_secrets.Secrets())
