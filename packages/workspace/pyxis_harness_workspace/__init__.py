from __future__ import annotations

from .config import Config
from .picker import Dialog, dialogs
from .plugin import apply, doc, inject, name
from .registry import Workspaces
from .workspace import DEFAULT_WORKSPACE, Workspace, WorkspaceError

__all__ = [
    "DEFAULT_WORKSPACE",
    "Config",
    "Dialog",
    "Workspace",
    "WorkspaceError",
    "Workspaces",
    "apply",
    "dialogs",
    "doc",
    "inject",
    "name",
]
