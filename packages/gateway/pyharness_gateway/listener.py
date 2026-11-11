"""Listener of the gateway application: a uvicorn server of its own, restarted when the settings change.

| member        | contract                                                                          |
|---------------|-----------------------------------------------------------------------------------|
| ``apply()``   | stop the running server, then listen on ``host:port`` when ``enabled``; one apply at a time |
| ``close()``   | stop the server                                                                   |
| ``listening`` | ``{"host", "port"}`` of the bound socket, or ``None``                             |
| ``error``     | why the last ``apply`` could not listen, or ``None``                              |

A bind failure is recorded in ``error`` and logged; it does not raise.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import Any

import uvicorn

from pyharness import package_toml

_CFG = package_toml(__file__)["listener"]
KEEP_ALIVE_S: int = _CFG["KEEP_ALIVE_S"]
SHUTDOWN_TIMEOUT_S: int = _CFG["SHUTDOWN_TIMEOUT_S"]


class _Server(uvicorn.Server):
    """``uvicorn.Server`` without signal handlers; the worker owns signals."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[override]
        yield


class Listener:
    def __init__(self, app: Any, logger: logging.Logger) -> None:
        self.app = app
        self.logger = logger
        self.listening: dict[str, Any] | None = None
        self.error: str | None = None
        self._server: _Server | None = None
        self._task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()

    async def _stop(self) -> None:
        server, task = self._server, self._task
        self._server = self._task = self.listening = None
        if server is not None:
            server.should_exit = True
        if task is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(task, SHUTDOWN_TIMEOUT_S + 10)

    async def _start(self, host: str, port: int) -> None:
        sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            raise
        config = uvicorn.Config(
            self.app,
            log_level="warning",
            lifespan="off",
            timeout_keep_alive=KEEP_ALIVE_S,
            timeout_graceful_shutdown=SHUTDOWN_TIMEOUT_S,
        )
        server = _Server(config)
        task = asyncio.get_running_loop().create_task(server.serve(sockets=[sock]))
        while not server.started:
            if task.done():
                raise OSError(f"server exited during startup: {task.exception()!r}")
            await asyncio.sleep(0.02)
        self._server, self._task = server, task
        self.listening = {"host": host, "port": sock.getsockname()[1]}

    async def apply(self, enabled: bool, host: str, port: int) -> None:
        async with self._lock:
            await self._stop()
            self.error = None
            if not enabled:
                return
            try:
                await self._start(host, port)
            except OSError as exc:
                self.error = str(exc)
                self.logger.warning("gateway: cannot listen on %s:%s: %s", host, port, exc)
                return
            self.logger.info("gateway: listening on http://%s:%s/v1", host, self.listening["port"])

    async def close(self) -> None:
        async with self._lock:
            await self._stop()
