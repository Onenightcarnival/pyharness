"""``ctx.terminal``: a persistent shell per session for the agent, background jobs, and PTY terminals for the Web UI.

| piece       | contract                                                                                         |
|-------------|--------------------------------------------------------------------------------------------------|
| ``bash``    | tool: one bash process per agent session (thread id), started in the workspace root; working directory and environment persist between calls; stdin is ``/dev/null``; a timeout kills and restarts the shell |
| jobs        | ``run_in_background`` starts ``bash -c`` with its output in a log file; ``job_output`` / ``job_list`` / ``job_kill``; ``GET /jobs``, ``GET /jobs/{id}``, ``DELETE /jobs/{id}`` |
| terminals   | PTY sessions for the right-sidebar terminal tab: ``POST /terminals``, ``GET /terminals``, ``DELETE /terminals/{id}``, WebSocket ``/terminals/{id}/ws`` (binary frames: bytes; text frames: JSON control) |

The shell tools carry the ``shell`` tag: the agent loop leaves them out in read-only mode. ``bash`` and
``run_in_background`` are gated by ``approval`` (approval prompts in workspace-write mode; none in full access).
PTY terminals need ``pty`` (POSIX); elsewhere the terminal tab reports itself unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import struct
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from pyharness import Service

END_MARK = "__PYH_SHELL_END__"


class Config(BaseModel):
    shell_tool: bool = True
    shell: str = Field("bash", description="Executable of the persistent shell (bash semantics expected).")
    timeout: int = Field(120, ge=1)
    max_timeout: int = Field(900, ge=1)
    max_output_chars: int = Field(16_000, ge=1000)
    approval: bool | dict[str, Any] = Field(default_factory=lambda: {"allowed_decisions": ["approve", "reject"]})
    jobs_tool: bool = True
    job_tail_lines: int = Field(200, ge=10)
    terminal_tab: bool = True
    terminal_shell: str | None = Field(None, description="Interactive shell for PTY terminals; default $SHELL.")
    scrollback_bytes: int = Field(200_000, ge=10_000)
    max_shells: int = Field(16, ge=1)


# ---------------------------------------------------------------------- persistent shell
class ShellSession:
    """One long-lived shell; commands run one at a time with their exit code and working directory read back."""

    def __init__(self, shell: str, cwd: Path, env: dict[str, str] | None = None) -> None:
        self.shell = shell
        self.cwd = cwd
        self.env = {**os.environ, "TERM": "dumb", "PS1": "", "PAGER": "cat", "GIT_PAGER": "cat", **(env or {})}
        self.proc: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.last_used = time.time()
        self.restarts = 0

    async def _ensure(self) -> asyncio.subprocess.Process:
        if self.proc is None or self.proc.returncode is not None:
            self.proc = await asyncio.create_subprocess_exec(
                self.shell,
                "--noprofile",
                "--norc",
                cwd=str(self.cwd),
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        return self.proc

    async def run(self, command: str, timeout: float) -> dict[str, Any]:
        """``{"output", "exit_code", "cwd", "timed_out"}``; a timeout kills the shell and the next call starts a new one."""
        async with self.lock:
            self.last_used = time.time()
            proc = await self._ensure()
            assert proc.stdin is not None and proc.stdout is not None
            script = f'{{\n{command}\n}} </dev/null\nprintf \'\\n{END_MARK} %s %s\\n\' "$?" "$PWD"\n'
            proc.stdin.write(script.encode())
            with contextlib.suppress(Exception):
                await proc.stdin.drain()
            chunks: list[bytes] = []
            timed_out = False
            start = time.monotonic()
            try:
                while True:
                    remaining = timeout - (time.monotonic() - start)
                    if remaining <= 0:
                        raise TimeoutError
                    line = await asyncio.wait_for(proc.stdout.readline(), remaining)
                    if not line:
                        break  # the shell exited (exit, exec failure)
                    text = line.decode(errors="replace")
                    if text.startswith(END_MARK):
                        parts = text.strip().split(" ", 2)
                        code = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else -1
                        if len(parts) > 2:
                            self.cwd = Path(parts[2])
                        output = b"".join(chunks).decode(errors="replace")
                        return {"output": output.rstrip("\n"), "exit_code": code, "cwd": str(self.cwd), "timed_out": False}
                    chunks.append(line)
            except TimeoutError:
                timed_out = True
            await self.close()
            self.restarts += 1
            output = b"".join(chunks).decode(errors="replace")
            return {"output": output.rstrip("\n"), "exit_code": None, "cwd": str(self.cwd), "timed_out": timed_out}

    async def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 5)


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head, tail = text[: limit // 2], text[-(limit // 2) :]
    return f"{head}\n…[{len(text) - limit} characters omitted]…\n{tail}"


# ---------------------------------------------------------------------- background jobs
class Job:
    def __init__(self, id: str, command: str, cwd: str, log: Path, session_id: str | None, name: str | None) -> None:
        self.id = id
        self.command = command
        self.cwd = cwd
        self.log = log
        self.session_id = session_id
        self.name = name or command.strip().splitlines()[0][:60]
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.exit_code: int | None = None
        self.killed = False
        self.proc: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task[Any] | None = None
        self.offsets: dict[str, int] = {}  # reader → bytes already returned

    @property
    def status(self) -> str:
        if self.ended_at is None:
            return "running"
        return "killed" if self.killed else ("exited" if self.exit_code == 0 else "failed")

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "cwd": self.cwd,
            "session_id": self.session_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "pid": self.proc.pid if self.proc is not None and self.ended_at is None else None,
        }

    def read(self, *, tail_lines: int | None = None, since: str | None = None) -> str:
        try:
            data = self.log.read_bytes()
        except FileNotFoundError:
            return ""
        if since is not None:
            start = self.offsets.get(since, 0)
            self.offsets[since] = len(data)
            data = data[start:]
        text = data.decode(errors="replace")
        if tail_lines is not None:
            lines = text.splitlines()
            if len(lines) > tail_lines:
                text = "\n".join(lines[-tail_lines:])
                text = f"…[{len(lines) - tail_lines} earlier lines omitted]…\n{text}"
        return text


class JobRegistry:
    def __init__(self, log_dir: Path, shell: str) -> None:
        self.log_dir = log_dir
        self.shell = shell
        self.jobs: dict[str, Job] = {}

    async def start(self, command: str, cwd: str, *, session_id: str | None = None, name: str | None = None) -> Job:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        job = Job(uuid.uuid4().hex[:8], command, cwd, self.log_dir / f"{uuid.uuid4().hex[:8]}.log", session_id, name)
        log = open(job.log, "wb")  # noqa: SIM115 — handed to the subprocess
        try:
            job.proc = await asyncio.create_subprocess_exec(
                self.shell,
                "-c",
                command,
                cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        self.jobs[job.id] = job

        async def waiter() -> None:
            assert job.proc is not None
            job.exit_code = await job.proc.wait()
            job.ended_at = time.time()

        job.task = asyncio.get_running_loop().create_task(waiter())
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self, session_id: str | None = None) -> list[Job]:
        jobs = [j for j in self.jobs.values() if session_id is None or j.session_id == session_id]
        return sorted(jobs, key=lambda j: j.started_at, reverse=True)

    async def kill(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.proc is None or job.ended_at is not None:
            return False
        job.killed = True
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(job.proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(job.proc.wait(), 3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(job.proc.pid, signal.SIGKILL)
        return True

    async def wait(self, job: Job, timeout: float) -> bool:
        if job.task is None:
            return True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(job.task), timeout)
        return job.ended_at is not None

    async def close(self) -> None:
        for job in list(self.jobs.values()):
            if job.ended_at is None:
                await self.kill(job.id)


# ---------------------------------------------------------------------- PTY terminals
class Terminal:
    """One PTY running an interactive shell; output is kept in a scrollback buffer and pushed to subscribers."""

    def __init__(self, id: str, shell: str, cwd: str, cols: int, rows: int, scrollback: int, title: str | None = None) -> None:
        self.id = id
        self.shell = shell
        self.cwd = cwd
        self.cols, self.rows = cols, rows
        self.scrollback = scrollback
        self.title = title or Path(cwd).name or "terminal"
        self.created_at = time.time()
        self.pid: int | None = None
        self.fd: int | None = None
        self.buffer = bytearray()
        self.exit_code: int | None = None
        self.subscribers: set[asyncio.Queue[bytes | None]] = set()

    def open(self) -> None:
        """Spawn the shell on a new PTY: the child becomes a session leader with the slave as its controlling terminal."""
        import fcntl
        import subprocess
        import termios

        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": os.environ.get("LANG") or "en_US.UTF-8"}
        args = [self.shell, "-l"] if os.path.basename(self.shell) in ("bash", "zsh", "sh", "fish") else [self.shell]
        # A Python wrapper (not preexec_fn, not pty.fork) sets the session and controlling tty, then execs the shell.
        bootstrap = (
            "import os, sys, fcntl, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); os.execvp(sys.argv[1], sys.argv[1:])"
        )
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", bootstrap, *args], stdin=slave, stdout=slave, stderr=slave, cwd=self.cwd, env=env, close_fds=True
            )
        finally:
            os.close(slave)
        self.pid, self.fd = proc.pid, master
        self._proc = proc
        asyncio.get_running_loop().add_reader(master, self._on_readable)

    def _on_readable(self) -> None:
        assert self.fd is not None
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._exited()
            return
        self.buffer.extend(data)
        if len(self.buffer) > self.scrollback:
            del self.buffer[: len(self.buffer) - self.scrollback]
        for queue in list(self.subscribers):
            queue.put_nowait(bytes(data))

    def _exited(self) -> None:
        loop = asyncio.get_running_loop()
        if self.fd is not None:
            with contextlib.suppress(Exception):
                loop.remove_reader(self.fd)
            with contextlib.suppress(OSError):
                os.close(self.fd)
            self.fd = None
        if self.pid is not None and self.exit_code is None:
            proc = getattr(self, "_proc", None)
            try:
                if proc is not None:
                    code = proc.poll()
                    if code is None:
                        code = proc.wait(timeout=2)
                    self.exit_code = code
                else:
                    _, status = os.waitpid(self.pid, os.WNOHANG)
                    self.exit_code = os.waitstatus_to_exitcode(status) if status else 0
            except Exception:  # noqa: BLE001
                self.exit_code = -1
        for queue in list(self.subscribers):
            queue.put_nowait(None)

    @property
    def alive(self) -> bool:
        return self.fd is not None and self.exit_code is None

    def write(self, data: bytes) -> None:
        if self.fd is not None:
            os.write(self.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        import fcntl
        import termios

        self.cols, self.rows = max(2, min(cols, 500)), max(1, min(rows, 300))
        if self.fd is not None:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))

    def subscribe(self) -> asyncio.Queue[bytes | None]:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[bytes | None]) -> None:
        self.subscribers.discard(queue)

    async def close(self) -> None:
        proc = getattr(self, "_proc", None)
        if self.pid is not None and self.exit_code is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.pid, signal.SIGHUP)
            for _ in range(20):
                await asyncio.sleep(0.05)
                if proc is not None and proc.poll() is not None:
                    break
            else:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(self.pid, signal.SIGKILL)
        self._exited()

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "cols": self.cols,
            "rows": self.rows,
            "alive": self.alive,
            "exit_code": self.exit_code,
            "created_at": self.created_at,
            "pid": self.pid,
        }


def pty_available() -> bool:
    try:
        import pty  # noqa: F401

        return os.name == "posix"
    except ImportError:
        return False


class NewTerminal(BaseModel):
    workspace: str | None = None
    cols: int = Field(80, ge=2, le=500)
    rows: int = Field(24, ge=1, le=300)
    title: str | None = None


class Resize(BaseModel):
    cols: int = Field(ge=2, le=500)
    rows: int = Field(ge=1, le=300)


def _thread_id() -> str | None:
    try:
        from langgraph.config import get_config

        return dict(get_config().get("configurable") or {}).get("thread_id")
    except Exception:
        return None


# ---------------------------------------------------------------------- service
class TerminalService(Service):
    key = "terminal"
    name = "pyharness-terminal"
    inject = ["tools", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.shells: dict[str, ShellSession] = {}
        self.terminals: dict[str, Terminal] = {}
        profile = ctx.get("profile", None)
        base = Path(profile.runtime) if profile is not None and hasattr(profile, "runtime") else Path.home() / ".pyharness" / "runtime"
        self.jobs = JobRegistry(base / "jobs", config.shell)

    async def start(self) -> None:
        if self.config.shell_tool:
            self.ctx.tools.register(self._bash_tool(), approval=self.config.approval, tags=("shell",))
        if self.config.jobs_tool:
            self.ctx.tools.register(self._background_tool(), approval=self.config.approval, tags=("shell", "jobs"))
            for tool in self._job_tools():
                self.ctx.tools.register(tool, tags=("jobs",))
        self.ctx.http.include_router(self._router(), prefix="/api", tags=["pyharness-terminal"])
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

    def _bash_tool(self) -> Any:
        from langchain_core.tools import tool

        service = self

        @tool("bash")
        async def bash(command: str, timeout: int | None = None) -> str:
            """Run a bash command in this session's persistent shell. The working directory and environment variables
            persist between calls (the shell starts in the workspace root); stdin is /dev/null. Returns stdout and
            stderr with the exit code; long output is clipped. `timeout` is in seconds (default 120). For commands
            that run longer than a few minutes or servers, use run_in_background instead."""
            if not command.strip():
                return "Error: command must be a non-empty string."
            r = await service.run(command, session_id=_thread_id(), timeout=timeout)
            body = clip(r["output"], service.config.max_output_chars)
            if r["timed_out"]:
                return f"{body}\n\n[timed out after {min(timeout or service.config.timeout, service.config.max_timeout)}s; the shell was killed and restarts in {r['cwd']}. Use run_in_background for long commands.]"
            if r["exit_code"] is None:
                return f"{body}\n\n[the shell exited; a new one starts in {r['cwd']} on the next call]"
            return (
                f"{body}\n\n[exit code {r['exit_code']}; cwd {r['cwd']}]"
                if body
                else f"[exit code {r['exit_code']}; cwd {r['cwd']}; no output]"
            )

        return bash

    # ------------------------------------------------------------------ jobs
    async def start_job(self, command: str, *, session_id: str | None = None, cwd: str | None = None, name: str | None = None) -> Job:
        if cwd is None:
            shell = self.shells.get(session_id or "-")
            cwd = str(shell.cwd) if shell is not None else str(await self.workspace_root(session_id))
        return await self.jobs.start(command, cwd, session_id=session_id, name=name)

    def _background_tool(self) -> Any:
        from langchain_core.tools import tool

        service = self

        @tool("run_in_background")
        async def run_in_background(command: str, name: str | None = None) -> str:
            """Start a long-running bash command (a build, a test suite, a dev server) as a background job in the
            shell's current directory and return its job id at once. Read its output later with job_output, list
            jobs with job_list, stop it with job_kill. Output goes to a log file, not to the chat."""
            if not command.strip():
                return "Error: command must be a non-empty string."
            job = await service.start_job(command, session_id=_thread_id(), name=name)
            return json.dumps({"job_id": job.id, "name": job.name, "cwd": job.cwd, "status": job.status, "log": str(job.log)})

        return run_in_background

    def _job_tools(self) -> list[Any]:
        from langchain_core.tools import tool

        service = self

        @tool("job_output")
        async def job_output(job_id: str, tail_lines: int | None = None, wait: bool = False, timeout: int = 60) -> str:
            """Read a background job's output (the last `tail_lines` lines, default 200) and its status. With `wait`
            the call blocks until the job finishes or `timeout` seconds pass; a timed-out wait leaves it running."""
            job = service.jobs.get(job_id)
            if job is None:
                return f"Error: no job {job_id}. job_list shows the known jobs."
            if wait and job.ended_at is None:
                await service.jobs.wait(job, min(timeout, service.config.max_timeout))
            text = clip(job.read(tail_lines=tail_lines or service.config.job_tail_lines), service.config.max_output_chars)
            info = job.describe()
            status = info["status"] + (f" (exit code {info['exit_code']})" if info["exit_code"] is not None else "")
            return f"[job {job.id} {job.name!r}: {status}]\n{text}" if text else f"[job {job.id} {job.name!r}: {status}; no output yet]"

        @tool("job_list")
        async def job_list() -> str:
            """List background jobs (running and finished) with their ids, names and statuses."""
            jobs = service.jobs.list()
            if not jobs:
                return "No background jobs."
            return "\n".join(
                f"{j.id}  {j.status:<8} {j.name}  (started {time.strftime('%H:%M:%S', time.localtime(j.started_at))})" for j in jobs
            )

        @tool("job_kill")
        async def job_kill(job_id: str) -> str:
            """Stop a running background job."""
            if await service.jobs.kill(job_id):
                return f"job {job_id} stopped"
            return f"job {job_id} is not running" if service.jobs.get(job_id) else f"Error: no job {job_id}"

        return [job_output, job_list, job_kill]

    # ------------------------------------------------------------------ terminals
    def terminal_shell(self) -> str:
        return self.config.terminal_shell or os.environ.get("SHELL") or "/bin/bash"

    def open_terminal(self, cwd: str | None, cols: int = 80, rows: int = 24, title: str | None = None) -> Terminal:
        if not pty_available():
            raise RuntimeError("PTY terminals are unavailable on this platform")
        root = cwd or str(self.default_root())
        term = Terminal(uuid.uuid4().hex[:8], self.terminal_shell(), root, cols, rows, self.config.scrollback_bytes, title)
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

    # ------------------------------------------------------------------ HTTP
    def _router(self) -> APIRouter:
        router = APIRouter()
        service = self

        @router.get("/terminal/status")
        async def terminal_status() -> dict[str, Any]:
            return service.status()

        @router.get("/jobs")
        async def list_jobs(session: str | None = None) -> dict[str, Any]:
            return {"jobs": [j.describe() for j in service.jobs.list(session)]}

        @router.get("/jobs/{job_id}")
        async def get_job(job_id: str, tail: int = 200) -> dict[str, Any]:
            job = service.jobs.get(job_id)
            if job is None:
                raise HTTPException(404, f"no job {job_id}")
            return {**job.describe(), "output": job.read(tail_lines=max(1, min(tail, 5000)))}

        @router.delete("/jobs/{job_id}")
        async def kill_job(job_id: str) -> dict[str, Any]:
            job = service.jobs.get(job_id)
            if job is None:
                raise HTTPException(404, f"no job {job_id}")
            return {"killed": await service.jobs.kill(job_id), **job.describe()}

        @router.get("/terminals")
        async def list_terminals() -> dict[str, Any]:
            return {
                "terminals": [t.describe() for t in service.terminals.values()],
                "available": pty_available() and service.config.terminal_tab,
            }

        @router.post("/terminals")
        async def new_terminal(body: NewTerminal) -> dict[str, Any]:
            if not service.config.terminal_tab:
                raise HTTPException(409, "terminals are disabled in the terminal plugin configuration")
            workspaces = service.ctx.get("workspace", None)
            cwd = body.workspace
            if cwd and workspaces is not None and hasattr(workspaces, "open"):
                try:
                    cwd = str(workspaces.open(cwd).root)
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(422, str(exc)) from None
            try:
                term = service.open_terminal(cwd, body.cols, body.rows, body.title)
            except RuntimeError as exc:
                raise HTTPException(409, str(exc)) from None
            return term.describe()

        @router.post("/terminals/{terminal_id}/resize")
        async def resize_terminal(terminal_id: str, body: Resize) -> dict[str, Any]:
            term = service.terminals.get(terminal_id)
            if term is None:
                raise HTTPException(404, f"no terminal {terminal_id}")
            term.resize(body.cols, body.rows)
            return term.describe()

        @router.delete("/terminals/{terminal_id}")
        async def close_terminal(terminal_id: str) -> dict[str, Any]:
            if not await service.close_terminal(terminal_id):
                raise HTTPException(404, f"no terminal {terminal_id}")
            return {"closed": True}

        @router.websocket("/terminals/{terminal_id}/ws")
        async def terminal_socket(ws: WebSocket, terminal_id: str) -> None:
            term = service.terminals.get(terminal_id)
            if term is None:
                await ws.close(code=4404)
                return
            await ws.accept()
            if term.buffer:
                await ws.send_bytes(bytes(term.buffer))
            if not term.alive:
                await ws.send_text(json.dumps({"type": "exit", "code": term.exit_code}))
                await ws.close()
                return
            queue = term.subscribe()

            async def pump() -> None:
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        await ws.send_text(json.dumps({"type": "exit", "code": term.exit_code}))
                        return
                    await ws.send_bytes(chunk)

            pump_task = asyncio.get_running_loop().create_task(pump())
            try:
                while True:
                    message = await ws.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    if message.get("bytes") is not None:
                        term.write(message["bytes"])
                    elif message.get("text"):
                        try:
                            control = json.loads(message["text"])
                        except ValueError:
                            term.write(message["text"].encode())
                            continue
                        if control.get("type") == "resize":
                            term.resize(int(control.get("cols") or term.cols), int(control.get("rows") or term.rows))
                        elif control.get("type") == "input":
                            term.write(str(control.get("data") or "").encode())
            except WebSocketDisconnect:
                pass
            finally:
                term.unsubscribe(queue)
                pump_task.cancel()
                with contextlib.suppress(BaseException):
                    await pump_task

        return router


__all__ = ["Config", "Job", "JobRegistry", "ShellSession", "Terminal", "TerminalService", "clip", "pty_available"]
