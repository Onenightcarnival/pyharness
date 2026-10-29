"""pyharness: an everything-is-a-plugin agent harness on FastAPI, deepagents and LangGraph.

| kernel module              | content                                          |
|----------------------------|--------------------------------------------------|
| ``context``                | service container, registrations, ``Service``    |
| ``events``                 | typed events with declared dispatch modes        |
| ``config``                 | composition tree, layered patches, interpolation |
| ``plugin``                 | plugin forms, entry-point discovery, bundles     |
| ``loader``                 | dependency-driven start, teardown                |
| ``lifecycle``              | holds, restarts, hand-off between generations    |
| ``profile``                | profiles in the harness home                     |
| ``manage``                 | transactional profile mutations                  |
| ``preflight``              | dry boot in a separate process                   |
| ``worker``, ``supervisor`` | process model                                    |
| ``cli``                    | ``pyh``                                          |

Model adapters, tools, the agent loop, persistence and the HTTP API are plugins.
"""

from .config import ConfigError, Entry, PatchOp
from .context import Context, Scope, Service, ServiceConflict, ServiceNotFound, unwrap
from .events import EventModeError, UndeclaredEventError
from .harness import Harness
from .lifecycle import BOOT_FAILURE_EXIT_CODE, RESTART_EXIT_CODE, Lifecycle
from .loader import EntryState, Loader
from .plugin import BUNDLE_GROUP, PLUGIN_GROUP, PluginDef, PluginError, define_plugin
from .profile import Profile

__version__ = "0.1.0"

__all__ = [
    "BOOT_FAILURE_EXIT_CODE",
    "BUNDLE_GROUP",
    "ConfigError",
    "Context",
    "Entry",
    "EntryState",
    "EventModeError",
    "Harness",
    "Lifecycle",
    "Loader",
    "PLUGIN_GROUP",
    "PatchOp",
    "PluginDef",
    "PluginError",
    "Profile",
    "RESTART_EXIT_CODE",
    "Scope",
    "Service",
    "ServiceConflict",
    "ServiceNotFound",
    "UndeclaredEventError",
    "define_plugin",
    "unwrap",
]
