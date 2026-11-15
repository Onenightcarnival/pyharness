"""
Model side of the gateway: one :class:`Generation` becomes one LangChain ``astream`` over a route of ``ctx.llm``.

| name               | contract                                                                          |
|--------------------|-----------------------------------------------------------------------------------|
| ``LangChainBackend`` | ``stream(generation)`` yields the chunks of :mod:`.chunks`                      |
| ``UpstreamError``  | failure of the route: the provider's status when it is 4xx or 5xx, else 502       |

``temperature``, ``max_tokens`` and ``reasoning_effort`` of a request build a model instance of their own
(``ctx.llm.build``); a request without them uses the cached instance (``ctx.llm.resolve``). ``reasoning_effort``
reaches route types listed in :data:`REASONING_EFFORT_TYPES`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from pyharness import package_toml

from .chunks import Chunk, normalize
from .drafts import GatewayError, Generation

_CFG = package_toml(__file__)["backend"]
REASONING_EFFORT_TYPES: tuple[str, ...] = tuple(_CFG["REASONING_EFFORT_TYPES"])


class Models(Protocol):
    """``ctx.llm``, as the backend uses it."""

    def resolve(self, spec: str | None = None, **overrides: Any) -> Any: ...
    def build(self, spec: str | None = None, **overrides: Any) -> Any: ...
    def route_type(self, route: str) -> str: ...


class UpstreamError(GatewayError):
    """The route failed; ``status`` is the provider's when it is an HTTP error status."""


def upstream_error(error: Exception) -> UpstreamError:
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    code = getattr(error, "code", None)
    return UpstreamError(
        status if isinstance(status, int) and 400 <= status <= 599 else 502,
        code if isinstance(code, str) and code else "upstream_error",
        str(error) or type(error).__name__,
    )


class LangChainBackend:
    def __init__(self, llm: Models) -> None:
        self.llm = llm

    def _model(self, generation: Generation) -> Any:
        overrides: dict[str, Any] = {}
        if generation.temperature is not None:
            overrides["temperature"] = generation.temperature
        if generation.max_tokens is not None:
            overrides["max_tokens"] = generation.max_tokens
        if generation.reasoning_effort and self.llm.route_type(generation.target.provider) in REASONING_EFFORT_TYPES:
            overrides["reasoning_effort"] = generation.reasoning_effort
        spec = generation.target.id
        model = self.llm.build(spec, **overrides) if overrides else self.llm.resolve(spec)
        return model.bind_tools(generation.tools) if generation.tools else model

    async def stream(self, generation: Generation) -> AsyncIterator[Chunk]:
        try:
            model = self._model(generation)
            options = {"stop": generation.stop} if generation.stop else {}
            async for chunk in normalize(model.astream(generation.messages, **options)):
                yield chunk
        except GatewayError:
            raise
        except Exception as exc:
            raise upstream_error(exc) from exc
