import copy
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from ..services import MergeService
from ..types import ConfigBlock, ConfigBlockMap

if TYPE_CHECKING:
    from configtool_secrets.models import SecretConfigBlock

    from ..core import Config
    from ..types import InterfaceAdapter


class _ConfigMergeHost(Protocol):
    _interface: 'InterfaceAdapter'
    _merged_config_blocks: ConfigBlockMap
    _secret_config_blocks: dict[str, 'SecretConfigBlock']

    @property
    def secrets(self) -> Mapping[str, Mapping[str, Any]]: ...

    @staticmethod
    def _resolve_secret_config_block(
        namespace: str, *configs: 'Config'
    ) -> ConfigBlock | None: ...

    @staticmethod
    def _get_config_block(namespace: str) -> ConfigBlock: ...

    @staticmethod
    def _parse_secret_config_block(namespace: str, block: Any) -> 'SecretConfigBlock': ...

    def _resolve_secret_config_block_values(self, block: Any) -> Any: ...

    def _get_all_config_blocks(self) -> ConfigBlockMap: ...

    def _merge_config_blocks(self, blocks: ConfigBlockMap) -> None: ...


class ConfigMergeBlocksMixin:
    """Provide merge behavior and config-block resolution helpers."""

    def merge(self, merge_config: 'Config') -> None:
        """Merge another Config object into this one, updating libraries and secrets."""
        host = cast(_ConfigMergeHost, self)
        MergeService.merge(cast(Any, self), merge_config)

        # Preserve config blocks from merged configs so secret namespaces can be
        # resolved later even if those namespaces are not part of active environments.
        host._merge_config_blocks(merge_config._get_all_config_blocks())

        # Preserve already-resolved secret blocks from both configs.
        merged_secret_blocks = host._secret_config_blocks.copy()
        merged_secret_blocks.update(getattr(merge_config, '_secret_config_blocks', {}))

        # Ensure every active secret namespace can be resolved from either side.
        for namespace in host.secrets:
            if namespace in merged_secret_blocks:
                continue

            resolved = host._resolve_secret_config_block(
                namespace,
                cast(Any, self),
                merge_config,
            )
            if resolved is not None:
                resolved = host._resolve_secret_config_block_values(resolved)
                merged_secret_blocks[namespace] = host._parse_secret_config_block(
                    namespace,
                    resolved,
                )

        host._secret_config_blocks = merged_secret_blocks

    @staticmethod
    def _merge_nested_runtime_map(
        destination: MutableMapping[str, dict[str, Any]],
        source: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """Merge nested runtime mappings with deep-copy semantics."""
        merge_from = getattr(destination, 'merge_from', None)
        if callable(merge_from):
            merge_from(source)
            return

        for namespace, values in source.items():
            if namespace not in destination:
                destination[namespace] = copy.deepcopy(dict(values))
            else:
                destination[namespace].update(copy.deepcopy(dict(values)))

    @staticmethod
    def _merge_flat_runtime_map(
        destination: MutableMapping[str, str], source: Mapping[str, str]
    ) -> None:
        """Merge flat runtime mappings."""
        merge_from = getattr(destination, 'merge_from', None)
        if callable(merge_from):
            merge_from(source)
            return
        destination.update(dict(source))

    @staticmethod
    def _resolve_secret_config_block(
        namespace: str, *configs: 'Config'
    ) -> ConfigBlock | None:
        """Resolve one namespace config block from one of the provided configs."""
        for config in configs:
            try:
                return config._get_config_block(namespace)
            except KeyError:
                continue
        return None

    def _get_config_block(self, namespace: str) -> ConfigBlock:
        """Get a config block from interface or merged fallback blocks."""
        host = cast(_ConfigMergeHost, self)
        try:
            return host._interface.get_config_block(namespace, overlay_default=False)
        except KeyError:
            root = namespace.split('.', 1)[0]
            local = namespace.split('.', 1)[1] if '.' in namespace else 'default'
            if root in host._merged_config_blocks:
                if local in host._merged_config_blocks[root]:
                    return host._merged_config_blocks[root][local]
            raise

    def _get_all_config_blocks(self) -> ConfigBlockMap:
        """Return merged and local config blocks for secret resolution."""
        host = cast(_ConfigMergeHost, self)
        rtrn = copy.deepcopy(host._merged_config_blocks)
        app = getattr(host._interface, '_app', None)
        local_blocks = getattr(app, '_config_blocks', None)
        if local_blocks:
            for root, namespaces in local_blocks.items():
                if root not in rtrn:
                    rtrn[root] = {}
                for local, block in namespaces.items():
                    rtrn[root][local] = copy.deepcopy(block)
        return rtrn

    def _merge_config_blocks(self, blocks: ConfigBlockMap) -> None:
        """Merge additional config blocks into cached merged config blocks."""
        host = cast(_ConfigMergeHost, self)
        for root, namespaces in blocks.items():
            if root not in host._merged_config_blocks:
                host._merged_config_blocks[root] = {}
            for local, block in namespaces.items():
                host._merged_config_blocks[root][local] = copy.deepcopy(block)
