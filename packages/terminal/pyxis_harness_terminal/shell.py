from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from pathlib import Path
from typing import Any

END_MARK = "__PYH_SHELL_END__"


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
        """
        ``{"output", "exit_code", "cwd", "timed_out"}``; a timeout kills the shell and the next call starts a new
        one.
        """
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
                        return {
                            "output": output.rstrip("\n"),
                            "exit_code": code,
                            "cwd": str(self.cwd),
                            "timed_out": False,
                        }
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
