class ConfigtoolError(Exception):
    """Base exception for configtool package errors."""


class DatabaseNotFoundError(ConfigtoolError, ImportError):
    """Raised when a database source path cannot be found."""


class CommandExecutionError(ConfigtoolError, RuntimeError):
    """Raised when command-backed database loading fails."""


class InvalidCommandOutputError(ConfigtoolError, ValueError):
    """Raised when command-backed database output is not valid JSON."""


class InterfaceSourceError(ConfigtoolError, NotImplementedError):
    """Raised when interface initialization lacks a supported data source."""
