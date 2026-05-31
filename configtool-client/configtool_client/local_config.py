from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import yaml

from .errors import SourceConfigurationError


@dataclass(frozen=True)
class LocalClientConfigModel:
    """Typed model for local client configuration settings."""

    app: str
    environment: str
    additional_namespaces: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> 'LocalClientConfigModel':
        """Validate and normalize local client config from a mapping."""
        app = data.get('app')
        environment = data.get('environment')
        additional = data.get('additional_namespaces', [])

        if not isinstance(app, str) or not app.strip():
            raise SourceConfigurationError(
                'configtool.yml field "app" must be a non-empty string.'
            )
        if not isinstance(environment, str) or not environment.strip():
            raise SourceConfigurationError(
                'configtool.yml field "environment" must be a non-empty string.'
            )

        if additional is None:
            additional_list: list[str] = []
        elif isinstance(additional, list):
            additional_items = cast(list[object], additional)
            if not all(isinstance(item, str) for item in additional_items):
                raise SourceConfigurationError(
                    'configtool.yml field "additional_namespaces" must be a list of strings.'
                )
            additional_list = cast(list[str], additional_items)
        else:
            raise SourceConfigurationError(
                'configtool.yml field "additional_namespaces" must be a list of strings.'
            )

        return cls(
            app=app,
            environment=environment,
            additional_namespaces=tuple(additional_list),
        )


class LocalConfigFile:
    """Load and expose local client config settings from YAML."""

    def __init__(self, file_path: str):
        """Initialize the local config file."""
        with open(file_path, encoding='utf-8') as f:
            loaded: object = yaml.safe_load(f)
        parsed: object = loaded or {}
        if not isinstance(parsed, Mapping):
            raise SourceConfigurationError(
                'configtool.yml must deserialize to a mapping object.'
            )
        self._model = LocalClientConfigModel.from_mapping(cast(Mapping[str, Any], parsed))

    @property
    def app(self) -> str:
        """Return configured app name."""
        return self._model.app

    @property
    def environment(self) -> str:
        """Return configured environment name."""
        return self._model.environment

    @property
    def additional_namespaces(self) -> list[str]:
        """Return configured additional namespaces."""
        return list(self._model.additional_namespaces)
