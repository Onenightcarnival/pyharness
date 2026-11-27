from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from pyxis_harness import Service

from .catalog import ROUTE_TYPE, provider_catalog, rebuild_routes
from .chatgpt import ChatGPTProvider
from .common import STREAM_IDLE_TIMEOUT
from .providers import Provider
from .routes import build_router
from .store import AuthStore, CatalogCache, ModelDefaults, ProviderSettings


class Config(BaseModel):
    chatgpt: dict[str, Any] = Field(default_factory=dict)
    stream_idle_timeout: float = Field(
        STREAM_IDLE_TIMEOUT, gt=0, description="Seconds without stream data before a chat model fails with TIMEOUT."
    )


class SubscriptionsService(Service):
    """Subscriptions: providers, model routes, the AI subscriptions page."""

    key = "subscriptions"
    name = "pyxis-harness-subscriptions"
    inject: ClassVar[list[str]] = ["llm", "http", "webui"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.providers: dict[str, Provider] = {}
        self.http = httpx.AsyncClient(follow_redirects=False, trust_env=False)
        self._route_disposer: Any = None
        self.settings: ProviderSettings | None = None
        self.defaults: ModelDefaults | None = None
        self._discovery: asyncio.Task[None] | None = None

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
        cfg = self.config.model_dump()
        self.providers = {"chatgpt": ChatGPTProvider(auth, catalogs, self.http, cfg.get("chatgpt") or {})}
        for provider in self.providers.values():
            provider.stream_idle_timeout = self.config.stream_idle_timeout
        self._route_disposer = self.ctx.llm.register(ROUTE_TYPE, self._factory)
        self.ctx.http.include_router(
            build_router(self), prefix="/api/subscriptions", tags=["pyxis-harness-subscriptions"]
        )
        self.ctx.webui.register_client(Path(__file__).with_name("client.js"))
        await self.sync_routes(discover=False)
        self._discovery = asyncio.create_task(self._background_discovery())

    async def stop(self) -> None:
        if self._discovery is not None:
            self._discovery.cancel()
        await self.http.aclose()

    async def _background_discovery(self) -> None:
        await asyncio.sleep(1)
        try:
            await self.sync_routes(discover=True)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning("subscriptions discovery failed: %s", exc)

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
        )

    async def catalog(self, provider_id: str, force: bool = False) -> dict[str, Any]:
        return await provider_catalog(self, provider_id, force)

    async def sync_routes(self, discover: bool = True) -> None:
        """Rebuild the ``chatgpt`` route of ``ctx.llm`` from the catalogs."""
        await rebuild_routes(self, discover)

    # ------------------------------------------------------------------ status
    async def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for provider_id, provider in self.providers.items():
            try:
                st = provider.status()
            except Exception as exc:  # noqa: BLE001
                st = {"busy": False, "accounts": [], "detail": str(exc)}
            out[provider_id] = st
        return {"providers": out}
