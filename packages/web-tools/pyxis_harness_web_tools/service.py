from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from pyxis_harness import Service, manage

from .common import USER_AGENT, Pacer
from .config import Config
from .fetch import fetch as fetch_url, fetch_tool
from .search import search as search_web, search_tool

SWITCH = "agent_tools"  # whether the agent has the tools; applied by sync()
LIVE = ("search_provider", "search_base_url", "base_url", "max_results", "max_uses")  # read at each search
ON_RESTART = ("search", "fetch")  # which of the two tools exist


class Settings(BaseModel):
    """Settings of the web tools; a field left out keeps its value."""

    agent_tools: bool | None = None
    search: bool | None = None
    fetch: bool | None = None
    search_provider: str | None = None
    search_base_url: str | None = Field(None, min_length=1)
    base_url: str | None = Field(None, min_length=1)
    max_results: int | None = None
    max_uses: int | None = None
    api_key: str | None = Field(None, description="Stored in the profile's credential file; empty: removed.")


class WebToolsService(Service):
    key = "web"
    name = "pyxis-harness-web-tools"
    inject: ClassVar[list[str]] = ["tools"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.transport: Any = None  # httpx transport override (tests)
        self.pacer = Pacer()
        self._on = False  # the tools are registered
        self._tool_disposers: list[Any] = []

    async def start(self) -> None:
        self.sync()
        self.ctx.on("app/ready", self._mount)

    def _unregister(self) -> None:
        for dispose in self._tool_disposers:
            dispose()
        self._tool_disposers = []

    def sync(self) -> bool:
        """Register ``web_search`` and ``web_fetch`` while ``agent_tools`` is on; returns that state."""
        on = self.config.agent_tools
        if on == self._on:
            return on
        self._on = on
        if on:
            for enabled, tool in ((self.config.search, search_tool), (self.config.fetch, fetch_tool)):
                if enabled:
                    self._tool_disposers.append(
                        self.ctx.tools.register(tool(self), approval=self.config.approval, tags=("web",))
                    )
        else:
            self._unregister()
        return on

    def _mount(self) -> None:
        """With an HTTP server: the settings routes; with the Web UI: the settings section."""
        http = self.ctx.get("http", None)
        if http is None or not hasattr(http, "include_router"):
            return
        router = APIRouter()

        @router.get("/settings")
        async def get_settings() -> dict[str, Any]:
            return self.settings()

        @router.put("/settings")
        async def put_settings(body: Settings) -> dict[str, Any]:
            try:
                return await self.save(body.model_dump(exclude_unset=True))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None

        http.include_router(router, prefix="/api/web-tools", tags=[self.name])
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        """The tools' settings and the state of the search key (never its value)."""
        key = self.status()["search"]
        return {
            **{name: getattr(self.config, name) for name in (SWITCH, *ON_RESTART, *LIVE)},
            "key": {name: key.get(name) for name in ("reference", "configured", "source")},
        }

    async def save(self, fields: dict[str, Any]) -> dict[str, Any]:
        """
        Change settings and persist them in the profile patch; the key goes to the profile's credential file.

        | fields                       | take effect                                    |
        |------------------------------|------------------------------------------------|
        | ``agent_tools``              | at once: ``sync()``                            |
        | provider, base URLs, counts  | at once: the next search                       |
        | ``api_key``                  | at once                                        |
        | ``search``, ``fetch``        | in the next generation; a restart is requested |
        """
        profile = self.ctx.get("profile", None)
        key = fields.pop("api_key", None)
        changed = {k: v for k, v in fields.items() if v is not None and getattr(self.config, k) != v}
        try:
            config = Config.model_validate({**self.config.model_dump(), **changed})
        except ValidationError as exc:
            raise ValueError("; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())) from None
        if key is not None:
            if profile is None or not hasattr(profile, "credentials"):
                raise ValueError("no profile: the key is read from the environment")
            if key.strip():
                profile.credentials.set(self.config.api_key_env, key.strip())
            else:
                profile.credentials.delete(self.config.api_key_env)
        if changed and profile is not None:
            await manage.set_entry_config(profile, "web-tools", changed, merge=True, preflight=False)
        for name in (SWITCH, *LIVE):
            setattr(self.config, name, getattr(config, name))
        self.sync()
        restart = any(name in ON_RESTART for name in changed)
        if restart:
            self.ctx.lifecycle.request_restart("web tools settings")
        saved = self.settings()
        return {
            "application": "restart" if restart else "applied",
            **saved,
            **{k: changed[k] for k in changed if k in ON_RESTART},
        }

    # ------------------------------------------------------------------ credentials
    def api_key(self) -> str | None:
        ref = self.config.api_key_env
        profile = self.ctx.get("profile", None)
        if profile is not None and hasattr(profile, "credentials"):
            return profile.credentials.get(ref)
        return os.environ.get(ref) or None

    def status(self) -> dict[str, Any]:
        ref = self.config.api_key_env
        legacy = self.config.search_provider == "deepseek-legacy"
        profile = self.ctx.get("profile", None)
        described = (
            profile.credentials.describe(ref)
            if profile is not None and hasattr(profile, "credentials")
            else {
                "reference": ref,
                "configured": bool(os.environ.get(ref)),
                "source": "env" if os.environ.get(ref) else None,
            }
        )
        return {
            "search": {
                **described,
                "enabled": self._on and self.config.search,
                "provider": self.config.search_provider,
                "model": self.config.model if legacy else None,
                "base_url": self.config.base_url if legacy else self.config.search_base_url,
            },
            "fetch": {"enabled": self._on and self.config.fetch},
        }

    def client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"user-agent": USER_AGENT},
            transport=self.transport,
            trust_env=False,
        )

    # ------------------------------------------------------------------ search
    async def search(self, query: str) -> dict[str, Any]:
        """``{"answer", "sources", "truncated"}``; raises ``RuntimeError`` with a user-facing message on failure."""
        return await search_web(self, query)

    # ------------------------------------------------------------------ fetch
    async def fetch(self, url: str, max_chars: int | None = None) -> dict[str, Any]:
        """``{"url", "status", "content_type", "title", "text", "truncated"}``; raises ``RuntimeError`` on failure."""
        return await fetch_url(self, url, max_chars)
