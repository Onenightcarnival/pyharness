from __future__ import annotations

from .config import ConfigError, Entry, PatchOp
from .context import Context, Scope, Service, ServiceConflict, ServiceNotFound, unwrap
from .credentials import CredentialStore
from .events import EventModeError, UndeclaredEventError
from .harness import Harness
from .lifecycle import BOOT_FAILURE_EXIT_CODE, RESTART_EXIT_CODE, Lifecycle
from .loader import EntryState, Loader
from .plugin import BUNDLE_GROUP, PLUGIN_GROUP, PluginDef, PluginError, define_plugin
from .profile import Profile
from .resources import package_prompts, package_toml

__version__ = "0.1.0"

__all__ = [
    "BOOT_FAILURE_EXIT_CODE",
    "BUNDLE_GROUP",
    "PLUGIN_GROUP",
    "RESTART_EXIT_CODE",
    "ConfigError",
    "Context",
    "CredentialStore",
    "Entry",
    "EntryState",
    "EventModeError",
    "Harness",
    "Lifecycle",
    "Loader",
    "PatchOp",
    "PluginDef",
    "PluginError",
    "Profile",
    "Scope",
    "Service",
    "ServiceConflict",
    "ServiceNotFound",
    "UndeclaredEventError",
    "define_plugin",
    "package_prompts",
    "package_toml",
    "unwrap",
]
