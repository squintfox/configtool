"""Compatibility facade for config client public types."""

from .core import Config
from .local_config import LocalClientConfigModel, LocalConfigFile

__all__ = [
    'Config',
    'LocalConfigFile',
    'LocalClientConfigModel',
]
