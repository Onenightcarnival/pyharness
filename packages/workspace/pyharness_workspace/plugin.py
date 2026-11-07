"""Plugin entry: ``Config``, ``apply`` providing ``ctx.workspace`` and ``ctx.backend``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .registry import Workspaces
from .workspace import Workspace

name = "pyharness-workspace"
inject = ["tools"]


class Config(BaseModel):
    root: str = Field("${cwd}", description="Default agent working directory.")
    virtual_mode: bool = True
    shell: bool = Field(False, description="`execute` tool on a local, unsandboxed shell.")
    shell_approval: bool = True
    shell_timeout: int = 120
    recent_limit: int = Field(20, description="Workspaces remembered for the picker.")
    picker: Literal["auto", "native", "browse"] = Field(
        "auto", description="Directory picker: the OS dialog when available, else the in-app browser."
    )
    picker_command: list[str] | None = Field(
        None,
        description="Command printing the chosen directory (empty output: cancelled); replaces the platform dialog.",
    )
    picker_timeout: int = Field(600, description="Seconds to wait for the OS dialog.")


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
