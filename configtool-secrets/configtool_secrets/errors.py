class ConfigtoolSecretsError(Exception):
    """Base exception for configtool-secrets package errors."""


class SecretTypeError(ConfigtoolSecretsError, NotImplementedError):
    """Raised when an unknown secret handler type is requested."""


class SecretCredentialError(ConfigtoolSecretsError, RuntimeError):
    """Raised when required secret backend credentials are missing."""


class SecretCommandExecutionError(ConfigtoolSecretsError, RuntimeError):
    """Raised when the command-backed secret handler fails to execute."""
