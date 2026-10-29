"""``ctx.llm``: chat-model provider registry.

``resolve("provider:model")``:

| ``provider``                                | model from                                |
|---------------------------------------------|-------------------------------------------|
| registered with :meth:`LLMService.register` | the registered factory                    |
| ``echo`` (built in)                         | :class:`EchoChatModel`; no credentials    |
| any other                                   | ``langchain.chat_models.init_chat_model`` |
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from pyharness import Service

ModelFactory = Callable[..., BaseChatModel]


class LLMConfig(BaseModel):
    default: str | None = Field(None, description="Default model, 'provider:model' (deepseek:deepseek-chat).")
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for every model.")
    providers: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Keyword arguments per provider: {provider: {...}}."
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
            "(deepseek:deepseek-chat) plus the provider's LangChain integration package.)"
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "EchoChatModel":
        return self


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

    def resolve(self, spec: str | None = None, **overrides: Any) -> BaseChatModel:
        """Chat model for ``spec``; ``None`` selects ``config.default``."""
        spec = spec or self.config.default
        if not spec:
            raise LLMConfigError("no model: llm.config.default unset (base bundle: PYH_MODEL)")
        provider, sep, model = spec.partition(":")
        if not sep:
            provider, model = "", spec
        options = {**self.config.options, **self.config.providers.get(provider, {}), **overrides}
        if provider in self._providers:
            return self._providers[provider][0](model, **options)
        from langchain.chat_models import init_chat_model

        try:
            return init_chat_model(spec, **options)
        except Exception as exc:
            raise LLMConfigError(f"cannot initialise model {spec!r}: {exc}") from exc


__all__ = ["EchoChatModel", "LLMConfig", "LLMConfigError", "LLMService"]
