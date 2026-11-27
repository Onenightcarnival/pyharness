from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from pyxis_harness import Service, manage

from .config import Config
from .jobs import Job, JobRegistry
from .pty import Terminal, pty_available
from .routes import make_router
from .shell import Shell, shell_of
from .tools import job_tools, shell_tool

LIVE = ("timeout", "max_output_chars", "promote_on_timeout")  # read at each command
ON_RESTART = ("dialect", "shell", "pwsh")  # the tool's name and its executable


class TerminalService(Service):
    key = "terminal"
    name = "pyxis-harness-terminal"
    inject: ClassVar[list[str]] = ["tools", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.shell: Shell = shell_of(config.dialect, config.shell, config.pwsh)
        self.terminals: dict[str, Terminal] = {}
        profile = ctx.get("profile", None)
        base = (
            Path(profile.runtime)
            if profile is not None and hasattr(profile, "runtime")
            else Path.home() / ".pyharness" / "runtime"
        )
        self.jobs = JobRegistry(base / "jobs", self.shell, config.grace)

    async def start(self) -> None:
        self._register_shell_tool()
        if self.config.jobs_tool:
            for tool in job_tools(self):
                self.ctx.tools.register(tool, tags=("jobs",))
        self.ctx.http.include_router(make_router(self), prefix="/api", tags=["pyxis-harness-terminal"])
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))
        self.ctx.on("app/stopping", self.stop)

    def _register_shell_tool(self) -> None:
        dispose, self._shell_tool = getattr(self, "_shell_tool", None), None
        if dispose is not None:
            dispose()
        if self.config.shell_tool:
            tool = shell_tool(self)
            self._shell_tool = self.ctx.tools.register(tool, approval=self.config.approval, tags=("shell",))

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        """The shell tool's settings, and the shell in effect in this generation."""
        return {
            **{key: getattr(self.config, key) for key in (*LIVE, *ON_RESTART, "max_timeout")},
            "effective": {"dialect": self.shell.dialect, "executable": self.shell.executable},
            "platform": sys.platform,
        }

    async def save(self, fields: dict[str, Any]) -> dict[str, Any]:
        """
        Change settings and persist them in the profile patch.

        | fields                                                    | take effect                          |
        |-----------------------------------------------------------|--------------------------------------|
        | ``timeout``, ``max_output_chars``, ``promote_on_timeout`` | at once: the next command            |
        | ``dialect``, ``shell``, ``pwsh``                          | in the next generation; a restart is |
        |                                                           | requested when the shell changes     |
        """
        changed = {key: value for key, value in fields.items() if getattr(self.config, key) != value}
        try:
            config = Config.model_validate({**self.config.model_dump(), **changed})
        except ValidationError as exc:
            raise ValueError("; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())) from None
        if config.timeout > config.max_timeout:
            raise ValueError(f"timeout is at most {config.max_timeout} seconds")
        chosen = shell_of(config.dialect, config.shell, config.pwsh)
        named = [changed[key] for key in ("shell", "pwsh") if changed.get(key)]
        for executable in [*named, *([chosen.executable] if chosen != self.shell else [])]:
            if shutil.which(executable) is None:
                raise ValueError(f"{executable} is not an executable on this machine")
        profile = self.ctx.get("profile", None)
        if changed and profile is not None:
            await manage.set_entry_config(profile, "terminal", changed, merge=True, preflight=False)
        self.config = config
        if any(key in LIVE for key in changed):
            self._register_shell_tool()  # its parameter texts name the timeout
        restart = chosen != self.shell  # the tool's name or executable changes
        if restart:
            self.ctx.lifecycle.request_restart("shell settings")
        return {"application": "restart" if restart else "applied", **self.settings()}

    async def stop(self) -> None:
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

    async def workdir(self, session_id: str | None, workdir: str | None = None) -> Path:
        """Directory a command starts in: the session's workspace root, or ``workdir`` resolved against it."""
        root = await self.workspace_root(session_id)
        path = root / Path(workdir).expanduser() if workdir else root
        if not path.is_dir():
            raise ValueError(f"workdir {path} is not a directory")
        return path

    @property
    def background(self) -> bool:
        """Whether a command can go on as a background job: the job tools are there to read and stop it."""
        return self.config.jobs_tool

    async def run(
        self, command: str, *, session_id: str | None = None, timeout: int | None = None, workdir: str | None = None
    ) -> dict[str, Any]:
        """
        Run ``command`` in a fresh shell and wait for it, at most ``timeout`` seconds.

        ``{"cwd", "output", "truncated", "log", "exit_code", "signal", "timed_out", "stopped", "job_id", "timeout"}``.
        At the timeout the command goes on as the background job ``job_id`` (``promote_on_timeout``) or is stopped
        (``timed_out``). ``stopped``: ended from outside this call. A cancelled call stops the command.
        """
        cwd = await self.workdir(session_id, workdir)
        limit = min(timeout or self.config.timeout, self.config.max_timeout)
        job = await self.jobs.start(command, str(cwd), session_id=session_id, foreground=True)
        try:
            finished = await self.jobs.wait(job, limit)
        except asyncio.CancelledError:
            await self.jobs.kill(job.id)
            self.jobs.discard(job)
            raise
        promoted = not finished and self.background and self.config.promote_on_timeout
        stopped = finished and job.killed
        if not finished and not promoted:
            await self.jobs.kill(job.id)
        output, truncated = job.tail(self.config.max_output_chars)
        result = {
            "cwd": str(cwd),
            "output": output,
            "truncated": truncated,
            "log": str(job.log) if truncated else None,
            "exit_code": job.exit_code,
            "signal": job.signal,
            "timed_out": not finished and not promoted,
            "stopped": stopped,
            "job_id": job.id if promoted else None,
            "timeout": limit,
        }
        if promoted:
            job.foreground = False
        else:
            self.jobs.discard(job, keep_log=truncated)
        return result

    # ------------------------------------------------------------------ jobs
    async def start_job(
        self, command: str, *, session_id: str | None = None, workdir: str | None = None, name: str | None = None
    ) -> Job:
        cwd = await self.workdir(session_id, workdir)
        return await self.jobs.start(command, str(cwd), session_id=session_id, name=name)

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
            "shell": {"dialect": self.shell.dialect, "executable": self.shell.executable},
            "jobs": len(self.jobs.jobs),
            "terminals": len(self.terminals),
            "pty": pty_available() and self.config.terminal_tab,
            "terminal_shell": self.terminal_shell(),
        }
