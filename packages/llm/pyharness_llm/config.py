"""Configuration models: routes, model catalog entries, the ``route:model`` spec helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .catalog import PROTOCOLS

Modality = Literal["text", "image"]

ModelFactory = Callable[..., BaseChatModel]

ROUTE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    name: str | None = None
    context_window: int | None = Field(None, gt=0)
    max_tokens: int | None = Field(None, gt=0)
    input: list[Modality] = Field(default_factory=lambda: ["text"], description="Input modalities the model accepts.")
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for this model only.")

    @field_validator("input")
    @classmethod
    def _input(cls, value: list[str]) -> list[str]:
        out = [m for m in ("text", "image") if m in value]
        if not out:
            raise ValueError("a model accepts at least one input modality")
        return out


class ProviderConfig(BaseModel):
    """One route. Unknown fields are keyword arguments for every model of the route."""

    model_config = ConfigDict(extra="allow")

    type: str | None = Field(
        None, description="LangChain provider (openai, anthropic, …) or a registered factory; None: the route id."
    )
    title: str | None = None
    protocol: str | None = Field(
        None, description="Custom endpoints: openai-chat, openai-responses, anthropic-messages."
    )
    base_url: str | None = None
    api_key: str | None = Field(None, description="Plain key in the configuration; prefer api_key_env.")
    api_key_env: str | None = Field(
        None, description="Credential reference: environment variable, then the profile credential store."
    )
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


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value if isinstance(value, (str, int, float, bool, type(None))) else repr(value)
