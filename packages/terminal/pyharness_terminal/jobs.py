from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
import uuid
from pathlib import Path
from typing import Any


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
        log = job.log.open("wb")
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
