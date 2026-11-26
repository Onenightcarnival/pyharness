from __future__ import annotations

import os
from typing import Any, ClassVar

import httpx

from pyxis_harness import Service

from .common import USER_AGENT, Pacer
from .config import Config
from .fetch import fetch as fetch_url, fetch_tool
from .search import search as search_web, search_tool


class WebToolsService(Service):
    key = "web"
    name = "pyxis-harness-web-tools"
    inject: ClassVar[list[str]] = ["tools"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.transport: Any = None  # httpx transport override (tests)
        self.pacer = Pacer()

    async def start(self) -> None:
        if self.config.search:
            self.ctx.tools.register(search_tool(self), approval=self.config.approval, tags=("web",))
        if self.config.fetch:
            self.ctx.tools.register(fetch_tool(self), approval=self.config.approval, tags=("web",))

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
                "enabled": self.config.search,
                "provider": self.config.search_provider,
                "model": self.config.model if legacy else None,
                "base_url": self.config.base_url if legacy else self.config.search_base_url,
            },
            "fetch": {"enabled": self.config.fetch},
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
