class ConfigtoolClientError(Exception):
    """Base exception for configtool-client package errors."""


class BackendDependencyError(ConfigtoolClientError, ModuleNotFoundError):
    """Raised when required backend package dependencies are unavailable."""


class SourceConfigurationError(ConfigtoolClientError, NotImplementedError):
    """Raised when client config source options are not provided."""


class SecretConfigResolutionError(ConfigtoolClientError, KeyError):
    """Raised when secret namespace config blocks cannot be resolved."""


class SecretsNotInitializedError(ConfigtoolClientError, RuntimeError):
    """Raised when secret operations are attempted before initialization."""
