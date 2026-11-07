"""Plugin entry: ``apply`` providing ``ctx.workspace`` and ``ctx.backend``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .registry import Workspaces
from .workspace import Workspace

name = "pyharness-workspace"
inject = ["tools"]


async def apply(ctx: Any, config: Config) -> None:
    root = Path(config.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    protected: list[Path] = []
    home: Path | None = None
    profile = ctx.get("profile", None)
    if profile is not None:
        home = Path(profile.home).resolve()
        if root == home or home in root.parents:
            raise RuntimeError(
                f"workspace root {root} is inside the harness home {home}; choose another directory (PYH_WORKSPACE)"
            )
        if root in home.parents:
            protected.append(home)
            ctx.logger.warning("harness home %s inside the workspace: file tools denied on it", home)
    workspaces = Workspaces(ctx, config, Workspace(root, config.virtual_mode, protected), home)
    if config.shell and config.shell_approval:
        ctx.tools.require_approval("execute", {"allowed_decisions": ["approve", "reject"]})
    ctx.provide("workspace", workspaces)
    ctx.provide("backend", workspaces.backend_for(None))
