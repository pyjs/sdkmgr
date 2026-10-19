"""Discover and provision development tools without changing global selections."""

from .android import AndroidInstallation
from .clang import ClangInstallation
from .core import Installation, Manager
from .errors import InstallationRequired, SDKError
from .installation import ToolInstallation

__all__ = [
    "AndroidInstallation", "ClangInstallation", "Installation", "InstallationRequired",
    "Manager", "SDKError", "ToolInstallation",
]
__version__ = "0.2.0"
