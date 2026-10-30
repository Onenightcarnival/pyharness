"""``ctx.llm``: chat-model provider registry.

``resolve("provider:model")``:

| ``provider``                                | model from                                |
|---------------------------------------------|-------------------------------------------|
| registered with :meth:`LLMService.register` | the registered factory                    |
| ``echo`` (built in)                         | :class:`EchoChatModel`; no credentials    |
| any other                                   | ``langchain.chat_models.init_chat_model`` |

``config.providers[provider]`` holds keyword arguments for that provider's model class. Two keys are
generic and translated per provider (:data:`PROVIDERS`): ``base_url`` and ``api_key``.

| method            | purpose                                                             |
|-------------------|---------------------------------------------------------------------|
| ``describe()``    | default spec, per-provider options with masked secrets, the catalog |
| ``probe()``       | one short completion against a provider / model / options           |
| ``list_models()`` | model ids of an OpenAI- or Anthropic-compatible endpoint            |
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from pyharness import Service

ModelFactory = Callable[..., BaseChatModel]

# Provider catalog: how the generic ``base_url`` / ``api_key`` options map onto each integration.
PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "title": "OpenAI / OpenAI-compatible",
        "package": "langchain_openai",
        "extra": "openai",
        "base_url": "https://api.openai.com/v1",
        "keys": {"base_url": "base_url", "api_key": "api_key"},
        "env": "OPENAI_API_KEY",
        "models_api": "openai",
    },
    "deepseek": {
        "title": "DeepSeek",
        "package": "langchain_deepseek",
        "extra": "deepseek",
        "base_url": "https://api.deepseek.com",
        "keys": {"base_url": "api_base", "api_key": "api_key"},
        "env": "DEEPSEEK_API_KEY",
        "models_api": "openai",
    },
    "anthropic": {
        "title": "Anthropic",
        "package": "langchain_anthropic",
        "extra": "anthropic",
        "base_url": "https://api.anthropic.com",
        "keys": {"base_url": "base_url", "api_key": "api_key"},
        "env": "ANTHROPIC_API_KEY",
        "models_api": "anthropic",
    },
    "google_genai": {
        "title": "Google Gemini",
        "package": "langchain_google_genai",
        "extra": None,
        "base_url": None,
        "keys": {"base_url": "base_url", "api_key": "google_api_key"},
        "env": "GOOGLE_API_KEY",
        "models_api": None,
    },
    "echo": {
        "title": "Echo (placeholder, no credentials)",
        "package": None,
        "extra": None,
        "base_url": None,
        "keys": {},
        "env": None,
        "models_api": None,
    },
}

PROBE_PROMPT = "Reply with the single word OK."


class LLMConfig(BaseModel):
    default: str | None = Field(None, description="Default model, 'provider:model' (deepseek:deepseek-chat).")
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for every model.")
    providers: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Keyword arguments per provider: {provider: {...}}; base_url and api_key are generic."
    )


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
        reply = (
            f"{self.prefix}{text}\n\n(Placeholder model. Model setting: PYH_MODEL=provider:model "
            "(deepseek:deepseek-chat) plus the provider's LangChain integration package, or the Web UI settings page.)"
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> EchoChatModel:
        return self


def split_spec(spec: str | None) -> tuple[str, str]:
    """``"provider:model"`` → ``(provider, model)``; no colon → ``("", spec)``."""
    if not spec:
        return "", ""
    provider, sep, model = spec.partition(":")
    return (provider, model) if sep else ("", spec)


def mask_secret(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return ("•" * 8) + value[-4:] if len(value) > 8 else "•" * 8


def translate_options(provider: str, options: dict[str, Any]) -> dict[str, Any]:
    """Generic ``base_url`` / ``api_key`` → the provider's keyword names; ``None`` values dropped.

    ``openai`` with a custom ``base_url`` defaults to the Chat Completions API (``use_responses_api=False``):
    the common denominator of OpenAI-compatible servers. Set ``use_responses_api`` explicitly to override.
    """
    keys = PROVIDERS.get(provider, {}).get("keys", {})
    out: dict[str, Any] = {}
    for key, value in options.items():
        if value is None:
            continue
        out[keys.get(key, key)] = value
    base_url = out.get("base_url")
    if provider == "openai" and isinstance(base_url, str) and "api.openai.com" not in base_url:
        out.setdefault("use_responses_api", False)
    return out


def provider_available(provider: str) -> bool:
    info = PROVIDERS.get(provider)
    if info is None:
        return True  # unknown to the catalog: init_chat_model decides
    package = info["package"]
    if package is None:
        return True
    return importlib.util.find_spec(package) is not None


class LLMService(Service):
    """Chat-model provider registry; resolves ``provider:model`` specs."""

    key = "llm"
    name = "pyharness-llm"
    Config = LLMConfig

    def __init__(self, ctx: Any, config: LLMConfig) -> None:
        super().__init__(ctx, config)
        self._providers: dict[str, tuple[ModelFactory, str]] = {}

    async def start(self) -> None:
        self._providers["echo"] = (lambda model, **kw: EchoChatModel(), self.ctx.entry_id)

    def register(self, provider: str, factory: ModelFactory) -> Callable[[], Any]:
        """Register ``factory(model_name, **options) -> BaseChatModel`` for ``provider:*``; returns the disposer."""
        if provider in self._providers:
            raise LLMConfigError(f"provider {provider!r} is already registered by {self._providers[provider][1]!r}")
        owner = self.caller.entry_id
        self._providers[provider] = (factory, owner)
        return self.caller.on_dispose(lambda: self._providers.pop(provider, None))

    def providers(self) -> dict[str, str]:
        """``provider -> owning entry``."""
        return {name: owner for name, (_, owner) in self._providers.items()}

    @property
    def default(self) -> str | None:
        return self.config.default

    def options_for(self, provider: str, **overrides: Any) -> dict[str, Any]:
        """Effective options for ``provider``: global, per-provider, then ``overrides``."""
        return {**self.config.options, **self.config.providers.get(provider, {}), **overrides}

    def resolve(self, spec: str | None = None, **overrides: Any) -> BaseChatModel:
        """Chat model for ``spec``; ``None`` selects ``config.default``."""
        spec = spec or self.config.default
        if not spec:
            raise LLMConfigError("no model: llm.config.default unset (base bundle: PYH_MODEL)")
        provider, model = split_spec(spec)
        options = self.options_for(provider, **overrides)
        if provider in self._providers:
            return self._providers[provider][0](model, **translate_options(provider, options))
        if provider and not provider_available(provider):
            info = PROVIDERS[provider]
            hint = f" (uv sync --extra {info['extra']})" if info.get("extra") else ""
            raise LLMConfigError(f"provider {provider!r} needs the {info['package']} package{hint}")
        from langchain.chat_models import init_chat_model

        try:
            if provider:
                return init_chat_model(model, model_provider=provider, **translate_options(provider, options))
            return init_chat_model(spec, **translate_options("", options))
        except Exception as exc:
            raise LLMConfigError(f"cannot initialise model {spec!r}: {exc}") from exc

    # ------------------------------------------------------------------ settings support
    def describe(self) -> dict[str, Any]:
        """Default spec, per-provider options (secrets masked), and the provider catalog."""
        provider, model = split_spec(self.config.default)
        providers: dict[str, dict[str, Any]] = {}
        for name, options in self.config.providers.items():
            providers[name] = {
                "base_url": options.get("base_url"),
                "api_key": mask_secret(options.get("api_key")),
                "has_api_key": bool(options.get("api_key")),
                "other": sorted(k for k in options if k not in ("base_url", "api_key")),
            }
        registered = self.providers()
        catalog = []
        for name, info in PROVIDERS.items():
            catalog.append(
                {
                    "id": name,
                    "title": info["title"],
                    "package": info["package"],
                    "extra": info["extra"],
                    "base_url": info["base_url"],
                    "available": provider_available(name) or name in registered,
                    "env": info["env"],
                    "env_set": bool(info["env"] and os.environ.get(info["env"])),
                    "models_api": info["models_api"],
                    "credentials": bool(info["keys"]),
                }
            )
        for name, owner in registered.items():
            if name not in PROVIDERS:
                catalog.append(
                    {
                        "id": name,
                        "title": f"{name} (plugin {owner})",
                        "package": None,
                        "extra": None,
                        "base_url": None,
                        "available": True,
                        "env": None,
                        "env_set": False,
                        "models_api": None,
                        "credentials": False,
                    }
                )
        return {
            "default": self.config.default,
            "provider": provider,
            "model": model,
            "providers": providers,
            "registered": registered,
            "catalog": catalog,
            "env_model": os.environ.get("PYH_MODEL") or None,
        }

    async def probe(self, provider: str, model: str, timeout: float = 60.0, **overrides: Any) -> dict[str, Any]:
        """One short completion with ``provider:model``; ``overrides`` win over the saved options."""
        if not provider or not model:
            raise LLMConfigError("provider and model are required")
        chat = self.resolve(f"{provider}:{model}", **overrides)
        started = time.monotonic()
        try:
            reply = await asyncio.wait_for(chat.ainvoke([HumanMessage(content=PROBE_PROMPT)]), timeout)
        except TimeoutError:
            raise LLMConfigError(f"no reply within {timeout:.0f}s") from None
        except Exception as exc:
            raise LLMConfigError(f"{type(exc).__name__}: {exc}") from exc
        text = reply.text if hasattr(reply, "text") else str(reply.content)
        return {"ok": True, "reply": (text or "").strip()[:400], "latency_ms": int((time.monotonic() - started) * 1000)}

    async def list_models(self, provider: str, timeout: float = 20.0, **overrides: Any) -> dict[str, Any]:
        """Model ids from the provider's ``/models`` endpoint (OpenAI- and Anthropic-style APIs)."""
        import httpx

        info = PROVIDERS.get(provider) or {}
        api = info.get("models_api")
        if api is None:
            return {"supported": False, "models": []}
        options = self.options_for(provider, **overrides)
        base_url = (options.get("base_url") or info.get("base_url") or "").rstrip("/")
        api_key = options.get("api_key") or (os.environ.get(info["env"]) if info.get("env") else None) or ""
        if not base_url:
            raise LLMConfigError("base_url is required")
        if api == "anthropic":
            url = base_url if base_url.endswith("/v1") else base_url + "/v1"
            url += "/models"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        else:
            url = base_url + "/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
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
        rows = data.get("data") if isinstance(data, dict) else data
        models = []
        for row in rows or []:
            if isinstance(row, dict) and row.get("id"):
                models.append(str(row["id"]))
            elif isinstance(row, str):
                models.append(row)
        return {"supported": True, "models": sorted(set(models)), "url": url}


__all__ = [
    "EchoChatModel",
    "LLMConfig",
    "LLMConfigError",
    "LLMService",
    "PROVIDERS",
    "mask_secret",
    "split_spec",
    "translate_options",
]
