"""
``SubscriptionsService``: the providers, their model routes and tools, the status of the AI subscriptions page.

| member                 | contract                                                                        |
|------------------------|---------------------------------------------------------------------------------|
| ``providers``          | ``{id: Provider}`` built at start from the stores under                         |
|                        | ``<profile data>/toolkit/subscriptions/`` (``AuthStore``, ``CatalogCache``)      |
| ``sync_routes()``      | :func:`pyharness_subscriptions.catalog.rebuild_routes`                          |
| ``sync_tools()``       | register the tools of every signed-in provider that has tools; drop them at logout |
| ``catalog()``          | :func:`pyharness_subscriptions.catalog.provider_catalog`                        |
| ``status()``           | ``{"providers": {id: status}}``; the Codex entry carries ``clientVersion``      |
| ``tool_enabled()``     | the stored preference of one provider tool, optionally as of the session's creation |
| ``model_default()``    | the stored default reasoning effort of one model                                |
| ``media_url()``        | the ``/api/subscriptions/media/{name}`` URL of a stored media file              |
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx
from langgraph.config import get_config
from pydantic import BaseModel, Field

from pyharness import Service

from .antigravity import AntigravityProvider
from .catalog import ROUTE_TYPE, provider_catalog, rebuild_routes
from .chatgpt import ChatGPTProvider
from .codex import CLIENT_VERSION_FLOOR, CodexProvider
from .grok import GrokProvider
from .providers import Provider
from .routes import build_router
from .store import PROVIDER_TOOLS, AuthStore, CatalogCache, MediaStore, ModelDefaults, ProviderSettings


class Config(BaseModel):
    codexClientVersion: str | None = None
    antigravity: dict[str, Any] = Field(default_factory=dict)
    models: list[dict[str, Any]] = Field(
        default_factory=list, description="Static Codex catalog; non-empty disables discovery."
    )
    chatgpt: dict[str, Any] = Field(default_factory=dict)
    grok: dict[str, Any] = Field(default_factory=dict)
    stream_idle_timeout: float = 300.0


def _thread_id() -> str | None:
    try:
        return dict(get_config().get("configurable") or {}).get("thread_id")
    except Exception:  # noqa: BLE001
        return None


class SubscriptionsService(Service):
    """Subscriptions: providers, model routes, tools, the AI subscriptions page."""

    key = "subscriptions"
    name = "pyharness-subscriptions"
    inject: ClassVar[list[str]] = ["llm", "tools", "http", "webui"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.providers: dict[str, Provider] = {}
        self.http = httpx.AsyncClient(follow_redirects=False)
        self._tool_disposers: dict[str, Any] = {}
        self._route_disposer: Any = None
        self.media: MediaStore | None = None
        self.settings: ProviderSettings | None = None
        self.defaults: ModelDefaults | None = None
        self.session_created: dict[str, int] = {}

    # ------------------------------------------------------------------ lifecycle
    def _data(self) -> Path:
        profile = self.ctx.get("profile", None)
        base = (
            Path(profile.data)
            if profile is not None and hasattr(profile, "data")
            else Path.home() / ".pyharness" / "data"
        )
        return base / "toolkit" / "subscriptions"

    async def start(self) -> None:
        base = self._data()
        base.mkdir(parents=True, exist_ok=True)
        auth, catalogs = AuthStore(base), CatalogCache(base)
        self.settings = ProviderSettings(base)
        self.defaults = ModelDefaults(base)
        self.media = MediaStore(base)
        cfg = self.config.model_dump()
        self.providers = {
            "codex": CodexProvider(
                auth,
                catalogs,
                self.http,
                {"codexClientVersion": cfg.get("codexClientVersion"), "models": cfg.get("models")},
            ),
            "chatgpt": ChatGPTProvider(auth, catalogs, self.http, cfg.get("chatgpt") or {}),
            "antigravity": AntigravityProvider(
                auth, catalogs, self.http, {"antigravity": cfg.get("antigravity") or {}}
            ),
            "grok": GrokProvider(auth, catalogs, self.http, cfg.get("grok") or {}),
        }
        self._route_disposer = self.ctx.llm.register(ROUTE_TYPE, self._factory)
        self.ctx.http.include_router(build_router(self), prefix="/api/subscriptions", tags=["pyharness-subscriptions"])
        self.ctx.webui.register_client(Path(__file__).with_name("client.js"))
        self.ctx.on("agent/turn-start", self._on_turn_start)
        await self.sync_routes(discover=False)
        self.sync_tools()
        asyncio.create_task(self._background_discovery())

    async def stop(self) -> None:
        for d in list(self._tool_disposers.values()):
            d()
        self._tool_disposers.clear()
        await self.http.aclose()

    async def _background_discovery(self) -> None:
        await asyncio.sleep(1)
        try:
            await self.sync_routes(discover=True)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning("subscriptions discovery failed: %s", exc)

    async def _on_turn_start(self, turn: Any) -> None:
        self.session_created.setdefault(turn.session_id, int(time.time() * 1000))

    # ------------------------------------------------------------------ helpers for tools
    def current_session_id(self) -> str | None:
        return _thread_id()

    def tool_enabled(self, provider: str, tool: str, at_creation: bool = False) -> bool:
        assert self.settings is not None
        at = self.session_created.get(self.current_session_id() or "") if at_creation else None
        return self.settings.tool_enabled(provider, tool, at)

    def model_default(self, provider: str, model: str) -> str | None:
        assert self.defaults is not None
        return self.defaults.get(provider, model)

    def media_url(self, path: Path) -> str:
        return f"/api/subscriptions/media/{path.name}"

    # ------------------------------------------------------------------ model routes
    def _factory(self, model: str, **options: Any) -> Any:
        provider_id = options.get("provider")
        provider = self.providers.get(str(provider_id or ""))
        if provider is None:
            raise RuntimeError(f"unknown subscription provider {provider_id!r}")
        account = options.get("account")
        effort = options.get("reasoning_effort") or (self.defaults.get(provider_id, model) if self.defaults else None)
        return provider.chat_model(
            model,
            account,
            reasoning_effort=effort,
            max_tokens=options.get("max_tokens"),
            temperature=options.get("temperature"),
            fast_tier=options.get("fast_tier"),
        )

    async def catalog(self, provider_id: str, force: bool = False) -> dict[str, Any]:
        return await provider_catalog(self, provider_id, force)

    async def sync_routes(self, discover: bool = True) -> None:
        """Rebuild the ``codex`` / ``chatgpt`` / ``antigravity`` / ``grok`` routes of ``ctx.llm`` from the catalogs."""
        await rebuild_routes(self, discover)

    # ------------------------------------------------------------------ tools
    def sync_tools(self) -> None:
        assert self.settings is not None
        for provider_id, provider in self.providers.items():
            wanted = bool(provider.auth.ordered_keys(provider_id)) and bool(PROVIDER_TOOLS[provider_id])
            have = provider_id in self._tool_disposers
            if wanted and not have:
                disposers = []
                for t in provider.tools(self):
                    try:
                        disposers.append(self.ctx.tools.register(t, tags=("subscriptions", provider_id)))
                    except Exception as exc:  # noqa: BLE001
                        self.ctx.logger.warning("subscriptions tool %s not registered: %s", t.name, exc)
                self._tool_disposers[provider_id] = lambda ds=disposers: [d() for d in ds]
            elif not wanted and have:
                self._tool_disposers.pop(provider_id)()

    # ------------------------------------------------------------------ status
    async def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for provider_id, provider in self.providers.items():
            try:
                st = provider.status()
                if isinstance(provider, CodexProvider):
                    try:
                        version, source = await asyncio.wait_for(provider.client_version(), 1.0)
                    except Exception:  # noqa: BLE001 - the npm lookup is slow or offline: report the floor
                        version, source = provider.config.get("codexClientVersion") or CLIENT_VERSION_FLOOR, "fallback"
                    st["clientVersion"] = {"version": version, "source": source}
            except Exception as exc:  # noqa: BLE001
                st = {"busy": False, "accounts": [], "detail": str(exc)}
            out[provider_id] = st
        return {"providers": out}
