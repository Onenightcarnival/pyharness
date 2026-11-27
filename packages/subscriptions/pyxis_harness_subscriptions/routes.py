from __future__ import annotations

import json
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from .providers import Provider
from .store import PROVIDERS, ModelDefaults, ProviderSettings


class Host(Protocol):
    """The service, as the routes use it."""

    providers: dict[str, Provider]
    settings: ProviderSettings | None
    defaults: ModelDefaults | None

    async def status(self) -> dict[str, Any]: ...
    async def catalog(self, provider_id: str, force: bool = False) -> dict[str, Any]: ...
    async def sync_routes(self, discover: bool = True) -> None: ...


def build_router(service: Host) -> APIRouter:
    router = APIRouter()

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
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manual")
    async def manual(request: Request) -> dict[str, Any]:
        data = await body(request)
        provider = provider_of(data)
        try:
            provider.manual(str(data.get("input") or ""))
        except Exception as exc:
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
        except Exception as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.get("/provider-settings")
    async def provider_settings(provider: str, force: bool = False) -> dict[str, Any]:
        if provider not in service.providers:
            raise HTTPException(400, "unknown provider")
        if force:
            service.providers[provider].catalogs.clear(provider)
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
        return {"ok": True}

    return router
