from __future__ import annotations

from .config import Config
from .plugin import apply, doc, inject, name
from .registry import Workspaces
from .workspace import DEFAULT_WORKSPACE, Workspace, WorkspaceError

__all__ = ["DEFAULT_WORKSPACE", "Config", "Workspace", "WorkspaceError", "Workspaces", "apply", "doc", "inject", "name"]
