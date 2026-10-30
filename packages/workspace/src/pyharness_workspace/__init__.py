"""Workspace provider: ``ctx.workspace`` (the workspace registry) and ``ctx.backend`` (the default deepagents backend).

| config           | backend               | agent file tools                                                     |
|------------------|-----------------------|----------------------------------------------------------------------|
| ``shell: false`` | ``FilesystemBackend`` | ``ls``, ``read_file``, ``write_file`` … on the workspace root        |
| ``shell: true``  | ``LocalShellBackend`` | the same plus ``execute``; approval unless ``shell_approval: false`` |

``virtual_mode``: agent paths start at ``/`` = root and stay inside it.

| member                       | contract                                                                  |
|------------------------------|---------------------------------------------------------------------------|
| ``default``                  | the configured workspace (``config.root``); ``root``, ``resolve`` … delegate to it |
| ``open(path)``               | a validated :class:`Workspace` for ``path``; ``None`` is the default       |
| ``backend_for(path, shell)`` | cached backend for a workspace; ``shell=False`` gives a filesystem-only one |
| ``recent()`` / ``remember`` / ``forget`` | workspaces used by sessions, kept in ``ctx.store``                |
| ``browse(path)``             | one directory level: subdirectories only, for the in-app picker          |
| ``picker()``                 | ``native`` (an OS folder dialog on this machine) or ``browse``            |
| ``pick(prompt)``             | opens the OS folder dialog; the chosen absolute path, or ``None``        |

| platform | native dialog                                   |
|----------|-------------------------------------------------|
| macOS    | ``osascript`` ``choose folder``                 |
| Windows  | PowerShell ``FolderBrowserDialog``              |
| Linux    | ``zenity`` or ``kdialog`` when a display exists |

| harness home vs root     | effect                                         |
|--------------------------|------------------------------------------------|
| home inside root         | file tools denied on the home (read and write) |
| root inside home         | refused                                        |
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

name = "pyharness-workspace"
inject = ["tools"]

NAMESPACE = ("pyharness", "workspaces")


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
        None, description="Command printing the chosen directory (empty output: cancelled); replaces the platform dialog."
    )
    picker_timeout: int = Field(600, description="Seconds to wait for the OS dialog.")


class WorkspaceError(ValueError):
    """A path cannot be a workspace."""


class Workspace:
    def __init__(self, root: Path, virtual_mode: bool, protected: list[Path] | None = None) -> None:
        self.root = root
        self.virtual_mode = virtual_mode
        self.protected = list(protected or [])

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)

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
        return {"root": str(self.root), "name": self.name, "virtual_mode": self.virtual_mode, "protected": [str(p) for p in self.protected]}


class Workspaces:
    """Workspace registry; ``ctx.workspace``. Attribute access of the default workspace stays available."""

    def __init__(self, ctx: Any, config: Config, default: Workspace, home: Path | None) -> None:
        self.ctx = ctx
        self.config = config
        self.default = default
        self.home = home
        self.shell = config.shell
        self._open: dict[Path, Workspace] = {default.root: default}
        self._backends: dict[tuple[Path, bool], Any] = {}

    # ------------------------------------------------------------------ default delegation
    @property
    def root(self) -> Path:
        return self.default.root

    @property
    def virtual_mode(self) -> bool:
        return self.default.virtual_mode

    @property
    def protected(self) -> list[Path]:
        return self.default.protected

    def resolve(self, path: str) -> Path:
        return self.default.resolve(path)

    def permissions(self) -> list[Any]:
        return self.default.permissions()

    def describe(self) -> dict[str, Any]:
        return self.default.describe()

    # ------------------------------------------------------------------ registry
    def open(self, path: str | os.PathLike[str] | None) -> Workspace:
        """Validated workspace for ``path``; ``None`` or the default root → the default workspace."""
        if path is None or str(path) == "":
            return self.default
        raw = Path(path).expanduser()
        if not raw.is_absolute():
            raise WorkspaceError(f"workspace path {str(path)!r} must be absolute")
        root = raw.resolve()
        if root in self._open:
            return self._open[root]
        if not root.is_dir():
            raise WorkspaceError(f"{root} is not a directory")
        protected: list[Path] = []
        if self.home is not None:
            if root == self.home or self.home in root.parents:
                raise WorkspaceError(f"{root} is inside the harness home {self.home}")
            if root in self.home.parents:
                protected.append(self.home)
        workspace = Workspace(root, self.config.virtual_mode, protected)
        self._open[root] = workspace
        return workspace

    def backend_for(self, path: str | os.PathLike[str] | None, shell: bool | None = None) -> Any:
        """Backend for a workspace; ``shell`` overrides the configured shell setting (``False``: file tools only)."""
        from deepagents.backends import FilesystemBackend, LocalShellBackend

        workspace = self.open(path)
        use_shell = self.config.shell if shell is None else (shell and self.config.shell)
        key = (workspace.root, use_shell)
        if key not in self._backends:
            if use_shell:
                self._backends[key] = LocalShellBackend(
                    root_dir=workspace.root, virtual_mode=workspace.virtual_mode, timeout=self.config.shell_timeout
                )
            else:
                self._backends[key] = FilesystemBackend(root_dir=workspace.root, virtual_mode=workspace.virtual_mode)
        return self._backends[key]

    def _store(self) -> Any:
        return self.ctx.get("store", None)

    async def recent(self) -> list[dict[str, Any]]:
        """Remembered workspaces, most recently used first; the default workspace is always first."""
        rows: list[dict[str, Any]] = []
        store = self._store()
        if store is not None:
            items = await store.asearch(NAMESPACE, limit=self.config.recent_limit * 2)
            rows = sorted((dict(i.value) for i in items), key=lambda r: r.get("last_used") or 0, reverse=True)
        default = self.default.describe() | {"default": True, "exists": True}
        out = [default]
        for row in rows:
            if row.get("root") == str(self.default.root):
                continue
            out.append({**row, "default": False, "exists": Path(row["root"]).is_dir()})
        return out[: self.config.recent_limit]

    async def remember(self, path: str | os.PathLike[str] | None) -> dict[str, Any]:
        workspace = self.open(path)
        record = workspace.describe() | {"last_used": time.time()}
        store = self._store()
        if store is not None and workspace is not self.default:
            await store.aput(NAMESPACE, str(workspace.root), record)
        return record

    async def forget(self, path: str) -> bool:
        store = self._store()
        if store is None:
            return False
        key = str(Path(path).expanduser().resolve())
        if await store.aget(NAMESPACE, key) is None:
            return False
        await store.adelete(NAMESPACE, key)
        return True

    # ------------------------------------------------------------------ OS picker
    def _native_command(self, prompt: str) -> list[str] | None:
        if self.config.picker_command:
            return list(self.config.picker_command)
        if sys.platform == "darwin" and shutil.which("osascript"):
            return ["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}")']
        if sys.platform == "win32":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$d.Description = '{prompt}'; if ($d.ShowDialog() -eq 'OK') {{ Write-Output $d.SelectedPath }}"
            )
            return ["powershell", "-NoProfile", "-Command", ps]
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            if shutil.which("zenity"):
                return ["zenity", "--file-selection", "--directory", f"--title={prompt}"]
            if shutil.which("kdialog"):
                return ["kdialog", "--getexistingdirectory", str(Path.home()), "--title", prompt]
        return None

    def picker(self) -> str:
        """``native`` when an OS folder dialog can open on this machine, else ``browse``."""
        if self.config.picker == "browse":
            return "browse"
        if self.config.picker == "native" or self._native_command("x") is not None:
            return "native"
        return "browse"

    async def pick(self, prompt: str = "Choose a workspace directory") -> str | None:
        """Open the OS folder dialog; the chosen absolute path, ``None`` when cancelled. Raises ``WorkspaceError`` without a dialog."""
        command = self._native_command(prompt.replace('"', "").replace("'", "")) if self.picker() == "native" else None
        if command is None:
            raise WorkspaceError("no native directory picker on this host")

        def run() -> str | None:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=self.config.picker_timeout)
            output = proc.stdout.strip()
            if proc.returncode != 0 or not output:
                return None  # cancelled
            return output.rstrip("/") or "/"

        try:
            chosen = await asyncio.get_running_loop().run_in_executor(None, run)
        except subprocess.TimeoutExpired:
            raise WorkspaceError("the directory dialog timed out") from None
        return str(Path(chosen).expanduser().resolve()) if chosen else None

    def browse(self, path: str | None = None) -> dict[str, Any]:
        """One directory level for a picker: ``path``, ``parent``, ``dirs`` (name-sorted, hidden flagged), ``home``."""
        base = Path(path).expanduser() if path else Path.home()
        if not base.is_absolute():
            raise WorkspaceError(f"path {path!r} must be absolute")
        base = base.resolve()
        if not base.is_dir():
            raise WorkspaceError(f"{base} is not a directory")
        dirs = []
        try:
            for entry in sorted(os.scandir(base), key=lambda e: e.name.lower()):
                try:
                    if entry.is_dir(follow_symlinks=True):
                        dirs.append({"name": entry.name, "path": str(base / entry.name), "hidden": entry.name.startswith(".")})
                except OSError:
                    continue
        except PermissionError as exc:
            raise WorkspaceError(f"{base} is not readable") from exc
        selectable = True
        try:
            self.open(base)
        except WorkspaceError:
            selectable = False
        return {
            "path": str(base),
            "parent": str(base.parent) if base.parent != base else None,
            "dirs": dirs,
            "home": str(Path.home()),
            "selectable": selectable,
        }


async def apply(ctx: Any, config: Config) -> None:
    root = Path(config.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    protected: list[Path] = []
    home: Path | None = None
    profile = ctx.get("profile", None)
    if profile is not None:
        home = Path(profile.home).resolve()
        if root == home or home in root.parents:
            raise RuntimeError(f"workspace root {root} is inside the harness home {home}; choose another directory (PYH_WORKSPACE)")
        if root in home.parents:
            protected.append(home)
            ctx.logger.warning("harness home %s inside the workspace: file tools denied on it", home)
    workspaces = Workspaces(ctx, config, Workspace(root, config.virtual_mode, protected), home)
    if config.shell and config.shell_approval:
        ctx.tools.require_approval("execute", {"allowed_decisions": ["approve", "reject"]})
    ctx.provide("workspace", workspaces)
    ctx.provide("backend", workspaces.backend_for(None))


__all__ = ["Config", "Workspace", "WorkspaceError", "Workspaces"]
