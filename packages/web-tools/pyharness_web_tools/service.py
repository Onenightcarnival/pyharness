"""``WebToolsService``: the ``web`` service; registers ``web_search`` and ``web_fetch`` and holds the credential.

| member         | contract                                                                             |
|----------------|--------------------------------------------------------------------------------------|
| ``api_key()``  | the ``api_key_env`` credential: the profile's credential store, else the environment |
| ``status()``   | ``{"search": {credential description, enabled, model, base_url}, "fetch": {enabled}}`` |
| ``search()``   | :func:`pyharness_web_tools.search.search`                                            |
| ``fetch()``    | :func:`pyharness_web_tools.fetch.fetch`                                              |
| ``transport``  | httpx transport override for every request (tests)                                   |

| config             | default                                     | meaning                                        |
|--------------------|---------------------------------------------|------------------------------------------------|
| ``search``         | ``True``                                    | register ``web_search``                        |
| ``fetch``          | ``True``                                    | register ``web_fetch``                         |
| ``api_key_env``    | ``DEEPSEEK_API_KEY``                        | credential reference of the search key         |
| ``base_url``       | ``https://api.deepseek.com/anthropic/v1``   | Anthropic-format Messages endpoint             |
| ``model``          | ``deepseek-v4-flash``                       | search model                                   |
| ``max_uses``       | 5 (1–20)                                    | searches DeepSeek may run per query            |
| ``max_results``    | 8 (1–50)                                    | sources returned                               |
| ``max_tokens``     | 4096 (≥ 256)                                | answer budget                                  |
| ``search_timeout`` | 90.0                                        | seconds                                        |
| ``fetch_timeout``  | 30.0                                        | seconds                                        |
| ``fetch_max_chars``| 20000 (≥ 1000)                              | text cap of ``web_fetch``                      |
| ``fetch_max_bytes``| 5000000 (≥ 10000)                           | body read cap of ``web_fetch``                 |
| ``approval``       | ``False``                                   | approval gate passed to ``ctx.tools.register`` |
"""

from __future__ import annotations

import os
from typing import Any, ClassVar

import httpx

from pyharness import Service

from .common import USER_AGENT
from .config import Config
from .fetch import fetch as fetch_url, fetch_tool
from .search import search as search_web, search_tool


class WebToolsService(Service):
    key = "web"
    name = "pyharness-web-tools"
    inject: ClassVar[list[str]] = ["tools"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.transport: Any = None  # httpx transport override (tests)

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
                "model": self.config.model,
                "base_url": self.config.base_url,
            },
            "fetch": {"enabled": self.config.fetch},
        }

    def client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"user-agent": USER_AGENT}, transport=self.transport
        )

    # ------------------------------------------------------------------ search
    async def search(self, query: str) -> dict[str, Any]:
        """``{"answer", "sources", "truncated"}``; raises ``RuntimeError`` with a user-facing message on failure."""
        return await search_web(self, query)

    # ------------------------------------------------------------------ fetch
    async def fetch(self, url: str, max_chars: int | None = None) -> dict[str, Any]:
        """``{"url", "status", "content_type", "title", "text", "truncated"}``; raises ``RuntimeError`` on failure."""
        return await fetch_url(self, url, max_chars)
