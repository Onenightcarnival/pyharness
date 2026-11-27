from __future__ import annotations

from typing import Any, Protocol

from .providers import DiscoveredModel, Provider
from .store import PROVIDER_TOOLS, ModelDefaults, ProviderSettings


class Host(Protocol):
    """The service, as the catalog functions use it."""

    ctx: Any
    providers: dict[str, Provider]
    settings: ProviderSettings | None
    defaults: ModelDefaults | None


ROUTE_TYPE = "subscription"


async def provider_catalog(service: Host, provider_id: str, force: bool = False) -> dict[str, Any]:
    assert service.settings is not None
    provider = service.providers[provider_id]
    prefs = service.settings.get(provider_id)
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
        configured_effort = service.defaults.get(provider_id, m.id) if service.defaults else None
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


async def cached_catalog(service: Host, provider_id: str) -> dict[str, Any]:
    """The catalog from the last-known models only (no network): used when routes are rebuilt after a change."""
    assert service.settings is not None
    provider = service.providers[provider_id]
    prefs = service.settings.get(provider_id)
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
                "configured": service.defaults.get(provider_id, m.id) if service.defaults else None,
            }
        )
    return {"models": rows}


async def rebuild_routes(service: Host, discover: bool = True) -> None:
    """
    Publish the ``codex`` / ``chatgpt`` / ``grok`` routes to ``ctx.llm`` from the catalogs: one
    per signed-in provider. A configured route of type ``subscription`` is removed from the live configuration.
    """
    assert service.settings is not None
    llm = service.ctx.llm
    configured = llm.config.model_dump(mode="python")["providers"]
    kept = {route: cfg for route, cfg in configured.items() if cfg.get("type") != ROUTE_TYPE}
    if len(kept) != len(configured):
        llm.update(providers=kept)
    routes: dict[str, Any] = {}
    for provider_id, provider in service.providers.items():
        keys = provider.auth.ordered_keys(provider_id)
        if not keys:
            continue
        cat = (
            await provider_catalog(service, provider_id, force=False)
            if discover
            else await cached_catalog(service, provider_id)
        )
        prefs = service.settings.get(provider_id)
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
    llm.publish(routes)
