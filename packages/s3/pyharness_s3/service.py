from __future__ import annotations

import asyncio
import warnings
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from pyharness import Service, package_prompts

from . import engine as eng
from .engine import Bucket, S3Error
from .routes import build_router
from .store import ProfileStore
from .tools import build_tools

PROMPT_ORDER = 152

PROMPTS = package_prompts(__file__)
GUIDANCE: str = PROMPTS["service"]["GUIDANCE"]


class Config(BaseModel):
    path: str | None = Field(None, description="Profiles file; default <profile data>/toolkit/s3.json.")
    approval: bool | dict[str, Any] = Field(False, description="Approval gate for s3_delete.")


class S3Service(Service):
    """S3 browser: profiles, clients, tools, routes and the S3 page module."""

    key = "s3"
    name = "pyharness-s3"
    inject: ClassVar[list[str]] = ["tools", "prompt", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.store: ProfileStore | None = None
        self.make_client = eng.make_client
        self._clients: dict[str, tuple[Any, int]] = {}
        self._tool_disposers: list[Any] = []
        self._prompt_disposer: Any = None

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
        return base / "toolkit" / "s3.json"

    async def start(self) -> None:
        profile = self.ctx.get("profile", None)
        credentials = (
            profile.credentials if profile is not None and hasattr(profile, "credentials") else _MemoryCredentials()
        )
        self.store = ProfileStore(self._path(), credentials)
        self.store.subscribe(self._on_store_change)
        self.ctx.http.include_router(build_router(self), prefix="/api", tags=["pyharness-s3"])
        self.sync()
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))

    async def stop(self) -> None:
        self._unregister()
        self._clients.clear()

    def _on_store_change(self) -> None:
        self._clients.clear()
        self.sync()

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
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tools = build_tools(self)
            self._tool_disposers = [
                self.ctx.tools.register(
                    t, approval=self.config.approval if t.name == "s3_delete" else False, tags=("s3",)
                )
                for t in tools
            ]
            self._prompt_disposer = self.ctx.prompt.add("plugin:s3", GUIDANCE, order=PROMPT_ORDER)
        elif not on and self._tool_disposers:
            self._unregister()
        return bool(self._tool_disposers)

    # ------------------------------------------------------------------ buckets
    def profile(self, id_or_name: str) -> dict[str, Any]:
        assert self.store is not None
        p = self.store.find(id_or_name)
        if p is None:
            raise S3Error(f"unknown bucket profile '{id_or_name}' (configure it in the S3 panel first)")
        return p

    def bucket(self, profile: dict[str, Any]) -> Bucket:
        assert self.store is not None
        entry = self._clients.get(profile["id"])
        if entry is None or entry[1] != profile.get("updatedAt"):
            client = self.make_client(profile, self.store.secret(profile["id"]))
            self._clients[profile["id"]] = (client, int(profile.get("updatedAt") or 0))
            entry = self._clients[profile["id"]]
        return Bucket(entry[0], profile)

    async def run(self, id_or_name: str, fn: Any) -> Any:
        profile = self.profile(id_or_name)
        return await asyncio.to_thread(lambda: fn(self.bucket(profile)))


class _MemoryCredentials:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, ref: str | None) -> str | None:
        return self.data.get(ref or "")

    def set(self, ref: str, value: str) -> None:
        self.data[ref] = value

    def delete(self, ref: str) -> bool:
        return self.data.pop(ref, None) is not None
