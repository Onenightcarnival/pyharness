"""PTY terminals for the Web UI: one interactive shell per terminal, a scrollback buffer, subscriber queues."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent
from typing import Any

try:  # POSIX only: elsewhere ``pty_available()`` is false and no terminal opens
    import fcntl
    import pty
    import termios
except ImportError:
    fcntl = pty = termios = None  # type: ignore[assignment]


class Terminal:
    """One PTY running an interactive shell; output is kept in a scrollback buffer and pushed to subscribers."""

    def __init__(
        self, id: str, shell: str, cwd: str, cols: int, rows: int, scrollback: int, title: str | None = None
    ) -> None:
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
        """Spawn the shell on a new PTY: the child becomes a session leader with the slave as its controlling
        terminal."""
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LANG": os.environ.get("LANG") or "en_US.UTF-8",
        }
        args = [self.shell, "-l"] if Path(self.shell).name in ("bash", "zsh", "sh", "fish") else [self.shell]
        # A Python wrapper (not preexec_fn, not pty.fork) sets the session and controlling tty, then execs the shell.
        bootstrap = dedent(
            """
            import os, sys, fcntl, termios
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            os.execvp(sys.argv[1], sys.argv[1:])
            """
        ).strip()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", bootstrap, *args],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.cwd,
                env=env,
                close_fds=True,
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
    return pty is not None and os.name == "posix"
