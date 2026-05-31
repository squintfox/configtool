import copy
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from typing import Any, Protocol, cast

from .command_policy import CommandExecutionPolicy
from .db import AppDatabaseModel, CommandDB, FileDB
from .errors import InterfaceSourceError
from .helpers import as_env_var_list, should_include_library
from .internal import AppConfig

VariableDetails = dict[str, Any]
NamespaceBlock = dict[str, VariableDetails]
FlattenedConfig = dict[str, NamespaceBlock]
LibraryValues = dict[str, Any]
LibraryMap = dict[str, LibraryValues]
SecretLookupMap = dict[str, dict[str, Any]]
EnvMap = dict[str, str]
DatabaseDocument = dict[str, Any]


class RuntimeNestedMap(MutableMapping[str, dict[str, Any]]):
    """Store runtime mappings of library names to variable dictionaries."""

    def __init__(self, initial: Mapping[str, Mapping[str, Any]] | None = None):
        """Initialize the runtime nested map."""
        self._data: dict[str, dict[str, Any]] = {}
        if initial:
            self.merge_from(initial)

    @property
    def data(self) -> dict[str, dict[str, Any]]:
        """Return the underlying mutable nested mapping."""
        return self._data

    def merge_from(self, other: Mapping[str, Mapping[str, Any]]) -> None:
        """Deep-merge values from another nested mapping."""
        for namespace, values in other.items():
            if namespace not in self._data:
                self._data[namespace] = copy.deepcopy(dict(values))
            else:
                self._data[namespace].update(copy.deepcopy(dict(values)))

    def __getitem__(self, key: str) -> dict[str, Any]:
        """Implement the __getitem__ special method."""
        return self._data[key]

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        """Implement the __setitem__ special method."""
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        """Implement the __delitem__ special method."""
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        """Implement the __iter__ special method."""
        return iter(self._data)

    def __len__(self) -> int:
        """Implement the __len__ special method."""
        return len(self._data)


class RuntimeFlatMap(MutableMapping[str, str]):
    """Store runtime mappings of environment variables to library refs."""

    def __init__(self, initial: Mapping[str, str] | None = None):
        """Initialize the runtime flat map."""
        self._data: dict[str, str] = {}
        if initial:
            self.merge_from(initial)

    @property
    def data(self) -> dict[str, str]:
        """Return the underlying mutable flat mapping."""
        return self._data

    def merge_from(self, other: Mapping[str, str]) -> None:
        """Merge values from another flat mapping."""
        self._data.update(dict(other))

    def __getitem__(self, key: str) -> str:
        """Implement the __getitem__ special method."""
        return self._data[key]

    def __setitem__(self, key: str, value: str) -> None:
        """Implement the __setitem__ special method."""
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        """Implement the __delitem__ special method."""
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        """Implement the __iter__ special method."""
        return iter(self._data)

    def __len__(self) -> int:
        """Implement the __len__ special method."""
        return len(self._data)


class Libraries(RuntimeNestedMap):
    """Runtime container for loaded library values."""

    pass


class Secrets(RuntimeNestedMap):
    """Runtime container for secret lookup mappings."""

    pass


class EnvMappings(RuntimeFlatMap):
    """Runtime container for environment variable mappings."""

    pass


class DatabaseSource(Protocol):
    """Define the interface for database-backed config sources."""

    @property
    def database(self) -> object:
        """Return the loaded database document."""
        ...


class Interface:
    """Load and project app configuration into runtime maps."""

    def __init__(
        self,
        app_name: str,
        environment: str,
        additional_namespaces: list[str],
        local_db_path: str | None = None,
        local_command_path: str | Sequence[str] | None = None,
        command_policy: CommandExecutionPolicy | None = None,
    ):
        """Initialize interface state and populate runtime maps."""
        self._local_db: DatabaseSource = self._create_local_db(
            local_db_path=local_db_path,
            local_command_path=local_command_path,
            command_policy=command_policy,
        )

        database_document = self._local_db.database
        if not isinstance(database_document, Mapping):
            raise InterfaceSourceError('Database source must deserialize to a mapping.')

        database_mapping = cast(Mapping[str, object], database_document)
        database_map: dict[str, object] = dict(database_mapping)
        normalized_app = AppDatabaseModel.from_mapping(app_name, database_map.get(app_name))
        normalized_database_document: dict[str, object] = copy.deepcopy(database_map)
        normalized_database_document[app_name] = {
            'environments': normalized_app.environments,
            'config': normalized_app.config,
        }

        self._app = AppConfig(app_name, normalized_database_document)

        for namespace in self._app.environments[environment]:
            self._app.load_namespace(namespace)

        if additional_namespaces:
            for namespace in additional_namespaces:
                self._app.load_namespace(namespace)

        self._config: FlattenedConfig = self._app.config

        # {
        #     'library_1.var_name': 'secret_lookup_val',
        #     'library_3.var_name_2': 'secret_lookup_val_2',
        #     'library_4.var_name_3': 'secret_lookup_val_3',
        # }
        self._secrets: Secrets = Secrets()

        # {
        #     'library_1': {
        #         'var_name': 'value',
        #         'var_name_2': 'value',
        #     },
        #     'library_2': {
        #         'var_name': 'value',
        #         'var_name_3': 'value',
        #     },
        # }
        self._libraries: Libraries = Libraries()

        # {
        #     'env_var_name': 'library.var_to_lookup_after_unlock',
        #     'env_var_name_2': 'library_2.var_to_lookup_after_unlock',
        # }
        self._env: EnvMappings = EnvMappings()
        self._env_secrets: EnvMappings = EnvMappings()
        self.populate()

    @staticmethod
    def _create_local_db(
        local_db_path: str | None = None,
        local_command_path: str | Sequence[str] | None = None,
        command_policy: CommandExecutionPolicy | None = None,
    ) -> DatabaseSource:
        """Create a database source from a file path or command path."""
        if local_db_path:
            return FileDB(local_db_path)
        if local_command_path:
            try:
                return CommandDB(local_command_path, policy=command_policy)
            except TypeError:
                # Backward compatibility for tests/mocks with legacy constructor signature.
                return CommandDB(local_command_path)
        raise InterfaceSourceError(
            'Must specify local DB file path or command path.'
        )  # TODO: cloud config?

    @property
    def secrets(self) -> Secrets:
        """Return the collected secret lookup mappings."""
        return self._secrets

    @property
    def libraries(self) -> Libraries:
        """Return the collected library values."""
        return self._libraries

    @property
    def env(self) -> EnvMappings:
        """Return non-secret environment variable mappings."""
        return self._env

    @property
    def env_secrets(self) -> EnvMappings:
        """Return secret-backed environment variable mappings."""
        return self._env_secrets

    def get_config_block(
        self, namespace: str, overlay_default: bool = False
    ) -> NamespaceBlock:
        """Return a namespace config block from the underlying app config."""
        return self._app.get_config_block(namespace, overlay_default=overlay_default)

    def load_namespace(self, namespace: str, **kwargs: Any) -> None:
        """Load one namespace into the underlying app config."""
        self._app.load_namespace(namespace, **kwargs)

    def populate(self, libraries: list[str] | None = None) -> None:
        """Populate runtime maps for all or selected libraries."""
        if libraries is None:
            libraries = []
        for library in self._config:
            if should_include_library(library, libraries):
                self._pop(library)

    def _pop(self, library: str) -> None:
        """Project one library from flattened config into runtime maps."""
        lib_tree = self._config[library]
        if library not in self._libraries:
            self._libraries[library] = {}

        for target_var, target_var_details in lib_tree.items():
            self._project_target_var(library, target_var, target_var_details)

    def _project_target_var(
        self,
        library: str,
        target_var: str,
        target_var_details: VariableDetails,
    ) -> None:
        """Project one variable into library/secret/env runtime maps."""
        if target_var_details.get('secret_namespace'):
            self._record_secret_mapping(library, target_var, target_var_details)
            return

        self._libraries[library][target_var] = target_var_details['value']
        self._record_env_mapping(
            library,
            target_var,
            target_var_details.get('env'),
            self._env,
        )

    def _record_secret_mapping(
        self,
        library: str,
        target_var: str,
        target_var_details: VariableDetails,
    ) -> None:
        """Record secret lookup mapping and related env mapping."""
        secret_namespace = target_var_details['secret_namespace']
        if secret_namespace not in self._secrets:
            self._secrets[secret_namespace] = {}

        lib_var = f'{library}.{target_var}'
        self._secrets[secret_namespace][lib_var] = target_var_details['value']
        self._record_env_mapping(
            library,
            target_var,
            target_var_details.get('env'),
            self._env_secrets,
        )

    def _record_env_mapping(
        self,
        library: str,
        target_var: str,
        env_vars: str | list[str] | None,
        env_target_map: MutableMapping[str, str],
    ) -> None:
        """Record env-var to library-variable references in target map."""
        if not env_vars:
            return

        lib_var = f'{library}.{target_var}'
        for env_var in as_env_var_list(env_vars):
            env_target_map[env_var] = lib_var
