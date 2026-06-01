"""Shared helper functions for config namespace and env mapping behavior."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Namespace:
    """Validated namespace reference with root and local parts."""

    root: str
    local: str = 'default'

    def __post_init__(self) -> None:
        """Validate namespace fields after construction."""
        if not self.root:
            raise ValueError('Namespace root must not be empty.')
        if not self.local:
            raise ValueError('Namespace local part must not be empty.')

    @classmethod
    def from_string(cls, namespace: object) -> 'Namespace':
        """Build a namespace object from a namespace string."""
        if not isinstance(namespace, str):
            raise TypeError('Namespace must be provided as a string.')
        if not namespace:
            raise ValueError('Namespace must not be empty.')

        root, local = (
            namespace.split('.', 1) if '.' in namespace else (namespace, 'default')
        )
        return cls(root=root, local=local)

    @property
    def default(self) -> bool:
        """Return whether this namespace resolves to the default block."""
        return self.local == 'default'

    @property
    def qualified(self) -> str:
        """Return the normalized namespace string."""
        return self.root if self.default else f'{self.root}.{self.local}'

    def __str__(self) -> str:
        """Return the normalized namespace string."""
        return self.qualified


def should_include_library(library: str, selected_libraries: list[str]) -> bool:
    """Return whether a library should be included in current projection."""
    if not selected_libraries:
        return True
    return library in selected_libraries


def as_env_var_list(env_vars: str | list[str]) -> list[str]:
    """Normalize one-or-many env var values into a list."""
    if isinstance(env_vars, list):
        return env_vars
    return [env_vars]
