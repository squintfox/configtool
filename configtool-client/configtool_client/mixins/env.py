import os
from typing import Any, cast

from dotenv import set_key

from ..services import EnvironmentExportService


class ConfigEnvironmentMixin:
    """Provide environment export, interpolation, and file writing helpers."""

    def deploy_env(
        self,
        enable_secrets: bool = True,
        libraries: list[str] | None = None,
    ) -> None:
        """Deploy selected mappings into process environment variables."""
        EnvironmentExportService.deploy_env(
            cast(Any, self),
            enable_secrets=enable_secrets,
            libraries=libraries,
        )

    def deploy_env_file(
        self,
        file_path: str,
        enable_secrets: bool = True,
        libraries: list[str] | None = None,
    ) -> None:
        """
        Write environment variables and secrets to a .env file for use with dotenv loaders.
        Overwrites the file if it exists.
        :param file_path: Path to the .env file to write.
        :param enable_secrets: Whether to include secrets in the .env file.
        :param libraries: Optional list of libraries to restrict which variables are written.
        """
        EnvironmentExportService.deploy_env_file(
            cast(Any, self),
            file_path=file_path,
            enable_secrets=enable_secrets,
            libraries=libraries,
        )

    def _deploy_env_entries(self, entries: list[tuple[str, str]]) -> None:
        """Apply resolved env key/value entries to the process environment."""
        for env_var, value in entries:
            os.environ[env_var] = value

    def _deploy_env_file(self, file_path: str, entries: list[tuple[str, str]]) -> None:
        """Write resolved env key/value entries to a dotenv file."""
        # Preserve historical behavior: each call rewrites the target file.
        with open(file_path, 'w', encoding='utf-8'):
            pass

        for env_var, value in entries:
            set_key(
                file_path,
                env_var,
                value,
                quote_mode='auto',
                export=False,
                encoding='utf-8',
            )
