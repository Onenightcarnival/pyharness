"""``ctx.subscriptions``: AI subscriptions as model routes and tools — Codex (OpenAI), ChatGPT, Google Antigravity
and Grok (xAI), signed in through their OAuth flows.

| member            | contract                                                                  |
|-------------------|---------------------------------------------------------------------------|
| ``providers``     | ``{id: Provider}``: login, accounts, catalog, usage, chat models, tools    |
| ``sync_routes()`` | publish the discovered models as ``ctx.llm`` routes ``codex`` / ``chatgpt`` / ``antigravity`` / ``grok`` |
| ``sync_tools()``  | register the provider tools that are switched on                          |

| config                 | meaning                                                        |
|------------------------|----------------------------------------------------------------|
| ``codexClientVersion`` | pin the Codex client version sent with catalog requests        |
| ``antigravity``        | ``clientId``, ``clientSecret``, ``baseURL``, ``userAgent``, ``projectId``, ``onboard``, ``maxTokens`` |
| ``models`` / ``chatgpt.models`` / ``grok.models`` | static catalogs (non-empty disables discovery for Codex / Grok) |
| ``stream_idle_timeout`` | seconds without data before a stream fails                   |

Sessions, preferences and catalogs live under ``<profile data>/toolkit/subscriptions/``. Routes under
``/api/subscriptions``: ``status``, ``login``, ``manual``, ``cancel``, ``logout``, ``default``, ``usage``,
``provider-settings`` (GET / PUT), ``model-default``, ``media/{name}``. Model routes are live only: they are rebuilt
from the stored sessions and the last-known catalogs at start and after every login / logout / discovery.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pyharness import Service

from .antigravity import AntigravityProvider
from .chatgpt import ChatGPTProvider
from .codex import CodexProvider
from .grok import GrokProvider
from .providers import DiscoveredModel, Provider
from .store import PROVIDER_TOOLS, PROVIDERS, AuthStore, CatalogCache, MediaStore, ModelDefaults, ProviderSettings

ROUTE_TYPE = "subscription"


class Config(BaseModel):
    codexClientVersion: str | None = None
    antigravity: dict[str, Any] = Field(default_factory=dict)
    models: list[dict[str, Any]] = Field(default_factory=list, description="Static Codex catalog; non-empty disables discovery.")
    chatgpt: dict[str, Any] = Field(default_factory=dict)
    grok: dict[str, Any] = Field(default_factory=dict)
    stream_idle_timeout: float = 300.0


def _thread_id() -> str | None:
    try:
        from langgraph.config import get_config

        return dict(get_config().get("configurable") or {}).get("thread_id")
    except Exception:  # noqa: BLE001
        return None


class SubscriptionsService(Service):
    """Subscriptions: providers, model routes, tools, the AI subscriptions page."""

    key = "subscriptions"
    name = "pyharness-subscriptions"
    inject = ["llm", "tools", "http", "webui"]
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
        base = Path(profile.data) if profile is not None and hasattr(profile, "data") else Path.home() / ".pyharness" / "data"
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
                auth, catalogs, self.http, {"codexClientVersion": cfg.get("codexClientVersion"), "models": cfg.get("models")}
            ),
            "chatgpt": ChatGPTProvider(auth, catalogs, self.http, cfg.get("chatgpt") or {}),
            "antigravity": AntigravityProvider(auth, catalogs, self.http, {"antigravity": cfg.get("antigravity") or {}}),
            "grok": GrokProvider(auth, catalogs, self.http, cfg.get("grok") or {}),
        }
        self._route_disposer = self.ctx.llm.register(ROUTE_TYPE, self._factory)
        self.ctx.http.include_router(self._router(), prefix="/api/subscriptions", tags=["pyharness-subscriptions"])
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
        assert self.settings is not None
        provider = self.providers[provider_id]
        prefs = self.settings.get(provider_id)
        rows = []
        union: dict[str, DiscoveredModel] = {}
        accounts = []
        for key in provider.auth.ordered_keys(provider_id):
            models, available = await provider.models(key, force)
            session = provider.auth.get(provider_id, key) or {}
            accounts.append(
                {
                    "key": key,
                    "label": (prefs.get("accounts", {}).get(key) or {}).get("alias") or provider.account_label(session),
                    "models": [{"id": m.id, "name": m.name} for m in models],
                    **({} if available else {"unavailable": True}),
                }
            )
            for m in models:
                union.setdefault(m.id, m)
        if not accounts:
            for m in provider.fallback_models():
                union.setdefault(m.id, m)
        for m in sorted(union.values(), key=lambda m: (m.priority is None, m.priority or 0)):
            configured = prefs.get("contextWindows", {}).get(m.id)
            default_ctx = m.context_window or provider.default_context
            effective = min(configured or default_ctx, m.max_context_window or 10**12)
            row = {
                "id": m.id,
                "name": m.name,
                "contextWindow": effective,
                "defaultContextWindow": default_ctx,
                "maxContextWindow": m.max_context_window,
                "efforts": m.efforts,
                "inputModalities": m.input_modalities,
                "fastTier": m.fast_tier,
            }
            configured_effort = self.defaults.get(provider_id, m.id) if self.defaults else None
            if configured_effort:
                row["configured"] = configured_effort
            rows.append(row)
        return {
            "provider": provider_id,
            "settings": prefs,
            "models": rows,
            "tools": list(PROVIDER_TOOLS[provider_id]),
            "accounts": accounts,
        }

    async def sync_routes(self, discover: bool = True) -> None:
        """Rebuild the ``codex`` / ``chatgpt`` / ``antigravity`` / ``grok`` routes of ``ctx.llm`` from the catalogs."""
        assert self.settings is not None
        routes = dict(self.ctx.llm.config.model_dump(mode="python")["providers"])
        for provider_id, provider in self.providers.items():
            keys = provider.auth.ordered_keys(provider_id)
            if not keys:
                routes.pop(provider_id, None)
                continue
            cat = await self.catalog(provider_id, force=False) if discover else await self._cached_catalog(provider_id)
            prefs = self.settings.get(provider_id)
            visible = prefs.get("visibleModels")
            models = []
            for m in cat["models"]:
                if visible is not None and m["id"] not in visible:
                    continue
                entry: dict[str, Any] = {
                    "id": m["id"],
                    "name": m["name"],
                    "context_window": m.get("contextWindow"),
                    "input": m.get("inputModalities") or ["text"],
                    "options": {"provider": provider_id},
                }
                if m.get("configured"):
                    entry["options"]["reasoning_effort"] = m["configured"]
                if provider.default_max_tokens:
                    entry["max_tokens"] = provider.default_max_tokens
                models.append(entry)
            routes[provider_id] = {
                "type": ROUTE_TYPE,
                "title": f"{provider.title} ({provider.vendor} subscription)",
                "models": models,
                "options": {"provider": provider_id},
            }
        self.ctx.llm.update(providers=routes)

    async def _cached_catalog(self, provider_id: str) -> dict[str, Any]:
        """The catalog from the last-known models only (no network): used when routes are rebuilt after a change."""
        assert self.settings is not None
        provider = self.providers[provider_id]
        prefs = self.settings.get(provider_id)
        union: dict[str, DiscoveredModel] = {}
        for key in provider.auth.ordered_keys(provider_id):
            cached = provider.catalogs.get(provider_id, key)
            for m in cached["models"] if cached else []:
                union.setdefault(m["id"], DiscoveredModel.from_dict(m))
        if not union:
            for m in provider.fallback_models():
                union.setdefault(m.id, m)
        rows = []
        for m in union.values():
            configured = prefs.get("contextWindows", {}).get(m.id)
            effective = min(configured or m.context_window or provider.default_context, m.max_context_window or 10**12)
            rows.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "contextWindow": effective,
                    "inputModalities": m.input_modalities,
                    "configured": self.defaults.get(provider_id, m.id) if self.defaults else None,
                }
            )
        return {"models": rows}

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
                        version, source = provider.config.get("codexClientVersion") or "0.153.4", "fallback"
                    st["clientVersion"] = {"version": version, "source": source}
            except Exception as exc:  # noqa: BLE001
                st = {"busy": False, "accounts": [], "detail": str(exc)}
            out[provider_id] = st
        return {"providers": out}

    # ------------------------------------------------------------------ routes
    def _router(self) -> APIRouter:
        router = APIRouter()
        service = self

        async def body(request: Request) -> dict[str, Any]:
            raw = await request.body()
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = None
            if not isinstance(data, dict):
                raise HTTPException(400, "invalid JSON body")
            return data

        def provider_of(data: dict[str, Any]) -> Provider:
            pid = str(data.get("provider") or "")
            if pid not in service.providers:
                raise HTTPException(400, f"provider must be one of {', '.join(PROVIDERS)}")
            return service.providers[pid]

        @router.get("/status")
        async def status() -> dict[str, Any]:
            return await service.status()

        @router.post("/login")
        async def login(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            try:
                return await provider.login(data.get("account") or None)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(409, str(exc)) from exc

        @router.post("/manual")
        async def manual(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            try:
                provider.manual(str(data.get("input") or ""))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, str(exc)) from exc
            return {"ok": True}

        @router.post("/cancel")
        async def cancel(request: Request) -> dict[str, Any]:
            provider_of(await body(request)).cancel()
            return {"ok": True}

        @router.post("/logout")
        async def logout(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            await provider.logout(str(data.get("account") or ""))
            await service.sync_routes(discover=False)
            service.sync_tools()
            return {"ok": True}

        @router.post("/default")
        async def set_default(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            if not provider.auth.set_default(provider.id, str(data.get("account") or "")):
                raise HTTPException(404, "unknown account")
            return {"ok": True}

        @router.post("/usage")
        async def usage(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            try:
                return await provider.usage_cached(data.get("account") or None, bool(data.get("force")))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, str(exc)) from exc

        @router.get("/provider-settings")
        async def provider_settings(provider: str, force: bool = False) -> dict[str, Any]:
            if provider not in service.providers:
                raise HTTPException(400, "unknown provider")
            if force:
                service.providers[provider].catalogs.clear(provider)
                if provider == "codex":
                    await service.providers["codex"].client_version(force=True)  # type: ignore[attr-defined]
            cat = await service.catalog(provider, force=force)
            if force:
                await service.sync_routes(discover=False)
            return cat

        @router.put("/provider-settings")
        async def put_provider_settings(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            assert service.settings is not None
            try:
                service.settings.set(provider.id, data.get("settings") or {})
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            await service.sync_routes(discover=False)
            service.sync_tools()
            return {"ok": True}

        @router.post("/model-default")
        async def model_default(request: Request) -> dict[str, Any]:
            data = await body(request)
            provider = provider_of(data)
            assert service.defaults is not None
            model = str(data.get("model") or "")
            effort = data.get("effort") or None
            if effort:
                cat = await service.catalog(provider.id)
                entry = next((m for m in cat["models"] if m["id"] == model), None)
                if entry is None or effort not in [e["id"] for e in entry.get("efforts") or []]:
                    raise HTTPException(400, "the model does not offer that effort")
            service.defaults.set(provider.id, model, effort)
            await service.sync_routes(discover=False)
            return {"ok": True}

        @router.post("/refresh")
        async def refresh_routes() -> dict[str, Any]:
            await service.sync_routes(discover=True)
            service.sync_tools()
            return {"ok": True}

        @router.get("/media/{name}")
        async def media(name: str) -> FileResponse:
            assert service.media is not None
            if not re.fullmatch(r"[\w.-]+\.(png|jpg|webp|gif|mp4)", name) or ".." in name:
                raise HTTPException(404, "not found")
            folder = service.media.videos if name.endswith(".mp4") else service.media.images
            path = folder / name
            if not path.is_file():
                raise HTTPException(404, "not found")
            return FileResponse(
                path, media_type=mimetypes.guess_type(name)[0] or "application/octet-stream", headers={"cache-control": "no-store"}
            )

        return router


__all__ = ["Config", "SubscriptionsService"]
