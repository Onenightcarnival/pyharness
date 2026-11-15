"""Configuration models: routes, model catalog entries, the ``route:model`` spec helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .catalog import PROTOCOLS
from .failures import CODE, TRANSIENT_CODES

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


class RetryPolicy(BaseModel):
    """Retries of a failed model call, on top of the provider client's own.

    | field              | meaning                                                              |
    |--------------------|----------------------------------------------------------------------|
    | ``mode``           | ``transient``: retry the codes in ``codes``; ``all``: retry every failure |
    | ``max_retries``    | attempts after the first                                             |
    | ``codes``          | failure codes retried in ``transient`` mode (:mod:`.failures`)       |
    | ``initial_delay_ms`` | wait before the first retry                                        |
    | ``backoff_factor`` | each further wait is the previous one times this                     |
    | ``max_delay_ms``   | cap of one wait; a provider's ``retry_after_ms`` wins when it is longer, up to the cap |
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["transient", "all"] = "transient"
    max_retries: int = Field(2, ge=0, le=10)
    codes: list[str] = Field(default_factory=lambda: list(TRANSIENT_CODES))
    initial_delay_ms: int = Field(1000, ge=0, le=60_000)
    backoff_factor: float = Field(2.0, ge=1, le=10)
    max_delay_ms: int = Field(30_000, ge=0, le=600_000)

    @field_validator("codes")
    @classmethod
    def _codes(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for code in value:
            if not CODE.match(code):
                raise ValueError(f"invalid failure code {code!r}: upper-case letters, digits and underscores")
            if code not in out:
                out.append(code)
        return out

    def retries(self, code: str) -> bool:
        return self.mode == "all" or code in self.codes

    def delay(self, attempt: int, retry_after_ms: int | None = None) -> float:
        """Seconds to wait before retry ``attempt`` (0-based)."""
        wait = min(self.max_delay_ms, self.initial_delay_ms * self.backoff_factor**attempt)
        return min(self.max_delay_ms, max(wait, retry_after_ms or 0)) / 1000


class ProviderConfig(BaseModel):
    """One route. Unknown fields are keyword arguments for every model of the route."""

    model_config = ConfigDict(extra="allow")

    type: str | None = Field(
        None, description="LangChain provider (openai, anthropic, …) or a registered factory; None: the route id."
    )
    title: str | None = None
    protocol: str | None = Field(
        None, description="Custom endpoints: openai-chat, openai-responses, anthropic-messages, gemini."
    )
    base_url: str | None = None
    api_key: str | None = Field(None, description="Plain key in the configuration; prefer api_key_env.")
    api_key_env: str | None = Field(
        None, description="Credential reference: environment variable, then the profile credential store."
    )
    models: list[ModelEntry] = Field(default_factory=list, description="Model catalog offered by selectors.")
    options: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for every model of the route.")
    retry: RetryPolicy | None = Field(None, description="Retry policy of the route; None: the global one.")

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
    retry: RetryPolicy | None = Field(
        None, description="Retry policy of routes without their own; None: the provider client's retries only."
    )

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
