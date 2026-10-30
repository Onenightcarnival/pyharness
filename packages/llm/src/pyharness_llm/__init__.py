"""``ctx.llm``: chat-model routes over LangChain provider integrations.

A **route** is a configured provider under ``config.providers[route]``: its ``type`` names a LangChain provider
(``init_chat_model`` ``model_provider``, or a factory registered with :meth:`LLMService.register`), its connection
facts (``base_url``, ``api_key_env``), and its model catalog. A model spec is ``"route:model"``.

| method                | purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| ``resolve(spec)``     | chat model for ``route:model``; instances cached until ``update``       |
| ``update(...)``       | replace the live configuration; the next request uses it               |
| ``describe()``        | routes with credential state (never the value) and the provider catalog |
| ``directory()``       | model choices for selectors, grouped by route                           |
| ``probe(...)``        | one short completion                                                    |
| ``list_models(...)``  | model ids served by an endpoint (OpenAI, Anthropic, Ollama listings)    |

Credentials: ``api_key_env`` is a reference resolved through the environment, then the profile credential store;
``api_key`` in the configuration is accepted and discouraged.

| ``type`` catalog       | source                                                            |
|------------------------|-------------------------------------------------------------------|
| LangChain built-ins    | ``langchain.chat_models.base._BUILTIN_PROVIDERS``                 |
| curated facts          | :data:`CURATED`: key and endpoint keyword names, env, defaults    |
| registered             | :meth:`LLMService.register` (``echo`` built in)                   |
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import time
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pyharness import Service

ModelFactory = Callable[..., BaseChatModel]

ROUTE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PROBE_PROMPT = "Reply with the single word OK."

PROTOCOLS: dict[str, dict[str, Any]] = {
    "openai-chat": {"title": "OpenAI Chat Completions", "type": "openai", "options": {"use_responses_api": False}, "models_api": "openai"},
    "openai-responses": {"title": "OpenAI Responses", "type": "openai", "options": {"use_responses_api": True}, "models_api": "openai"},
    "anthropic-messages": {"title": "Anthropic Messages", "type": "anthropic", "options": {}, "models_api": "anthropic"},
}

# Curated facts per LangChain provider type. Missing types fall back to generic ``api_key`` / ``base_url`` keywords.
CURATED: dict[str, dict[str, Any]] = {
    "openai": {"title": "OpenAI", "env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1", "models_api": "openai"},
    "azure_openai": {"title": "Azure OpenAI", "env": "AZURE_OPENAI_API_KEY", "keys": {"base_url": "azure_endpoint"}, "models_api": None},
    "anthropic": {"title": "Anthropic", "env": "ANTHROPIC_API_KEY", "base_url": "https://api.anthropic.com", "models_api": "anthropic"},
    "deepseek": {
        "title": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "keys": {"base_url": "api_base"},
        "models_api": "openai",
        "models": [{"id": "deepseek-chat", "name": "DeepSeek Chat"}, {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner"}],
    },
    "google_genai": {"title": "Google Gemini", "env": "GOOGLE_API_KEY", "keys": {"api_key": "google_api_key"}, "models_api": None},
    "google_vertexai": {"title": "Google Vertex AI", "credentials": False, "models_api": None},
    "google_anthropic_vertex": {"title": "Anthropic on Vertex AI", "credentials": False, "models_api": None},
    "bedrock": {"title": "Amazon Bedrock", "credentials": False, "models_api": None},
    "bedrock_converse": {"title": "Amazon Bedrock Converse", "credentials": False, "models_api": None},
    "anthropic_bedrock": {"title": "Anthropic on Bedrock", "credentials": False, "models_api": None},
    "groq": {"title": "Groq", "env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1", "models_api": "openai"},
    "mistralai": {
        "title": "Mistral AI",
        "env": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "keys": {"base_url": "endpoint"},
        "models_api": "openai",
    },
    "fireworks": {
        "title": "Fireworks AI",
        "env": "FIREWORKS_API_KEY",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "models_api": "openai",
    },
    "together": {"title": "Together AI", "env": "TOGETHER_API_KEY", "base_url": "https://api.together.xyz/v1", "models_api": "openai"},
    "xai": {"title": "xAI", "env": "XAI_API_KEY", "base_url": "https://api.x.ai/v1", "models_api": "openai"},
    "perplexity": {"title": "Perplexity", "env": "PPLX_API_KEY", "base_url": "https://api.perplexity.ai", "models_api": "openai"},
    "openrouter": {"title": "OpenRouter", "env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "models_api": "openai"},
    "ollama": {"title": "Ollama", "credentials": False, "base_url": "http://localhost:11434", "models_api": "ollama"},
    "cohere": {"title": "Cohere", "env": "COHERE_API_KEY", "keys": {"api_key": "cohere_api_key"}, "models_api": None},
    "huggingface": {"title": "Hugging Face", "env": "HUGGINGFACEHUB_API_TOKEN", "models_api": None},
    "nvidia": {"title": "NVIDIA", "env": "NVIDIA_API_KEY", "models_api": None},
    "ibm": {"title": "IBM watsonx", "env": "WATSONX_APIKEY", "models_api": None},
    "litellm": {"title": "LiteLLM", "credentials": False, "models_api": None},
    "upstage": {"title": "Upstage", "env": "UPSTAGE_API_KEY", "models_api": None},
    "baseten": {"title": "Baseten", "env": "BASETEN_API_KEY", "models_api": None},
    "meta": {"title": "Meta Llama API", "env": "LLAMA_API_KEY", "models_api": None},
    "azure_ai": {
        "title": "Azure AI",
        "env": "AZURE_AI_CREDENTIAL",
        "keys": {"base_url": "endpoint", "api_key": "credential"},
        "models_api": None,
    },
    "langsmith": {"title": "LangSmith", "env": "LANGSMITH_API_KEY", "models_api": None},
    "bedrock_mantle_anthropic": {"title": "Bedrock Mantle (Anthropic)", "credentials": False, "models_api": None},
    "bedrock_mantle_openai": {"title": "Bedrock Mantle (OpenAI)", "credentials": False, "models_api": None},
    "echo": {
        "title": "Echo (placeholder, no credentials)",
        "credentials": False,
        "models_api": None,
        "models": [{"id": "echo", "name": "Echo"}],
    },
}
HIDDEN_TYPES = {"langsmith", "bedrock_mantle_anthropic", "bedrock_mantle_openai"}
EXTRAS = {"deepseek": "deepseek", "anthropic": "anthropic"}


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    name: str | None = None
    context_window: int | None = Field(None, gt=0)
    max_tokens: int | None = Field(None, gt=0)
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for this model only.")


class ProviderConfig(BaseModel):
    """One route. Unknown fields are keyword arguments for every model of the route."""

    model_config = ConfigDict(extra="allow")

    type: str | None = Field(None, description="LangChain provider (openai, anthropic, …) or a registered factory; None: the route id.")
    title: str | None = None
    protocol: str | None = Field(None, description="Custom endpoints: openai-chat, openai-responses, anthropic-messages.")
    base_url: str | None = None
    api_key: str | None = Field(None, description="Plain key in the configuration; prefer api_key_env.")
    api_key_env: str | None = Field(None, description="Credential reference: environment variable, then the profile credential store.")
    models: list[ModelEntry] = Field(default_factory=list, description="Model catalog offered by selectors.")
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for every model of the route.")

    @field_validator("protocol")
    @classmethod
    def _protocol(cls, value: str | None) -> str | None:
        if value is not None and value not in PROTOCOLS:
            raise ValueError(f"unknown protocol {value!r}; one of {', '.join(PROTOCOLS)}")
        return value

    def kwargs(self) -> dict[str, Any]:
        return {**(self.model_extra or {}), **self.options}


class LLMConfig(BaseModel):
    default: str | None = Field(None, description="Default model, 'route:model'.")
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for every model.")
    providers: dict[str, ProviderConfig] = Field(default_factory=dict, description="Routes by id.")

    @field_validator("providers")
    @classmethod
    def _route_ids(cls, value: dict[str, ProviderConfig]) -> dict[str, ProviderConfig]:
        for route in value:
            if not ROUTE_ID.match(route):
                raise ValueError(f"invalid route id {route!r}: lowercase letters, digits, '-' and '_'")
        return value


class LLMConfigError(RuntimeError):
    pass


class EchoChatModel(BaseChatModel):
    """Placeholder model without credentials; replies with the last human message."""

    prefix: str = "echo: "

    @property
    def _llm_type(self) -> str:
        return "pyharness-echo"

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        last = next((m for m in reversed(messages) if m.type == "human"), None)
        text = last.text if last is not None else ""
        reply = f"{self.prefix}{text}\n\n(Placeholder model. Configure a model service in the Web UI settings or with PYH_MODEL.)"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> EchoChatModel:
        return self


# ---------------------------------------------------------------------- helpers
def split_spec(spec: str | None) -> tuple[str, str]:
    """``"route:model"`` → ``(route, model)``; no colon → ``("", spec)``."""
    if not spec:
        return "", ""
    route, sep, model = spec.partition(":")
    return (route, model) if sep else ("", spec)


def mask_secret(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return ("•" * 8) + value[-4:] if len(value) > 8 else "•" * 8


def builtin_types() -> dict[str, tuple[str, str]]:
    """LangChain provider → ``(package, class name)``."""
    try:
        from langchain.chat_models.base import _BUILTIN_PROVIDERS

        return {name: (pkg, cls) for name, (pkg, cls, _) in _BUILTIN_PROVIDERS.items()}
    except Exception:  # pragma: no cover - older langchain
        return {}


def type_info(kind: str) -> dict[str, Any]:
    """Catalog facts for a provider type: title, package, installed, env, base_url, keys, credentials, models_api."""
    builtin = builtin_types().get(kind)
    curated = CURATED.get(kind, {})
    package = builtin[0].split(".")[0] if builtin else None
    installed = importlib.util.find_spec(package) is not None if package else kind == "echo"
    return {
        "id": kind,
        "title": curated.get("title", kind.replace("_", " ").title()),
        "package": package,
        "extra": EXTRAS.get(kind),
        "installed": installed,
        "env": curated.get("env", f"{kind.upper()}_API_KEY" if curated.get("credentials", True) and kind != "echo" else None),
        "base_url": curated.get("base_url"),
        "keys": {"api_key": "api_key", "base_url": "base_url", **curated.get("keys", {})},
        "credentials": curated.get("credentials", True),
        "models_api": curated.get("models_api"),
        "models": list(curated.get("models", [])),
        "curated": kind in CURATED,
    }


def translate_options(kind: str, options: dict[str, Any]) -> dict[str, Any]:
    """Generic ``base_url`` / ``api_key`` → the provider's keyword names; ``None`` values dropped.

    ``openai`` with a custom ``base_url`` defaults to the Chat Completions API (``use_responses_api=False``):
    the common denominator of OpenAI-compatible servers. Set ``use_responses_api`` explicitly to override.
    """
    keys = type_info(kind)["keys"] if kind else {}
    out: dict[str, Any] = {}
    for key, value in options.items():
        if value is None:
            continue
        out[keys.get(key, key)] = value
    base_url = options.get("base_url")
    if kind == "openai" and isinstance(base_url, str) and "api.openai.com" not in base_url:
        out.setdefault("use_responses_api", False)
    return out


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value if isinstance(value, (str, int, float, bool, type(None))) else repr(value)


class LLMService(Service):
    """Chat-model routes; resolves ``route:model`` specs."""

    key = "llm"
    name = "pyharness-llm"
    Config = LLMConfig

    def __init__(self, ctx: Any, config: LLMConfig) -> None:
        super().__init__(ctx, config)
        self._providers: dict[str, tuple[ModelFactory, str]] = {}
        self._cache: dict[Any, BaseChatModel] = {}

    async def start(self) -> None:
        self._providers["echo"] = (lambda model, **kw: EchoChatModel(), self.ctx.entry_id)

    # ------------------------------------------------------------------ registry
    def register(self, provider: str, factory: ModelFactory) -> Callable[[], Any]:
        """Register ``factory(model_name, **options) -> BaseChatModel`` as provider type ``provider``; returns the disposer."""
        if provider in self._providers:
            raise LLMConfigError(f"provider {provider!r} is already registered by {self._providers[provider][1]!r}")
        owner = self.caller.entry_id
        self._providers[provider] = (factory, owner)
        self._cache.clear()
        return self.caller.on_dispose(lambda: (self._providers.pop(provider, None), self._cache.clear()))

    def providers(self) -> dict[str, str]:
        """Registered provider types: ``type -> owning entry``."""
        return {name: owner for name, (_, owner) in self._providers.items()}

    @property
    def default(self) -> str | None:
        return self.config.default

    def update(
        self, *, default: str | None | Any = ..., providers: dict[str, Any] | None = None, options: dict[str, Any] | None = None
    ) -> LLMConfig:
        """Replace parts of the live configuration; validated; the next ``resolve`` uses it."""
        data = self.config.model_dump(mode="python")
        if default is not ...:
            data["default"] = default
        if providers is not None:
            data["providers"] = providers
        if options is not None:
            data["options"] = options
        self.config = LLMConfig.model_validate(data)
        self._cache.clear()
        return self.config

    def invalidate(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------ routes
    def route(self, route: str) -> ProviderConfig:
        """Configured route, or an implicit one whose ``type`` is the id (``openai:gpt-4o`` without configuration)."""
        return self.config.providers.get(route) or ProviderConfig(type=route)

    def route_type(self, route: str) -> str:
        cfg = self.route(route)
        if cfg.protocol:
            return PROTOCOLS[cfg.protocol]["type"]
        return cfg.type or route

    def _credentials(self) -> Any:
        profile = self.ctx.get("profile", None)
        return profile.credentials if profile is not None else None

    def references(self, route: str, cfg: ProviderConfig | None = None) -> list[str]:
        """Credential references tried in order: ``api_key_env``, ``<ROUTE>_API_KEY`` for a named route, the type's variable."""
        from pyharness.credentials import reference_for

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

    def resolve(self, spec: str | None = None, **overrides: Any) -> BaseChatModel:
        """Chat model for ``spec`` (``route:model``); ``None`` selects ``config.default``. Instances are cached."""
        spec = spec or self.config.default
        if not spec:
            raise LLMConfigError("no model: llm.config.default unset (PYH_MODEL, or the Web UI settings)")
        route, model = split_spec(spec)
        if not route:
            raise LLMConfigError(f"model spec {spec!r} needs the form route:model")
        options = self.options_for(route, model, **overrides)
        key = (spec, _freeze(options))
        if key in self._cache:
            return self._cache[key]
        kind = self.route_type(route)
        if kind in self._providers:
            chat = self._providers[kind][0](model, **translate_options("", options))
        else:
            info = type_info(kind)
            if info["package"] is None:
                raise LLMConfigError(f"unknown provider type {kind!r} for route {route!r}")
            if not info["installed"]:
                hint = f" (uv sync --extra {info['extra']})" if info["extra"] else f" (pip install {info['package'].replace('_', '-')})"
                raise LLMConfigError(f"provider {kind!r} needs the {info['package']} package{hint}")
            from langchain.chat_models import init_chat_model

            try:
                chat = init_chat_model(model, model_provider=kind, **translate_options(kind, options))
            except Exception as exc:
                raise LLMConfigError(f"cannot initialise model {spec!r}: {exc}") from exc
        self._cache[key] = chat
        return chat

    # ------------------------------------------------------------------ settings support
    def catalog(self) -> list[dict[str, Any]]:
        """Provider types offered for configuration: LangChain built-ins, curated facts, registered factories."""
        out = []
        seen = set()
        for kind in list(CURATED) + sorted(builtin_types()):
            if kind in seen or kind in HIDDEN_TYPES:
                continue
            seen.add(kind)
            info = type_info(kind)
            if kind in self._providers:
                info["installed"] = True
            out.append(info)
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
            "type_info": info,
            "configured": route in self.config.providers,
        }

    def describe(self) -> dict[str, Any]:
        route, model = split_spec(self.config.default)
        return {
            "default": self.config.default,
            "provider": route,
            "model": model,
            "routes": [self.describe_route(r) for r in self.config.providers],
            "catalog": self.catalog(),
            "registered": self.providers(),
            "env_model": os.environ.get("PYH_MODEL") or None,
        }

    def directory(self) -> dict[str, Any]:
        """Selector view: routes with their model catalogs and the default spec."""
        groups = []
        for route, cfg in self.config.providers.items():
            models = [{"id": m.id, "name": m.name or m.id, "spec": f"{route}:{m.id}"} for m in cfg.models]
            if models:
                groups.append({"id": route, "title": self.describe_route(route)["title"], "type": self.route_type(route), "models": models})
        default_route, default_model = split_spec(self.config.default)
        if self.config.default and default_route and not any(m["spec"] == self.config.default for g in groups for m in g["models"]):
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
        """One short completion with ``route:model``; ``overrides`` (base_url, api_key, type) win over the saved route."""
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

    async def list_models(self, route: str, kind: str | None = None, timeout: float = 20.0, **overrides: Any) -> dict[str, Any]:
        """Model ids served by the route's endpoint: ``/models`` (OpenAI, Anthropic) or ``/api/tags`` (Ollama)."""
        import httpx

        cfg = self.route(route)
        kind = kind or self.route_type(route)
        info = type_info(kind)
        api = PROTOCOLS[cfg.protocol]["models_api"] if cfg.protocol else info["models_api"]
        if "protocol" in overrides and overrides["protocol"]:
            api = PROTOCOLS[overrides["protocol"]]["models_api"]
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
                ident = str(row.get("id") or row.get("name"))
                entry: dict[str, Any] = {"id": ident, "name": str(row.get("display_name") or row.get("name") or ident)}
                for src, dst in (
                    ("context_window", "context_window"),
                    ("context_length", "context_window"),
                    ("max_input_tokens", "context_window"),
                    ("max_tokens", "max_tokens"),
                    ("max_output_tokens", "max_tokens"),
                ):
                    if isinstance(row.get(src), int) and row[src] > 0:
                        entry.setdefault(dst, row[src])
                models.append(entry)
            elif isinstance(row, str):
                models.append({"id": row, "name": row})
        models.sort(key=lambda m: m["id"])
        return {"supported": True, "models": models, "url": url}


__all__ = [
    "CURATED",
    "PROTOCOLS",
    "EchoChatModel",
    "LLMConfig",
    "LLMConfigError",
    "LLMService",
    "ModelEntry",
    "ProviderConfig",
    "mask_secret",
    "split_spec",
    "translate_options",
    "type_info",
]
