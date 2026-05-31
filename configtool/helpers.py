"""Shared helper functions for config namespace and env mapping behavior."""


def namespace_is_default(namespace: str) -> bool:
    """Return whether a namespace targets the implicit or explicit default block."""
    spl = namespace.split('.', 1)
    return False if len(spl) > 1 and spl[1] not in ['default'] else True


def split_namespace(namespace: str) -> tuple[str, str]:
    """Split namespace string into root and local namespace parts."""
    root = namespace.split('.', 1)[0]
    local = namespace.split('.', 1)[1] if not namespace_is_default(namespace) else 'default'
    return root, local


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
