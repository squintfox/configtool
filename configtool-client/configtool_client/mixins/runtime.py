from collections.abc import Mapping, MutableMapping
from io import StringIO
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol, cast

from dict_hash import md5  # pyright: ignore[reportUnknownVariableType]
from dotenv import dotenv_values

if TYPE_CHECKING:
    from ..types import InterfaceAdapter


class _ConfigNamespaceLoadHost(Protocol):
    _interface: 'InterfaceAdapter'

    def unlock_secrets(self, libraries: list[str] | None = None) -> None: ...

    def _update_library_hash(self, library: str) -> None: ...


class ConfigRuntimeMixin:
    """Provide runtime map accessors and common state mutation helpers."""

    _interface: 'InterfaceAdapter'
    _library_hashes: dict[str, str]

    @staticmethod
    def _readonly_nested_map(
        data: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Mapping[str, Any]]:
        """Return a read-only view of a nested runtime mapping."""
        return MappingProxyType({k: MappingProxyType(dict(v)) for k, v in data.items()})

    @staticmethod
    def _readonly_flat_map(data: Mapping[str, str]) -> Mapping[str, str]:
        """Return a read-only view of a flat runtime mapping."""
        return MappingProxyType(dict(data))

    @property
    def _libraries_mut(self) -> MutableMapping[str, dict[str, Any]]:
        """Return mutable library map from backend interface."""
        return self._interface.libraries

    @property
    def _secrets_mut(self) -> MutableMapping[str, dict[str, Any]]:
        """Return mutable secret lookup map from backend interface."""
        return self._interface.secrets

    @property
    def _env_mut(self) -> MutableMapping[str, str]:
        """Return mutable env map from backend interface."""
        return self._interface.env

    @property
    def _env_secrets_mut(self) -> MutableMapping[str, str]:
        """Return mutable secret env map from backend interface."""
        return self._interface.env_secrets

    @property
    def libraries(self):
        """Return a read-only view of loaded libraries."""
        resolved = {
            library: self._resolve_runtime_library(library)
            for library in self._libraries_mut
        }
        return self._readonly_nested_map(resolved)

    @property
    def secrets(self):
        """Return a read-only view of secret lookup mappings."""
        return self._readonly_nested_map(self._secrets_mut)

    @property
    def env(self):
        """Return a read-only view of environment variable mappings."""
        return self._readonly_flat_map(self._env_mut)

    @property
    def env_secrets(self):
        """Return a read-only view of secret environment mappings."""
        return self._readonly_flat_map(self._env_secrets_mut)

    def update(self, var_dict: Mapping[str, Any]) -> None:
        """Update library values from library.variable to value mappings."""
        affected_libraries: set[str] = set()
        for lib_var in var_dict:
            library, var = self._split_lib_var(lib_var)
            self._libraries_mut[library][var] = var_dict[lib_var]
            affected_libraries.add(library)
        for library in affected_libraries:
            self._update_library_hash(library)

    def set_secret_lookup(self, namespace: str, lib_var: str, lookup_value: Any) -> None:
        """Set one secret lookup mapping for a namespace."""
        if namespace not in self._secrets_mut:
            self._secrets_mut[namespace] = {}
        self._secrets_mut[namespace][lib_var] = lookup_value

    def set_library_value(self, library: str, var_name: str, value: Any) -> None:
        """Set one library variable value in runtime config."""
        if library not in self._libraries_mut:
            self._libraries_mut[library] = {}
        self._libraries_mut[library][var_name] = value
        self._update_library_hash(library)

    def set_env_mapping(self, env_var: str, lib_var: str, secret: bool = False) -> None:
        """Set one environment variable mapping to a library reference."""
        target = self._env_secrets_mut if secret else self._env_mut
        target[env_var] = lib_var

    def get_value(self, library: str, var: str):
        """Return one variable value from a library."""
        return self._resolve_runtime_library(library)[var]

    def get_library(self, library: str) -> dict[str, Any]:
        """Return all variables for one library."""
        return self._resolve_runtime_library(library)

    def get_library_hash(self, library: str) -> str:
        """Return change hash for one library."""
        return self._library_hashes[library]

    def load_namespace(self, namespace: str, unlock: bool = True, **kwargs: Any) -> None:
        """Load one namespace and refresh derived runtime maps."""
        host = cast(_ConfigNamespaceLoadHost, self)
        host._interface.load_namespace(namespace, **kwargs)
        library = namespace.split('.', 1)[0]
        host._interface.populate(libraries=[library])
        if unlock:
            host.unlock_secrets(libraries=[library])
        host._update_library_hash(library)

    def _update_library_hash(self, library: str):
        """Recompute and store hash for one library."""
        self._library_hashes[library] = md5(self.get_library(library))

    @staticmethod
    def _format_env_file_value(value: Any) -> str:
        """Format one value for dotenv stream parsing."""
        return str(value)

    def _iter_selected_env_refs(
        self, env_map: Mapping[str, str], libraries: list[str]
    ) -> list[tuple[str, str, str]]:
        """Collect selected env mappings as tuples of env var, library, and variable."""
        refs: list[tuple[str, str, str]] = []
        for env_var, lib_var in env_map.items():
            library, var = self._split_lib_var(lib_var)
            if libraries and library not in libraries:
                continue
            refs.append((env_var, library, var))
        return refs

    def _build_env_file_entries(
        self, env_map: Mapping[str, str], libraries: list[str]
    ) -> list[tuple[str, str]]:
        """Build ordered dotenv key/value entries for selected env mappings."""
        entries: list[tuple[str, str]] = []
        for env_var, library, var in self._iter_selected_env_refs(env_map, libraries):
            value = self._libraries_mut[library][var]
            entries.append((env_var, str(value)))
        return entries

    def _build_selected_env_entries(
        self,
        enable_secrets: bool,
        libraries: list[str],
    ) -> list[tuple[str, str]]:
        """Build ordered env key/value entries for selected runtime mappings."""
        entries = self._build_env_file_entries(self._env_mut, libraries=libraries)
        if enable_secrets:
            entries.extend(
                self._build_env_file_entries(
                    self._env_secrets_mut,
                    libraries=libraries,
                )
            )
        return entries

    def _resolve_env_entries_with_dotenv(
        self, entries: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Resolve dotenv interpolation for env entries without side effects."""
        if not entries:
            return []

        stream_lines = [
            f"{key}={self._format_env_file_value(value)}" for key, value in entries
        ]
        stream_content = "\n".join(stream_lines)
        parsed_values = dotenv_values(stream=StringIO(stream_content), interpolate=True)
        return [(key, str(parsed_values.get(key, ''))) for key, _ in entries]

    def _build_resolved_env_entries(
        self,
        enable_secrets: bool,
        libraries: list[str],
    ) -> list[tuple[str, str]]:
        """Build and resolve selected env entries through dotenv interpolation."""
        entries = self._build_selected_env_entries(
            enable_secrets=enable_secrets,
            libraries=libraries,
        )
        return self._resolve_env_entries_with_dotenv(entries)

    def _resolve_runtime_library(self, library: str) -> dict[str, Any]:
        """Resolve one loaded library against the current non-secret env context."""
        raw_library = self._libraries_mut[library]

        env_entries = self._build_selected_env_entries(
            enable_secrets=False,
            libraries=[],
        )

        runtime_entries: list[tuple[str, str]] = []
        runtime_key_to_var: dict[str, str] = {}
        resolved_library: dict[str, Any] = {}

        for index, (var_name, value) in enumerate(raw_library.items()):
            if isinstance(value, str):
                runtime_key = f'CFGT_RUNTIME_{library.upper()}_{index}'
                runtime_key_to_var[runtime_key] = var_name
                runtime_entries.append((runtime_key, value))
            else:
                resolved_library[var_name] = value

        if not runtime_entries:
            return dict(raw_library)

        resolved_entries = self._resolve_env_entries_with_dotenv(
            [*env_entries, *runtime_entries]
        )
        resolved_by_key = dict(resolved_entries)

        for runtime_key, var_name in runtime_key_to_var.items():
            resolved_library[var_name] = resolved_by_key.get(
                runtime_key,
                raw_library[var_name],
            )

        return resolved_library

    @staticmethod
    def _split_lib_var(lib_var: str) -> tuple[str, str]:
        """Split a library.variable reference into its parts."""
        return lib_var.split('.', 1)[0], lib_var.split('.', 1)[1]
