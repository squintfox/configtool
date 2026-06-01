from typing import Any

from .helpers import Namespace

VariableDetails = dict[str, Any]
NamespaceBlock = dict[str, VariableDetails]
ConfigBlocks = dict[str, dict[str, NamespaceBlock]]
EnvironmentMap = dict[str, list[str]]
FlattenedConfig = dict[str, NamespaceBlock]


class AppConfig:
    """Load and flatten app namespace configuration from a database mapping."""

    def __init__(self, app_name: str, database: dict[str, Any]):
        """Initialize the app config."""
        self._environments = database[app_name]['environments']
        self._config_blocks = database[app_name]['config']

        # this stores the flattened config after you've overlayed all namespaces
        self._config: FlattenedConfig = {}

    @property
    def environments(self) -> EnvironmentMap:
        """Return environment-to-namespace mapping for the app."""
        return self._environments

    @property
    def config(self) -> FlattenedConfig:
        """Return flattened config built from loaded namespaces."""
        return self._config

    def load_namespace(
        self, namespace: str | Namespace, force_default: bool = False
    ) -> None:
        """Load a namespace block into the flattened runtime config."""
        namespace_obj = (
            namespace
            if isinstance(namespace, Namespace)
            else Namespace.from_string(namespace)
        )
        root = namespace_obj.root
        self._ensure_root(root)

        config_block = self.get_config_block(namespace_obj)
        if not config_block:
            return

        if namespace_obj.default:
            self._config[root].update(config_block)
            return

        # Keep existing force_default behavior unchanged (compute-only, no merge).
        if force_default:
            self.get_config_block(namespace_obj, overlay_default=force_default)
            return

        overlay_default = not bool(self._config[root])
        self._config[root].update(
            self.get_config_block(namespace_obj, overlay_default=overlay_default)
        )

    def get_config_block(
        self, namespace: str | Namespace, overlay_default: bool = False
    ) -> NamespaceBlock:
        """Return config block for namespace with optional default overlay."""
        rtrn: NamespaceBlock = {}
        namespace_obj = (
            namespace
            if isinstance(namespace, Namespace)
            else Namespace.from_string(namespace)
        )
        root = namespace_obj.root
        local = namespace_obj.local

        if overlay_default:
            if self._config_blocks[root]['default']:
                rtrn.update(self._config_blocks[root]['default'])
        if self._config_blocks[root][local]:
            rtrn.update(self._config_blocks[root][local])
        return rtrn

    def _ensure_root(self, root: str) -> None:
        """Ensure a root namespace container exists in flattened config."""
        if not self._config.get(root):
            self._config[root] = {}
