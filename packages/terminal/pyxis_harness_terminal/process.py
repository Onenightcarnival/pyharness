from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from typing import Any

from . import win32

WINDOWS = sys.platform == "win32"
POLL = 0.05


def signal_group(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):  # macOS answers EPERM for a group of zombies
        return False
    return True


def signal_name(returncode: int | None) -> str | None:
    """Name of the signal that ended a POSIX process (a negative return code); ``None`` otherwise."""
    if returncode is None or returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"signal {-returncode}"


class Tree:
    """A started process with the processes it starts: one owner for the wait and for the kill."""

    def __init__(self, proc: asyncio.subprocess.Process, job: int | None = None) -> None:
        self.proc = proc
        self.job = job  # Windows: the Job Object holding the tree; without one the kill goes through taskkill

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def running(self) -> bool:
        return self.proc.returncode is None

    async def kill(self, grace: float) -> None:
        """
        End the tree and wait for its root.

        POSIX: SIGTERM to the process group, SIGKILL to what is left of it after ``grace`` seconds.
        Windows: every process of the Job Object at once (taskkill of the process tree without one); no
        graceful stage exists for console processes.
        """
        if not self.running:
            return
        if WINDOWS:
            if self.job is None or not win32.terminate(self.job):
                await asyncio.to_thread(win32.taskkill, self.pid)
        else:
            signal_group(self.pid, signal.SIGTERM)
            deadline = asyncio.get_running_loop().time() + grace
            while group_alive(self.pid) and asyncio.get_running_loop().time() < deadline:  # noqa: ASYNC110
                await asyncio.sleep(POLL)
            signal_group(self.pid, signal.SIGKILL)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.proc.wait(), grace)

    def release(self) -> None:
        """Windows: close the Job Object, which ends the processes still in it."""
        job, self.job = self.job, None
        if job is not None:
            win32.close(job)


async def spawn(argv: list[str], *, cwd: str, env: dict[str, str], stdout: Any) -> Tree:
    """Start ``argv`` as the root of its own tree: stdin empty, stderr joined to ``stdout``, no console window."""
    options: dict[str, Any] = {"creationflags": win32.CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=stdout,
        stderr=asyncio.subprocess.STDOUT,
        **options,
    )
    return Tree(proc, win32.own(proc.pid) if WINDOWS else None)
