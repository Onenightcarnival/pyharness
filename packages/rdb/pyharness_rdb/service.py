from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from pyharness import Service, package_prompts

from .driver import Driver, EngineError
from .pool import Pool
from .routes import build_router
from .store import ProfileStore
from .tools import connections_tool, execute_tool, explain_tool, query_tool, schema_tool

PROMPT_ORDER = 153

PROMPTS = package_prompts(__file__)
GUIDANCE: str = PROMPTS["service"]["GUIDANCE"]


class Config(BaseModel):
    path: str | None = Field(None, description="Profiles file; default <profile data>/toolkit/rdb.json.")
    approval: bool | dict[str, Any] = Field(False, description="Approval gate for db_execute.")
    idle_close_seconds: float = 600.0


class RdbService(Service):
    """Database workbench: profiles, connections, tools, routes and the Database page module."""

    key = "rdb"
    name = "pyharness-rdb"
    inject: ClassVar[list[str]] = ["tools", "prompt", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.store: ProfileStore | None = None
        self.pool = Pool(idle_close_s=config.idle_close_seconds)
        self._tool_disposers: list[Any] = []
        self._prompt_disposer: Any = None
        self._sweeper: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------ lifecycle
    def _path(self) -> Path:
        if self.config.path:
            return Path(self.config.path).expanduser()
        profile = self.ctx.get("profile", None)
        base = (
            Path(profile.data)
            if profile is not None and hasattr(profile, "data")
            else Path.home() / ".pyharness" / "data"
        )
        return base / "toolkit" / "rdb.json"

    async def start(self) -> None:
        profile = self.ctx.get("profile", None)
        credentials = (
            profile.credentials if profile is not None and hasattr(profile, "credentials") else _MemoryCredentials()
        )
        self.store = ProfileStore(self._path(), credentials)
        self.store.subscribe(self.sync)
        self.ctx.http.include_router(build_router(self), prefix="/api", tags=["pyharness-rdb"])
        self.sync()
        self._sweeper = asyncio.create_task(self._sweep())
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        self._unregister()
        await asyncio.to_thread(self.pool.close_all)

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(self.pool.sweep)

    def _unregister(self) -> None:
        for d in self._tool_disposers:
            d()
        self._tool_disposers = []
        if self._prompt_disposer is not None:
            self._prompt_disposer()
            self._prompt_disposer = None

    def sync(self) -> bool:
        assert self.store is not None
        on = bool(self.store.settings().get("agentTools"))
        if on and not self._tool_disposers:
            self._tool_disposers = [
                self.ctx.tools.register(connections_tool(self), tags=("db",)),
                self.ctx.tools.register(schema_tool(self), tags=("db",)),
                self.ctx.tools.register(query_tool(self), tags=("db",)),
                self.ctx.tools.register(explain_tool(self), tags=("db",)),
                self.ctx.tools.register(execute_tool(self), approval=self.config.approval, tags=("db", "db-write")),
            ]
            self._prompt_disposer = self.ctx.prompt.add("plugin:rdb", GUIDANCE, order=PROMPT_ORDER)
        elif not on and self._tool_disposers:
            self._unregister()
        return bool(self._tool_disposers)

    # ------------------------------------------------------------------ connections
    def profile(self, id_or_name: str) -> dict[str, Any]:
        assert self.store is not None
        p = self.store.find(id_or_name)
        if p is None:
            raise EngineError(f"unknown connection '{id_or_name}' (configure it in the database panel first)")
        return p

    def driver(self, profile: dict[str, Any]) -> Driver:
        assert self.store is not None
        return self.pool.get(profile, self.store.password(profile["id"]))

    async def run(self, id_or_name: str, fn: Any) -> Any:
        """``fn(driver)`` in a worker thread for the connection of a profile."""
        profile = self.profile(id_or_name)
        return await asyncio.to_thread(lambda: fn(self.driver(profile)))

    async def test(self, pid: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            profile = self.profile(pid)
            driver = await asyncio.to_thread(lambda: self.driver(profile))
            version = await asyncio.to_thread(driver.server_version)
            out: dict[str, Any] = {
                "ok": True,
                "latencyMs": int((time.perf_counter() - started) * 1000),
                "serverVersion": version,
            }
            if driver.node:
                out["node"] = driver.node
            return out
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "latencyMs": int((time.perf_counter() - started) * 1000), "error": str(exc).strip()}


class _MemoryCredentials:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, ref: str | None) -> str | None:
        return self.data.get(ref or "")

    def set(self, ref: str, value: str) -> None:
        self.data[ref] = value

    def delete(self, ref: str) -> bool:
        return self.data.pop(ref, None) is not None
