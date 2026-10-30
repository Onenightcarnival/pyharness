"""Workspace provider: ``ctx.workspace`` (paths) and ``ctx.backend`` (deepagents backend).

| config           | backend               | agent file tools                                                     |
|------------------|-----------------------|----------------------------------------------------------------------|
| ``shell: false`` | ``FilesystemBackend`` | ``ls``, ``read_file``, ``write_file`` … on ``root``                  |
| ``shell: true``  | ``LocalShellBackend`` | the same plus ``execute``; approval unless ``shell_approval: false`` |

``virtual_mode``: agent paths start at ``/`` = ``root`` and stay inside it.

| harness home vs ``root`` | effect                                         |
|--------------------------|------------------------------------------------|
| home inside root         | file tools denied on the home (read and write) |
| root inside home         | plugin fails                                   |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

name = "pyharness-workspace"
inject = ["tools"]


class Config(BaseModel):
    root: str = Field("${cwd}", description="Agent working directory.")
    virtual_mode: bool = True
    shell: bool = Field(False, description="`execute` tool on a local, unsandboxed shell.")
    shell_approval: bool = True
    shell_timeout: int = 120


class Workspace:
    def __init__(self, root: Path, virtual_mode: bool, protected: list[Path] | None = None) -> None:
        self.root = root
        self.virtual_mode = virtual_mode
        self.protected = list(protected or [])

    def resolve(self, path: str) -> Path:
        """Real path of an agent path (``/plugins/x``); raises ``ValueError`` outside the root or inside the home."""
        raw = Path(path)
        candidate = (self.root / str(path).lstrip("/")).resolve() if self.virtual_mode or not raw.is_absolute() else raw.resolve()
        if self.virtual_mode and candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"{path!r} escapes the workspace root")
        for guarded in self.protected:
            if candidate == guarded or guarded in candidate.parents:
                raise ValueError(f"{path!r} is inside the harness home: access denied")
        return candidate

    def permissions(self) -> list[Any]:
        """deepagents ``FilesystemPermission`` rules: deny read and write on protected paths."""
        from deepagents import FilesystemPermission

        rules = []
        for guarded in self.protected:
            base = "/" + guarded.relative_to(self.root).as_posix() if self.virtual_mode else guarded.as_posix()
            rules.append(FilesystemPermission(operations=["read", "write"], paths=[base, base.rstrip("/") + "/**"], mode="deny"))
        return rules

    def describe(self) -> dict[str, Any]:
        return {"root": str(self.root), "virtual_mode": self.virtual_mode, "protected": [str(p) for p in self.protected]}


async def apply(ctx: Any, config: Config) -> None:
    from deepagents.backends import FilesystemBackend, LocalShellBackend

    root = Path(config.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    protected: list[Path] = []
    profile = ctx.get("profile", None)
    if profile is not None:
        home = Path(profile.home).resolve()
        if root == home or home in root.parents:
            raise RuntimeError(f"workspace root {root} is inside the harness home {home}; choose another directory (PYH_WORKSPACE)")
        if root in home.parents:
            protected.append(home)
            ctx.logger.warning("harness home %s inside the workspace: file tools denied on it", home)
    if config.shell:
        backend: Any = LocalShellBackend(root_dir=root, virtual_mode=config.virtual_mode, timeout=config.shell_timeout)
        if config.shell_approval:
            ctx.tools.require_approval("execute", {"allowed_decisions": ["approve", "reject"]})
    else:
        backend = FilesystemBackend(root_dir=root, virtual_mode=config.virtual_mode)
    ctx.provide("workspace", Workspace(root, config.virtual_mode, protected))
    ctx.provide("backend", backend)
