"""``ctx.http``: the FastAPI application and its uvicorn server.

| member             | contract                                               |
|--------------------|--------------------------------------------------------|
| ``include_router`` | router under a prefix, owned by the calling plugin     |
| ``mount``          | sub-application at a path, owned by the calling plugin |
| ``routes``         | flattened route list                                   |

| event            | server                                                                |
|------------------|-----------------------------------------------------------------------|
| ``app/serve``    | socket bound, then uvicorn started; a bind error fails the boot       |
| ``app/stopping`` | stops accepting requests; in-flight requests get ``shutdown_timeout`` |
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from typing import Any, Callable

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from pyharness import Service


class HttpConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    serve: bool = Field(True, description="Bind the server on app/serve.")
    log_level: str = "warning"
    title: str = "pyharness"
    shutdown_timeout: int = Field(5, description="Seconds for in-flight requests when stopping.")


class _Server:
    """``uvicorn.Server`` without signal handlers; the worker owns signals."""

    def __new__(cls, config: Any) -> Any:
        import uvicorn

        class Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):  # type: ignore[override]
                yield

        return Server(config)


class HttpService(Service):
    """FastAPI root application and uvicorn server."""

    key = "http"
    name = "pyharness-http"
    Config = HttpConfig

    def __init__(self, ctx: Any, config: HttpConfig) -> None:
        super().__init__(ctx, config)
        self.app = FastAPI(title=config.title)
        self._contributions: list[dict[str, Any]] = []
        self._server: Any = None
        self._task: asyncio.Task[Any] | None = None
        self.bound_port: int | None = None

    async def start(self) -> None:
        self.ctx.on("app/serve", self._serve)
        self.ctx.on("app/stopping", self.stop)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(self._task, 15)
            self._task = None

    # ------------------------------------------------------------------ contributions
    def include_router(self, router: APIRouter, prefix: str = "", **kwargs: Any) -> Callable[[], Any]:
        """Include ``router`` under ``prefix``; returns the disposer."""
        before = len(self.app.router.routes)
        self.app.include_router(router, prefix=prefix, **kwargs)
        added = self.app.router.routes[before:]
        self._contributions.append({"kind": "router", "prefix": prefix, "owner": self.caller.entry_id, "routes": len(added)})
        return self.caller.on_dispose(lambda: self._remove(added))

    def mount(self, path: str, app: Any, name: str | None = None) -> Callable[[], Any]:
        """Mount an ASGI application at ``path``; returns the disposer."""
        before = len(self.app.router.routes)
        self.app.mount(path, app, name=name)
        added = self.app.router.routes[before:]
        self._contributions.append({"kind": "mount", "prefix": path, "owner": self.caller.entry_id, "routes": len(added)})
        return self.caller.on_dispose(lambda: self._remove(added))

    def _remove(self, routes: list[Any]) -> None:
        for route in routes:
            with contextlib.suppress(ValueError):
                self.app.router.routes.remove(route)
        self.app.openapi_schema = None

    def routes(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def walk(routes: list[Any], prefix: str) -> None:
            for route in routes:
                included = getattr(route, "original_router", None)
                if included is not None:  # FastAPI included-router wrapper
                    context = getattr(route, "include_context", None)
                    walk(included.routes, prefix + (getattr(context, "prefix", "") or ""))
                    continue
                out.append({"path": prefix + getattr(route, "path", "?"), "methods": sorted(getattr(route, "methods", None) or [])})

        walk(self.app.router.routes, "")
        return out

    def contributions(self) -> list[dict[str, Any]]:
        return list(self._contributions)

    # ------------------------------------------------------------------ server
    async def _serve(self) -> None:
        if not self.config.serve:
            return
        import uvicorn

        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level,
            lifespan="off",
            timeout_graceful_shutdown=self.config.shutdown_timeout,
        )
        family = socket.AF_INET6 if ":" in self.config.host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.config.host, self.config.port))
        except OSError as exc:
            sock.close()
            raise RuntimeError(f"cannot bind HTTP server to {self.config.host}:{self.config.port}: {exc}") from exc
        self.bound_port = sock.getsockname()[1]
        server = _Server(config)
        self._server = server
        self._task = asyncio.get_running_loop().create_task(server.serve(sockets=[sock]))
        while not server.started:
            if self._task.done():
                exc = self._task.exception() if not self._task.cancelled() else None
                raise RuntimeError(f"HTTP server failed to start on {self.config.host}:{self.config.port}: {exc!r}")
            await asyncio.sleep(0.05)
        self.ctx.logger.info("serving on http://%s:%s", self.config.host, self.bound_port)


__all__ = ["HttpConfig", "HttpService"]
