from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, ClassVar

from pyharness import Service, package_prompts

from .config import Config
from .engine import HttpEngine
from .routes import build_router
from .store import HistoryStore, RequestStore, TargetStore
from .tools import build_tools

GUIDANCE: str = package_prompts(__file__)["service"]["GUIDANCE"]
PROMPT_ORDER = 153


class HttpClientService(Service):
    """HTTP API request tool: targets, saved requests, history, the ``http_*`` tools and the HTTP page."""

    key = "httpClient"
    name = "pyharness-http-client"
    inject: ClassVar[list[str]] = ["tools", "prompt", "http", "webui"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        base = self._data()
        self.store = TargetStore(base / "targets.json")
        self.requests = RequestStore(base / "requests.json")
        self.history = HistoryStore(base / "history.jsonl", lambda: self.store.settings()["historyLimit"])
        self.engine = HttpEngine(self.store, self.history)
        self._tool_disposers: list[Any] = []
        self._prompt_disposer: Any = None

    def _data(self) -> Path:
        if self.config.data_dir:
            return Path(self.config.data_dir).expanduser()
        profile = self.ctx.get("profile", None)
        base = (
            Path(profile.data)
            if profile is not None and hasattr(profile, "data")
            else Path.home() / ".pyharness" / "data"
        )
        return base / "toolkit" / "http-client"

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.ctx.http.include_router(build_router(self), prefix="/api/http-client", tags=["pyharness-http-client"])
        self.ctx.webui.register_client(Path(__file__).with_name("client.js"))
        self.sync()

    async def stop(self) -> None:
        self._unregister()
        await self.engine.aclose()

    def _unregister(self) -> None:
        for dispose in self._tool_disposers:
            dispose()
        self._tool_disposers = []
        if self._prompt_disposer is not None:
            self._prompt_disposer()
            self._prompt_disposer = None

    def sync(self) -> bool:
        """Register the ``http_*`` tools and the prompt section while ``agentTools`` is on; returns that state."""
        on = bool(self.store.settings()["agentTools"])
        if on and not self._tool_disposers:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tools = build_tools(self)
            self._tool_disposers = [self.ctx.tools.register(t, tags=("http-client",)) for t in tools]
            self._prompt_disposer = self.ctx.prompt.add("plugin:http-client", GUIDANCE, order=PROMPT_ORDER)
        elif not on and self._tool_disposers:
            self._unregister()
        return bool(self._tool_disposers)
