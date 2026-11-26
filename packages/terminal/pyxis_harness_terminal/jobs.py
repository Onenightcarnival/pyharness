from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from pathlib import Path
from typing import Any

from .process import Tree, signal_name, spawn
from .shell import Shell, decode, tail


class Job:
    """One command: its process tree and the log file its output goes to."""

    def __init__(
        self,
        id: str,
        command: str,
        cwd: str,
        log: Path,
        session_id: str | None,
        name: str | None,
        foreground: bool = False,
    ) -> None:
        self.id = id
        self.command = command
        self.cwd = cwd
        self.log = log
        self.session_id = session_id
        self.name = name or command.strip().splitlines()[0][:60]
        self.foreground = foreground  # a tool call is waiting for it
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.exit_code: int | None = None
        self.killed = False
        self.tree: Tree | None = None
        self.task: asyncio.Task[Any] | None = None
        self.offsets: dict[str, int] = {}  # reader → bytes already returned

    @property
    def status(self) -> str:
        if self.ended_at is None:
            return "running"
        return "killed" if self.killed else ("exited" if self.exit_code == 0 else "failed")

    @property
    def signal(self) -> str | None:
        return signal_name(self.exit_code)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "cwd": self.cwd,
            "session_id": self.session_id,
            "status": self.status,
            "foreground": self.foreground,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "pid": self.tree.pid if self.tree is not None and self.ended_at is None else None,
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
        text = decode(data)
        if tail_lines is not None:
            lines = text.splitlines()
            if len(lines) > tail_lines:
                text = "\n".join(lines[-tail_lines:])
                text = f"…[{len(lines) - tail_lines} earlier lines omitted]…\n{text}"
        return text

    def tail(self, max_chars: int) -> tuple[str, bool]:
        """The end of the output, at most ``max_chars`` characters; and whether earlier output was left out."""
        window = max_chars * 4  # bytes that hold ``max_chars`` characters of any UTF-8 text
        try:
            with self.log.open("rb") as log:
                size = log.seek(0, 2)
                log.seek(max(0, size - window))
                data = log.read()
        except FileNotFoundError:
            return "", False
        text, cut = tail(decode(data), max_chars)
        return text, cut or size > window


class JobRegistry:
    def __init__(self, log_dir: Path, shell: Shell, grace: float = 3.0) -> None:
        self.log_dir = log_dir
        self.shell = shell
        self.grace = grace
        self.jobs: dict[str, Job] = {}

    async def start(
        self,
        command: str,
        cwd: str,
        *,
        session_id: str | None = None,
        name: str | None = None,
        foreground: bool = False,
    ) -> Job:
        """Start ``command`` in a fresh shell in ``cwd``; its output goes to the job's log file."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{uuid.uuid4().hex[:8]}.log"
        job = Job(uuid.uuid4().hex[:8], command, cwd, log_path, session_id, name, foreground)
        with job.log.open("wb") as log:
            job.tree = await spawn(self.shell.argv(command), cwd=cwd, env=self.shell.environment(), stdout=log)
        self.jobs[job.id] = job

        async def waiter() -> None:
            assert job.tree is not None
            job.exit_code = await job.tree.proc.wait()
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
        if job is None or job.tree is None or job.ended_at is not None:
            return False
        job.killed = True
        await job.tree.kill(self.grace)
        await self.wait(job, self.grace)
        return True

    async def wait(self, job: Job, timeout: float) -> bool:
        if job.task is None:
            return True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(job.task), timeout)
        return job.ended_at is not None

    def discard(self, job: Job, *, keep_log: bool = False) -> None:
        """Forget a job; its log goes with it unless ``keep_log``."""
        self.jobs.pop(job.id, None)
        if job.tree is not None:
            job.tree.release()
        if not keep_log:
            with contextlib.suppress(OSError):  # Windows: a process that outlived the kill still holds the file
                job.log.unlink(missing_ok=True)

    async def close(self) -> None:
        for job in list(self.jobs.values()):
            if job.ended_at is None:
                await self.kill(job.id)
            if job.tree is not None:
                job.tree.release()
