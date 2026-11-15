"""
``Workspaces`` (``ctx.workspace``): open workspaces, cached backends, remembered workspaces, the directory picker.

| member                       | contract                                                                  |
|------------------------------|---------------------------------------------------------------------------|
| ``default``                  | the configured workspace; ``root``, ``resolve`` … delegate to it          |
| ``open(path)``               | a validated :class:`Workspace` for ``path``; ``None`` is the default       |
| ``backend_for(path, shell)`` | cached backend for a workspace; ``shell=False`` gives a filesystem-only one |
| ``recent()`` / ``remember`` / ``forget`` | workspaces used by sessions, kept in ``ctx.store``                |
| ``rename(path, name)``       | display name of a workspace (``None`` restores the directory name)       |
| ``browse(path)``             | one directory level: subdirectories only, for the in-app picker          |
| ``picker()``                 | ``native`` (an OS folder dialog on this machine) or ``browse``            |
| ``pick(prompt)``             | opens the OS folder dialog; the chosen absolute path, or ``None``        |
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent
from typing import Any

from deepagents.backends import FilesystemBackend, LocalShellBackend

from .config import Config
from .workspace import Workspace, WorkspaceError

NAMESPACE = ("pyharness", "workspaces")


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
        default_row = next((r for r in rows if r.get("root") == str(self.default.root)), {})
        default = self.default.describe() | {
            "default": True,
            "exists": True,
            "name": default_row.get("name") or self.default.name,
        }
        out = [default]
        for row in rows:
            if row.get("root") == str(self.default.root):
                continue
            out.append(
                {
                    **row,
                    "name": row.get("name") or Path(row["root"]).name or row["root"],
                    "default": False,
                    "exists": Path(row["root"]).is_dir(),
                }
            )
        return out[: self.config.recent_limit]

    async def remember(self, path: str | os.PathLike[str] | None) -> dict[str, Any]:
        workspace = self.open(path)
        store = self._store()
        previous = await store.aget(NAMESPACE, str(workspace.root)) if store is not None else None
        record = workspace.describe() | {"last_used": time.time()}
        if previous is not None and previous.value.get("name"):
            record["name"] = previous.value["name"]
        if store is not None and workspace is not self.default:
            await store.aput(NAMESPACE, str(workspace.root), record)
        return record

    async def rename(self, path: str | os.PathLike[str] | None, name: str | None) -> dict[str, Any]:
        """Set the display name shown for a workspace; empty or ``None`` restores the directory name."""
        workspace = self.open(path)
        store = self._store()
        if store is None:
            raise WorkspaceError("no store: workspace names are not persisted")
        item = await store.aget(NAMESPACE, str(workspace.root))
        record = dict(item.value) if item is not None else workspace.describe() | {"last_used": time.time()}
        name = (name or "").strip()
        if name:
            record["name"] = name[:80]
        else:
            record.pop("name", None)
            record["name"] = workspace.name
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
            ps = dedent(
                f"""
                Add-Type -AssemblyName System.Windows.Forms;
                $d = New-Object System.Windows.Forms.FolderBrowserDialog;
                $d.Description = '{prompt}'; if ($d.ShowDialog() -eq 'OK') {{ Write-Output $d.SelectedPath }}
                """
            ).strip()
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
        """
        Open the OS folder dialog; the chosen absolute path, ``None`` when cancelled.

        Raises ``WorkspaceError`` without a dialog.
        """
        command = self._native_command(prompt.replace('"', "").replace("'", "")) if self.picker() == "native" else None
        if command is None:
            raise WorkspaceError("no native directory picker on this host")

        def run() -> str | None:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=self.config.picker_timeout, check=False
            )
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
                        dirs.append(
                            {"name": entry.name, "path": str(base / entry.name), "hidden": entry.name.startswith(".")}
                        )
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
