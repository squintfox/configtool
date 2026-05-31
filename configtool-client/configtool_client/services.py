from typing import TYPE_CHECKING

from .errors import SecretsNotInitializedError

if TYPE_CHECKING:
    from .core import Config


class MergeService:
    """Provide helper operations for merging Config runtime state."""

    @staticmethod
    def merge(target: 'Config', source: 'Config') -> None:
        """Merge runtime maps from one Config into another."""
        target._merge_nested_runtime_map(target._libraries_mut, source._libraries_mut)
        for library in source._libraries_mut:
            target._update_library_hash(library)

        target._merge_nested_runtime_map(target._secrets_mut, source._secrets_mut)
        target._merge_flat_runtime_map(target._env_mut, source._env_mut)
        target._merge_flat_runtime_map(target._env_secrets_mut, source._env_secrets_mut)


class SecretUnlockService:
    """Provide helper operations for unlocking secrets in Config."""

    @staticmethod
    def unlock(config: 'Config', libraries: list[str] | None = None) -> None:
        """Unlock secrets for all or selected libraries."""
        if libraries is None:
            libraries = []

        config._init_secrets()
        secrets = config._select_secrets(libraries=libraries)
        if not secrets:
            return

        secret_config_blocks = config._resolve_secret_config_blocks(secrets)
        config._secret_config_blocks = secret_config_blocks
        scoped_secret_blocks = {ns: secret_config_blocks[ns] for ns in secrets}

        if not config._secrets_obj:
            raise SecretsNotInitializedError('Secrets object is not initialized')

        unlocked = config._secrets_obj.unlock(secrets, scoped_secret_blocks)
        config.update(unlocked)


class EnvironmentExportService:
    """Provide helper operations for exporting environment variables."""

    @staticmethod
    def deploy_env(
        config: 'Config',
        enable_secrets: bool = True,
        libraries: list[str] | None = None,
    ) -> None:
        """Export selected config values into process environment variables."""
        if libraries is None:
            libraries = []
        resolved_entries = config._build_resolved_env_entries(
            enable_secrets=enable_secrets,
            libraries=libraries,
        )
        config._deploy_env_entries(resolved_entries)

    @staticmethod
    def deploy_env_file(
        config: 'Config',
        file_path: str,
        enable_secrets: bool = True,
        libraries: list[str] | None = None,
    ) -> None:
        """Write selected environment mappings to a dotenv-style file."""
        if libraries is None:
            libraries = []
        resolved_entries = config._build_resolved_env_entries(
            enable_secrets=enable_secrets,
            libraries=libraries,
        )
        config._deploy_env_file(file_path, resolved_entries)
