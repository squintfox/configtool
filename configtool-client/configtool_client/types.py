from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from configtool_secrets.models import SecretConfigBlock

    from .core import Config

LibraryMap = dict[str, dict[str, Any]]
SecretLookupMap = dict[str, dict[str, Any]]
EnvMap = dict[str, str]
ConfigBlock = dict[str, Any]
ConfigBlockMap = dict[str, dict[str, ConfigBlock]]


class InterfaceAdapter(Protocol):
    """Define the interface required from a configtool backend adapter."""

    @property
    def libraries(self) -> MutableMapping[str, dict[str, Any]]:
        """Return mutable library values grouped by library name."""
        ...

    @property
    def secrets(self) -> MutableMapping[str, dict[str, Any]]:
        """Return mutable secret lookup mappings grouped by library name."""
        ...

    @property
    def env(self) -> MutableMapping[str, str]:
        """Return mutable environment variable mappings."""
        ...

    @property
    def env_secrets(self) -> MutableMapping[str, str]:
        """Return mutable secret environment variable mappings."""
        ...

    _app: Any

    def get_config_block(
        self, namespace: str, overlay_default: bool = False
    ) -> ConfigBlock:
        """Get a config block for the provided namespace."""
        ...

    def load_namespace(self, namespace: str, **kwargs: Any) -> None:
        """Load one namespace into the current runtime maps."""
        ...

    def populate(self, libraries: list[str] | None = None) -> None:
        """Populate runtime maps for selected libraries or all libraries."""
        ...


class SecretsAdapter(Protocol):
    """Define the interface required from a secrets backend adapter."""

    cred_options: list[dict[str, Any]]

    def unlock(
        self,
        secrets: SecretLookupMap,
        blocks: dict[str, 'SecretConfigBlock'],
        /,
    ) -> dict[str, Any]:
        """Unlock secrets for the provided lookup map and secret config blocks."""
        ...
