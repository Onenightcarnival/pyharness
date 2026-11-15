from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from pyharness import manage
from pyharness.credentials import reference_for
from pyharness_llm import PROTOCOLS, LLMConfig, LLMConfigError, ProviderConfig, split_spec, type_info

from .models import AgentDefaults, CompactionSettings, DefaultModel, ModelRetry, RouteSettings


def build_settings_router(ctx: Any, llm_entry: str) -> APIRouter:
    router = APIRouter()

    def llm() -> Any:
        service = ctx.get("llm", None)
        if service is None:
            raise HTTPException(503, "model registry (ctx.llm) unavailable")
        return service

    def profile() -> Any:
        profile = ctx.get("profile", None)
        if profile is None:
            raise HTTPException(409, "no profile: model settings are read-only in this harness")
        return profile

    async def persist(service: Any) -> None:
        """Write the live llm configuration (without secrets) to the profile patch; no restart needed."""
        data = service.config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        for route in data.get("providers", {}).values():
            route.pop("api_key", None)
        await manage.set_entry_config(profile(), llm_entry, data, merge=False, preflight=False)

    def view(service: Any) -> dict[str, Any]:
        lifecycle = ctx.lifecycle
        return {
            **service.describe(),
            "groups": service.directory()["groups"],
            "protocols": [{"id": k, "title": v["title"], "type": v["type"]} for k, v in PROTOCOLS.items()],
            "entry": llm_entry,
            "generation": lifecycle.generation,
            "editable": ctx.get("profile", None) is not None,
        }

    @router.get("/models")
    async def model_directory() -> dict[str, Any]:
        return llm().directory()

    @router.get("/agent")
    async def agent_options() -> dict[str, Any]:
        loop = ctx.get("agentLoop", None)
        if loop is None or not hasattr(loop, "presets"):
            return {"presets": [], "modes": [], "default_preset": None, "default_mode": None}
        return {
            "presets": loop.presets(),
            "modes": loop.modes(),
            "default_preset": loop.config.default_preset,
            "default_mode": loop.config.default_mode,
        }

    @router.put("/settings/agent")
    async def put_agent_defaults(body: AgentDefaults) -> dict[str, Any]:
        loop = ctx.get("agentLoop", None)
        if loop is None or not hasattr(loop, "set_defaults"):
            raise HTTPException(503, "agent loop unavailable")
        try:
            defaults = loop.set_defaults(preset=body.default_preset, mode=body.default_mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        await manage.set_entry_config(profile(), "agent-loop", defaults, merge=True, preflight=False)
        return {**defaults, "presets": loop.presets(), "modes": loop.modes()}

    def compaction_service() -> Any:
        service = ctx.get("compaction", None)
        if service is None:
            raise HTTPException(503, "compaction plugin unavailable")
        return service

    @router.get("/settings/compaction")
    async def get_compaction_settings() -> dict[str, Any]:
        return compaction_service().settings()

    @router.put("/settings/compaction")
    async def put_compaction_settings(body: CompactionSettings) -> dict[str, Any]:
        """Apply in place (the next model call uses the new values) and persist in the profile patch."""
        service = compaction_service()
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if "summary_model" in body.model_fields_set:
            fields["summary_model"] = body.summary_model or None
        try:
            settings = service.update(**fields)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        await manage.set_entry_config(profile(), "compaction", fields, merge=True, preflight=False)
        return {"application": "applied", **settings}

    @router.get("/settings/models")
    async def get_model_settings() -> dict[str, Any]:
        return view(llm())

    @router.put("/settings/models")
    async def put_default_model(body: DefaultModel) -> dict[str, Any]:
        service = llm()
        route, model = split_spec(body.default)
        if body.default and (not route or not model):
            raise HTTPException(422, "default must be route:model")
        service.update(default=body.default or None)
        await persist(service)
        return view(service)

    @router.put("/settings/model-retry")
    async def put_model_retry(body: ModelRetry) -> dict[str, Any]:
        """The retry policy of routes without their own; ``null`` leaves retries to the provider clients."""
        service = llm()
        profile()
        try:
            service.update(retry=body.retry)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        await persist(service)
        return view(service)

    @router.put("/settings/models/{route}")
    async def put_route(route: str, body: RouteSettings) -> dict[str, Any]:
        service = llm()
        store = profile().credentials
        owner = service.published().get(route)
        if owner is not None:
            raise HTTPException(409, f"route {route!r} is published by the {owner!r} plugin and is managed there")
        current = service.config.providers.get(route)
        data = current.model_dump(mode="python", exclude_none=True) if current is not None else {}
        data.pop("api_key", None)
        for field in ("type", "title", "protocol", "base_url", "models", "options"):
            value = getattr(body, field)
            if value is not None:
                data[field] = value or None if field in ("title", "base_url") else value
        if body.protocol is not None and body.protocol:
            data["type"] = PROTOCOLS[body.protocol]["type"]
        if body.retry is not None:
            if body.retry.get("mode") == "inherit":
                data.pop("retry", None)
            else:
                data["retry"] = body.retry
        kind = PROTOCOLS[data["protocol"]]["type"] if data.get("protocol") else (data.get("type") or route)
        info = type_info(kind)
        if info["package"] is None and kind not in service.providers():
            raise HTTPException(422, f"unknown provider type {kind!r}")
        if data.get("protocol") and not data.get("base_url"):
            raise HTTPException(422, "a custom endpoint needs base_url")
        reference = (
            data.get("api_key_env") or (info["env"] if route == kind else reference_for(route)) or reference_for(route)
        )
        plain = current.api_key if current is not None else None  # legacy: key written in the configuration
        if body.api_key:
            try:
                store.set(reference, body.api_key)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            data["api_key_env"] = reference
        elif body.api_key == "":
            store.delete(reference)
        elif plain and not store.describe(reference)["configured"]:
            store.set(reference, plain)  # migrate the plain key into the store; the configuration keeps the reference
            data["api_key_env"] = reference
        try:
            cfg = ProviderConfig.model_validate(data)
            providers = {
                **{k: v.model_dump(mode="python", exclude_none=True) for k, v in service.config.providers.items()},
                route: cfg.model_dump(mode="python", exclude_none=True),
            }
            default = service.config.default
            if not default or (cfg.models and split_spec(default)[0] not in {**providers, **service.published()}):
                default = f"{route}:{cfg.models[0].id}" if cfg.models else default
            service.update(providers=providers, default=default)
        except (ValueError, LLMConfigError) as exc:
            raise HTTPException(422, str(exc)) from None
        await persist(service)
        return {"route": service.describe_route(route), **view(service)}

    @router.delete("/settings/models/{route}")
    async def delete_route(route: str) -> dict[str, Any]:
        service = llm()
        if route not in service.config.providers:
            raise HTTPException(404, f"no route {route!r}")
        cfg = service.config.providers[route]
        providers = {
            k: v.model_dump(mode="python", exclude_none=True) for k, v in service.config.providers.items() if k != route
        }
        default = service.config.default
        if default and split_spec(default)[0] == route:
            default = next(
                (f"{r}:{v['models'][0]['id']}" for r, v in providers.items() if v.get("models")), "echo:echo"
            )
        service.update(providers=providers, default=default)
        if cfg.api_key_env:
            profile().credentials.delete(cfg.api_key_env)
        await persist(service)
        return view(service)

    @router.post("/settings/models/{route}/discover")
    async def discover_models(route: str, body: RouteSettings) -> dict[str, Any]:
        overrides = {
            k: v for k, v in (("base_url", body.base_url), ("api_key", body.api_key), ("protocol", body.protocol)) if v
        }
        kind = PROTOCOLS[body.protocol]["type"] if body.protocol else body.type
        try:
            return {"ok": True, **await llm().list_models(route, kind, **overrides)}
        except LLMConfigError as exc:
            return {"ok": False, "error": str(exc), "models": []}

    @router.post("/settings/models/{route}/test")
    async def test_route(route: str, body: RouteSettings) -> dict[str, Any]:
        service = llm()
        model = (body.model or "").strip()
        if not model:
            raise HTTPException(422, "model is required")
        overrides: dict[str, Any] = {k: v for k, v in (("base_url", body.base_url), ("api_key", body.api_key)) if v}
        if body.protocol:
            overrides.update(PROTOCOLS[body.protocol]["options"])
        cfg = service.config.providers.get(route)
        if cfg is None and (body.type or body.protocol):
            kind = PROTOCOLS[body.protocol]["type"] if body.protocol else body.type
            overrides["type"] = kind
        try:
            kind = overrides.pop("type", None)
            if kind and cfg is None:
                # Unsaved route: resolve through a temporary configuration.
                temp = LLMConfig.model_validate(
                    {
                        **service.config.model_dump(mode="python"),
                        "providers": {
                            **{
                                k: v.model_dump(mode="python", exclude_none=True)
                                for k, v in service.config.providers.items()
                            },
                            route: {"type": kind},
                        },
                    }
                )
                saved = service.config
                service.config = temp
                try:
                    return await service.probe(route, model, **overrides)
                finally:
                    service.config = saved
                    service.invalidate()
            return await service.probe(route, model, **overrides)
        except LLMConfigError as exc:
            return {"ok": False, "error": str(exc)}

    return router
