from __future__ import annotations

import contextlib
import os
import uuid
from pathlib import Path
from typing import Any, ClassVar

from pyharness import Service

from .config import Config
from .jobs import Job, JobRegistry
from .pty import Terminal, pty_available
from .routes import make_router
from .shell import ShellSession
from .tools import background_tool, bash_tool, job_tools


class TerminalService(Service):
    key = "terminal"
    name = "pyxis-harness-terminal"
    inject: ClassVar[list[str]] = ["tools", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.shells: dict[str, ShellSession] = {}
        self.terminals: dict[str, Terminal] = {}
        profile = ctx.get("profile", None)
        base = (
            Path(profile.runtime)
            if profile is not None and hasattr(profile, "runtime")
            else Path.home() / ".pyharness" / "runtime"
        )
        self.jobs = JobRegistry(base / "jobs", config.shell)

    async def start(self) -> None:
        if self.config.shell_tool:
            self.ctx.tools.register(bash_tool(self), approval=self.config.approval, tags=("shell",))
        if self.config.jobs_tool:
            self.ctx.tools.register(background_tool(self), approval=self.config.approval, tags=("shell", "jobs"))
            for tool in job_tools(self):
                self.ctx.tools.register(tool, tags=("jobs",))
        self.ctx.http.include_router(make_router(self), prefix="/api", tags=["pyxis-harness-terminal"])
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))
        self.ctx.on("app/stopping", self.stop)

    async def stop(self) -> None:
        for shell in list(self.shells.values()):
            await shell.close()
        self.shells.clear()
        for term in list(self.terminals.values()):
            await term.close()
        self.terminals.clear()
        await self.jobs.close()

    # ------------------------------------------------------------------ shells
    def default_root(self) -> Path:
        workspaces = self.ctx.get("workspace", None)
        if workspaces is not None and hasattr(workspaces, "default"):
            return Path(workspaces.default.root)
        return Path.cwd()

    async def workspace_root(self, session_id: str | None) -> Path:
        """Root of the session's workspace (the default workspace without a session)."""
        workspaces = self.ctx.get("workspace", None)
        agents = self.ctx.get("agents", None)
        record: dict[str, Any] | None = None
        if session_id and agents is not None and hasattr(agents, "get_session"):
            with contextlib.suppress(Exception):
                record = await agents.get_session(session_id)
        if workspaces is not None and hasattr(workspaces, "open"):
            try:
                return Path(workspaces.open((record or {}).get("workspace")).root)
            except Exception:  # noqa: BLE001
                return self.default_root()
        return Path.cwd()

    async def shell_for(self, session_id: str | None, cwd: Path | None = None) -> ShellSession:
        key = session_id or "-"
        shell = self.shells.get(key)
        if shell is None:
            if len(self.shells) >= self.config.max_shells:
                oldest = min(self.shells, key=lambda k: self.shells[k].last_used)
                await self.shells.pop(oldest).close()
            shell = ShellSession(self.config.shell, cwd or await self.workspace_root(session_id))
            self.shells[key] = shell
        return shell

    async def run(
        self, command: str, *, session_id: str | None = None, timeout: int | None = None, cwd: Path | None = None
    ) -> dict[str, Any]:
        shell = await self.shell_for(session_id, cwd)
        limit = min(timeout or self.config.timeout, self.config.max_timeout)
        return await shell.run(command, limit)

    # ------------------------------------------------------------------ jobs
    async def start_job(
        self, command: str, *, session_id: str | None = None, cwd: str | None = None, name: str | None = None
    ) -> Job:
        if cwd is None:
            shell = self.shells.get(session_id or "-")
            cwd = str(shell.cwd) if shell is not None else str(await self.workspace_root(session_id))
        return await self.jobs.start(command, cwd, session_id=session_id, name=name)

    # ------------------------------------------------------------------ terminals
    def terminal_shell(self) -> str:
        return self.config.terminal_shell or os.environ.get("SHELL") or "/bin/bash"

    def open_terminal(self, cwd: str | None, cols: int = 80, rows: int = 24, title: str | None = None) -> Terminal:
        if not pty_available():
            raise RuntimeError("PTY terminals are unavailable on this platform")
        root = cwd or str(self.default_root())
        term = Terminal(
            uuid.uuid4().hex[:8], self.terminal_shell(), root, cols, rows, self.config.scrollback_bytes, title
        )
        term.open()
        self.terminals[term.id] = term
        return term

    async def close_terminal(self, terminal_id: str) -> bool:
        term = self.terminals.pop(terminal_id, None)
        if term is None:
            return False
        await term.close()
        return True

    def status(self) -> dict[str, Any]:
        return {
            "shells": len(self.shells),
            "jobs": len(self.jobs.jobs),
            "terminals": len(self.terminals),
            "pty": pty_available() and self.config.terminal_tab,
            "terminal_shell": self.terminal_shell(),
        }
