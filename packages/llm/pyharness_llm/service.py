from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import Any

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pyharness import Service, package_prompts
from pyharness.credentials import reference_for

from .catalog import GEMINI_VERSION, PRESETS, PROTOCOLS, translate_options, type_info
from .config import (
    LLMConfig,
    LLMConfigError,
    ModelFactory,
    ProviderConfig,
    RetryPolicy,
    _freeze,
    mask_secret,
    split_spec,
)
from .failures import RETRY_CHOICES

PROMPTS = package_prompts(__file__)
PROBE_PROMPT: str = PROMPTS["service"]["PROBE_PROMPT"]


class EchoChatModel(BaseChatModel):
    """Placeholder model without credentials; replies with the last human message."""

    prefix: str = "echo: "

    @property
    def _llm_type(self) -> str:
        return "pyxis-harness-echo"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        last = next((m for m in reversed(messages) if m.type == "human"), None)
        text = last.text if last is not None else ""
        reply = (
            f"{self.prefix}{text}\n\n"
            "(Placeholder model. Configure a model service in the Web UI settings or with PYH_MODEL.)"
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> EchoChatModel:
        return self


class LLMService(Service):
    """Chat-model routes; resolves ``route:model`` specs."""

    key = "llm"
    name = "pyxis-harness-llm"
    Config = LLMConfig

    def __init__(self, ctx: Any, config: LLMConfig) -> None:
        super().__init__(ctx, config)
        self._providers: dict[str, tuple[ModelFactory, str]] = {}
        self._published: dict[str, tuple[ProviderConfig, str]] = {}  # route id -> (route, owning entry)
        self._publishers: dict[str, Callable[[], Any]] = {}  # owning entry -> disposer of its routes
        self._cache: dict[Any, BaseChatModel] = {}

    async def start(self) -> None:
        self._providers["echo"] = (lambda model, **kw: EchoChatModel(), self.ctx.entry_id)

    # ------------------------------------------------------------------ registry
    def register(self, provider: str, factory: ModelFactory) -> Callable[[], Any]:
        """
        Register ``factory(model_name, **options) -> BaseChatModel`` as provider type ``provider``; returns the
        disposer.
        """
        if provider in self._providers:
            raise LLMConfigError(f"provider {provider!r} is already registered by {self._providers[provider][1]!r}")
        owner = self.caller.entry_id
        self._providers[provider] = (factory, owner)
        self._cache.clear()
        return self.caller.on_dispose(lambda: (self._providers.pop(provider, None), self._cache.clear()))

    def providers(self) -> dict[str, str]:
        """Registered provider types: ``type -> owning entry``."""
        return {name: owner for name, (_, owner) in self._providers.items()}

    def publish(self, routes: dict[str, Any]) -> Callable[[], Any]:
        """Set the routes the calling plugin publishes, replacing its earlier ones; returns the disposer."""
        owner = self.caller.entry_id
        validated = LLMConfig.model_validate({"providers": routes}).providers
        for route in validated:
            taken = self._published.get(route)
            if taken is not None and taken[1] != owner:
                raise LLMConfigError(f"route {route!r} is already published by {taken[1]!r}")
        self._published = {r: v for r, v in self._published.items() if v[1] != owner}
        self._published.update({route: (cfg, owner) for route, cfg in validated.items()})
        self._cache.clear()
        if owner not in self._publishers:
            self._publishers[owner] = self.caller.on_dispose(lambda: self._unpublish(owner))
        return self._publishers[owner]

    def _unpublish(self, owner: str) -> None:
        self._published = {r: v for r, v in self._published.items() if v[1] != owner}
        self._publishers.pop(owner, None)
        self._cache.clear()

    def published(self) -> dict[str, str]:
        """Published routes: ``route id -> owning entry``."""
        return {route: owner for route, (_, owner) in self._published.items()}

    def routes(self) -> dict[str, ProviderConfig]:
        """Every route in effect: the configured ones, then the published ones (which win on the same id)."""
        return {**self.config.providers, **{route: cfg for route, (cfg, _) in self._published.items()}}

    @property
    def default(self) -> str | None:
        return self.config.default

    def update(
        self,
        *,
        default: str | Any | None = ...,
        providers: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        retry: dict[str, Any] | Any | None = ...,
    ) -> LLMConfig:
        """Replace parts of the live configuration; validated; the next ``resolve`` uses it."""
        data = self.config.model_dump(mode="python")
        if default is not ...:
            data["default"] = default
        if providers is not None:
            data["providers"] = providers
        if options is not None:
            data["options"] = options
        if retry is not ...:
            data["retry"] = retry
        self.config = LLMConfig.model_validate(data)
        self._cache.clear()
        return self.config

    def invalidate(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------ routes
    def route(self, route: str) -> ProviderConfig:
        """
        Route in effect (configured or published), or an implicit one whose ``type`` is the id
        (``openai:gpt-4o`` without configuration).
        """
        return self.routes().get(route) or ProviderConfig(type=route)

    def route_type(self, route: str) -> str:
        cfg = self.route(route)
        if cfg.protocol:
            return PROTOCOLS[cfg.protocol]["type"]
        return cfg.type or route

    def retry_policy(self, spec: str | None = None) -> RetryPolicy | None:
        """
        The retry policy for ``spec`` (``None``: the default): its route's, else the global one; ``None`` adds
        no retries.
        """
        route, _ = split_spec(spec or self.default)
        return (self.route(route).retry if route else None) or self.config.retry

    def _credentials(self) -> Any:
        profile = self.ctx.get("profile", None)
        return profile.credentials if profile is not None else None

    def references(self, route: str, cfg: ProviderConfig | None = None) -> list[str]:
        """
        Credential references tried in order: ``api_key_env``, ``<ROUTE>_API_KEY`` for a named route, the type's
        variable.
        """
        cfg = cfg or self.route(route)
        kind = self.route_type(route)
        env = type_info(kind)["env"]
        out: list[str] = []
        for ref in (cfg.api_key_env, reference_for(route) if route != kind else None, env):
            if ref and ref not in out:
                out.append(ref)
        return out

    def api_key_for(self, route: str, cfg: ProviderConfig | None = None) -> tuple[str | None, dict[str, Any]]:
        """``(value, description)``; the description never carries the value."""
        cfg = cfg or self.route(route)
        if cfg.api_key:
            return cfg.api_key, {"reference": None, "configured": True, "source": "config"}
        refs = self.references(route, cfg)
        store = self._credentials()
        for ref in refs:
            if store is not None:
                value = store.get(ref)
                if value:
                    return value, store.describe(ref)
            elif os.environ.get(ref):
                return os.environ[ref], {"reference": ref, "configured": True, "source": "env"}
        return None, {"reference": refs[0] if refs else None, "configured": False, "source": None, "tried": refs}

    def accepts_images(self, spec: str | None) -> bool | None:
        """Whether the model of ``spec`` declares image input; ``None`` when the model is not in a catalog."""
        route, model = split_spec(spec or self.config.default)
        cfg = self.routes().get(route)
        if cfg is None:
            return None
        entry = next((m for m in cfg.models if m.id == model), None)
        return "image" in entry.input if entry is not None else None

    def context_window(self, spec: str | None) -> int | None:
        """Declared context window of the model of ``spec``; ``None`` when unknown."""
        route, model = split_spec(spec or self.config.default)
        cfg = self.routes().get(route)
        if cfg is None:
            return None
        entry = next((m for m in cfg.models if m.id == model), None)
        return entry.context_window if entry is not None else None

    def options_for(self, route: str, model: str | None = None, **overrides: Any) -> dict[str, Any]:
        """Keyword arguments for ``route``: global, route, model, then ``overrides``; credential resolved."""
        cfg = self.route(route)
        kind = self.route_type(route)
        options: dict[str, Any] = {**self.config.options}
        if cfg.protocol:
            options.update(PROTOCOLS[cfg.protocol]["options"])
        options.update(cfg.kwargs())
        if cfg.base_url:
            options["base_url"] = cfg.base_url
        entry = next((m for m in cfg.models if m.id == model), None) if model else None
        if entry is not None:
            if entry.max_tokens:
                options["max_tokens"] = entry.max_tokens
            options.update(entry.options)
        options.update(overrides)
        if "api_key" not in options and type_info(kind)["credentials"]:
            value, _ = self.api_key_for(route, cfg)
            if value:
                options["api_key"] = value
        return options

    def _plan(self, spec: str | None, overrides: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
        """``(spec, route, model, options)`` of a model request; ``None`` selects ``config.default``."""
        spec = spec or self.config.default
        if not spec:
            raise LLMConfigError("no model: llm.config.default unset (PYH_MODEL, or the Web UI settings)")
        route, model = split_spec(spec)
        if not route:
            raise LLMConfigError(f"model spec {spec!r} needs the form route:model")
        return spec, route, model, self.options_for(route, model, **overrides)

    def _construct(self, spec: str, route: str, model: str, options: dict[str, Any]) -> BaseChatModel:
        kind = self.route_type(route)
        if kind in self._providers:
            return self._providers[kind][0](model, **translate_options("", options))
        info = type_info(kind)
        if info["package"] is None:
            raise LLMConfigError(f"unknown provider type {kind!r} for route {route!r}")
        if not info["installed"]:
            raise LLMConfigError(
                f"provider {kind!r} needs the {info['package']} package "
                f"(pip install {info['package'].replace('_', '-')})"
            )
        try:
            return init_chat_model(model, model_provider=kind, **translate_options(kind, options))
        except Exception as exc:
            raise LLMConfigError(f"cannot initialise model {spec!r}: {exc}") from exc

    def resolve(self, spec: str | None = None, **overrides: Any) -> BaseChatModel:
        """Chat model for ``spec`` (``route:model``); ``None`` selects ``config.default``. Instances are cached."""
        spec, route, model, options = self._plan(spec, overrides)
        key = (spec, _freeze(options))
        if key not in self._cache:
            self._cache[key] = self._construct(spec, route, model, options)
        return self._cache[key]

    def build(self, spec: str | None = None, **overrides: Any) -> BaseChatModel:
        """A new chat model for ``spec`` with ``overrides``; not cached. For per-request parameters."""
        return self._construct(*self._plan(spec, overrides))

    # ------------------------------------------------------------------ settings support
    def catalog(self) -> list[dict[str, Any]]:
        """Provider types offered for configuration: the presets, ``echo``, and registered factories."""
        out = [type_info(kind) for kind in [*PRESETS, "echo"]]
        seen = {c["id"] for c in out}
        for kind, owner in self.providers().items():
            if kind not in seen:
                out.append(
                    {
                        **type_info(kind),
                        "title": f"{kind} (plugin {owner})",
                        "installed": True,
                        "credentials": False,
                        "registered_by": owner,
                    }
                )
        return out

    def describe_route(self, route: str) -> dict[str, Any]:
        cfg = self.route(route)
        kind = self.route_type(route)
        info = type_info(kind)
        value, credential = self.api_key_for(route, cfg)
        return {
            "id": route,
            "type": kind,
            "title": cfg.title or (PROTOCOLS[cfg.protocol]["title"] if cfg.protocol else info["title"]),
            "protocol": cfg.protocol,
            "base_url": cfg.base_url,
            "effective_base_url": cfg.base_url or info["base_url"],
            "api_key": {**credential, "masked": mask_secret(value), "required": info["credentials"]},
            "models": [m.model_dump(mode="json", exclude_none=True) for m in cfg.models],
            "options": {k: v for k, v in cfg.kwargs().items() if k != "api_key"},
            "retry": cfg.retry.model_dump(mode="json") if cfg.retry else None,
            "type_info": info,
            "configured": route in self.config.providers,
            "published_by": self.published().get(route),
        }

    def describe(self) -> dict[str, Any]:
        route, model = split_spec(self.config.default)
        return {
            "default": self.config.default,
            "provider": route,
            "model": model,
            "routes": [self.describe_route(r) for r in self.config.providers if r not in self._published],
            "catalog": self.catalog(),
            "registered": self.providers(),
            "retry": self.config.retry.model_dump(mode="json") if self.config.retry else None,
            "retry_choices": list(RETRY_CHOICES),
            "env_model": os.environ.get("PYH_MODEL") or None,
        }

    def directory(self) -> dict[str, Any]:
        """Selector view: routes with their model catalogs and the default spec."""
        groups = []
        for route, cfg in self.routes().items():
            models = [
                {
                    "id": m.id,
                    "name": m.name or m.id,
                    "spec": f"{route}:{m.id}",
                    "input": list(m.input),
                    "context_window": m.context_window,
                }
                for m in cfg.models
            ]
            if models:
                groups.append(
                    {
                        "id": route,
                        "title": self.describe_route(route)["title"],
                        "type": self.route_type(route),
                        "models": models,
                    }
                )
        default_route, default_model = split_spec(self.config.default)
        if (
            self.config.default
            and default_route
            and not any(m["spec"] == self.config.default for g in groups for m in g["models"])
        ):
            title = self.describe_route(default_route)["title"] if default_route else default_route
            groups.insert(
                0,
                {
                    "id": default_route,
                    "title": title,
                    "type": self.route_type(default_route),
                    "models": [{"id": default_model, "name": default_model, "spec": self.config.default}],
                },
            )
        return {"default": self.config.default, "groups": groups}

    async def probe(self, route: str, model: str, timeout: float = 60.0, **overrides: Any) -> dict[str, Any]:
        """
        One short completion with ``route:model``; ``overrides`` (base_url, api_key, type) win over the saved
        route.
        """
        if not route or not model:
            raise LLMConfigError("route and model are required")
        chat = self.resolve(f"{route}:{model}", **overrides)
        started = time.monotonic()
        try:
            reply = await asyncio.wait_for(chat.ainvoke([HumanMessage(content=PROBE_PROMPT)]), timeout)
        except TimeoutError:
            raise LLMConfigError(f"no reply within {timeout:.0f}s") from None
        except Exception as exc:
            raise LLMConfigError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            if overrides:
                self._cache.clear()  # probe options are not the saved route
        text = reply.text if hasattr(reply, "text") else str(reply.content)
        return {"ok": True, "reply": (text or "").strip()[:400], "latency_ms": int((time.monotonic() - started) * 1000)}

    async def list_models(
        self, route: str, kind: str | None = None, timeout: float = 20.0, **overrides: Any
    ) -> dict[str, Any]:
        """
        Model ids served by the route's endpoint: ``/models`` (OpenAI, Anthropic, Gemini) or ``/api/tags``
        (Ollama).
        """
        cfg = self.route(route)
        kind = kind or self.route_type(route)
        info = type_info(kind)
        api = PROTOCOLS[cfg.protocol].get("models_api") if cfg.protocol else info["models_api"]
        if overrides.get("protocol"):
            api = PROTOCOLS[overrides["protocol"]].get("models_api")
        if api is None:
            return {"supported": False, "models": []}
        base_url = (overrides.get("base_url") or cfg.base_url or info["base_url"] or "").rstrip("/")
        api_key = overrides.get("api_key") or self.api_key_for(route, cfg)[0] or ""
        if not base_url:
            raise LLMConfigError("base_url is required")
        headers: dict[str, str] = {}
        if api == "anthropic":
            url = (base_url if base_url.endswith("/v1") else base_url + "/v1") + "/models?limit=1000"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        elif api == "ollama":
            url = base_url + "/api/tags"
        elif api == "google":
            versioned = base_url if GEMINI_VERSION.search(base_url) else base_url + "/v1beta"
            url = versioned + "/models?pageSize=1000"
            headers = {"x-goog-api-key": api_key}
        else:
            url = base_url + "/models"
            if api_key:
                headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                res = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMConfigError(f"{type(exc).__name__}: {exc}") from exc
        if res.status_code >= 400:
            raise LLMConfigError(f"HTTP {res.status_code}: {res.text[:300]}")
        try:
            data = res.json()
        except ValueError:
            raise LLMConfigError("the models endpoint did not return JSON") from None
        rows = data.get("data") or data.get("models") if isinstance(data, dict) else data
        models = []
        for row in rows or []:
            if isinstance(row, dict) and (row.get("id") or row.get("name")):
                if "generateContent" not in row.get("supportedGenerationMethods", ["generateContent"]):
                    continue  # Gemini lists embedding and other non-chat models too
                ident = str(row.get("id") or row.get("name")).removeprefix("models/")
                label = row.get("display_name") or row.get("displayName") or row.get("name") or ident
                entry: dict[str, Any] = {"id": ident, "name": str(label).removeprefix("models/")}
                for src, dst in (
                    ("context_window", "context_window"),
                    ("context_length", "context_window"),
                    ("max_input_tokens", "context_window"),
                    ("inputTokenLimit", "context_window"),
                    ("outputTokenLimit", "max_tokens"),
                    ("max_tokens", "max_tokens"),
                    ("max_output_tokens", "max_tokens"),
                ):
                    if isinstance(row.get(src), int) and row[src] > 0:
                        entry.setdefault(dst, row[src])
                top = row.get("top_provider") if isinstance(row.get("top_provider"), dict) else {}
                if isinstance(top.get("max_completion_tokens"), int) and top["max_completion_tokens"] > 0:
                    entry.setdefault("max_tokens", top["max_completion_tokens"])
                arch = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
                modalities = row.get("input_modalities") or arch.get("input_modalities")
                if isinstance(modalities, list):
                    entry["input"] = [m for m in ("text", "image") if m in modalities] or ["text"]
                models.append(entry)
            elif isinstance(row, str):
                models.append({"id": row, "name": row})
        models.sort(key=lambda m: m["id"])
        return {"supported": True, "models": models, "url": url}
