from __future__ import annotations

import asyncio
import json
import math
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.config import get_config

from pyxis_harness_llm import failure_code, retry_after_ms
from pyxis_harness_tools import ToolCall


@dataclass
class ModelCall:
    """One model call as ``agent/model-request`` listeners see it."""

    session_id: str | None
    request: Any  # langchain ModelRequest; replaceable: call.request = call.request.override(...)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelRetry:
    """One retry of a model call as ``agent/model-retry`` listeners see it."""

    session_id: str | None
    attempt: int  # 1-based number of the retry about to run
    max_retries: int
    code: str  # failure code of the attempt that failed
    message: str
    delay_ms: int
    model_spec: str | None = None


CHARS_PER_TOKEN = 4
FRAMING = 4  # tokens of role or schema framing around a part
# The main agent's model request while its call is in progress; ``None`` outside that call.
_REQUEST: ContextVar[Any] = ContextVar("pyh_model_request", default=None)


def _chars(content: Any) -> int:
    return len(content) if isinstance(content, str) else len(json.dumps(content, ensure_ascii=False, default=str))


def _schema(tool: Any) -> Any:
    try:
        return convert_to_openai_tool(tool)
    except Exception:  # noqa: BLE001 - a provider-side tool without a convertible schema
        return tool if isinstance(tool, dict) else str(tool)


def context_sizes(messages: list[BaseMessage], tools: list[Any]) -> dict[str, int]:
    """
    Estimated tokens of one model request by part: ``{"system", "tools", "messages"}``.

    | part     | estimate                                                         |
    |----------|------------------------------------------------------------------|
    | system   | characters of the system messages / 4, plus framing               |
    | tools    | characters of the tool schemas as JSON / 4, plus framing          |
    | messages | ``count_tokens_approximately`` of the other messages              |
    """
    system = sum(_chars(m.content) for m in messages if isinstance(m, SystemMessage))
    schemas = json.dumps([_schema(t) for t in tools], ensure_ascii=False, default=str) if tools else ""
    return {
        "system": math.ceil(system / CHARS_PER_TOKEN) + FRAMING if system else 0,
        "tools": math.ceil(len(schemas) / CHARS_PER_TOKEN) + FRAMING if schemas else 0,
        "messages": count_tokens_approximately([m for m in messages if not isinstance(m, SystemMessage)]),
    }


class RequestScope(AgentMiddleware):
    """Innermost of the harness's middleware: marks the main agent's model call for ``ContextMeter``."""

    @property
    def name(self) -> str:  # type: ignore[override]
        return "PyHarnessRequestScope"

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        token = _REQUEST.set(request)
        try:
            return await handler(request)
        finally:
            _REQUEST.reset(token)


class ContextMeter(AsyncCallbackHandler):
    """
    Measures what the main agent sends to its model and publishes it as a ``context`` run event.

    The callback sees the request as sent: the system message after every middleware. Model calls outside
    ``RequestScope`` (subagents, reviewers, summarizers) are not measured.
    """

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    async def on_chat_model_start(
        self, serialized: Any, messages: list[list[BaseMessage]], *, metadata: Any = None, **kwargs: Any
    ) -> None:
        request = _REQUEST.get()
        agents = self._ctx.get("agents", None)
        if request is None or agents is None or not messages:
            return
        sizes = context_sizes(messages[0], list(getattr(request, "tools", None) or []))
        await agents.publish((metadata or {}).get("thread_id"), {"type": "context", **sizes})


def _configurable() -> dict[str, Any]:
    try:
        return dict(get_config().get("configurable") or {})
    except RuntimeError:  # no run in progress
        return {}


def _thread_id() -> str | None:
    return _configurable().get("thread_id")


class HarnessMiddleware(AgentMiddleware):
    """LangChain middleware → harness events."""

    def __init__(self, ctx: Any, built_spec: str | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._built_spec = built_spec

    @property
    def name(self) -> str:  # type: ignore[override]
        return "PyHarnessMiddleware"

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_call = request.tool_call
        call = ToolCall(
            name=tool_call["name"],
            args=dict(tool_call.get("args") or {}),
            id=tool_call.get("id"),
            session_id=_thread_id(),
            request=request,
        )
        return await self._ctx.tools.execute(call, handler)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        configurable = _configurable()
        spec = configurable.get("model_spec") or self._ctx.llm.default
        if spec and spec != self._built_spec:
            request = request.override(model=self._ctx.llm.resolve(spec))
        call = ModelCall(session_id=configurable.get("thread_id"), request=request, meta={"model_spec": spec})
        return await self._ctx.waterfall("agent/model-request", call, final=lambda c: self._call(c, handler))

    async def _call(self, call: ModelCall, handler: Any) -> Any:
        policy = self._ctx.llm.retry_policy(call.meta.get("model_spec"))
        attempt = 0
        while True:
            try:
                return await handler(call.request)
            except Exception as exc:
                code = failure_code(exc)
                if policy is None or attempt >= policy.max_retries or not policy.retries(code):
                    raise
                delay = policy.delay(attempt, retry_after_ms(exc))
                attempt += 1
                self._ctx.logger.warning(
                    "model call failed (%s: %s); retry %d of %d in %.1fs", code, exc, attempt, policy.max_retries, delay
                )
                await self._ctx.parallel(
                    "agent/model-retry",
                    ModelRetry(
                        session_id=call.session_id,
                        attempt=attempt,
                        max_retries=policy.max_retries,
                        code=code,
                        message=f"{type(exc).__name__}: {exc}",
                        delay_ms=round(delay * 1000),
                        model_spec=call.meta.get("model_spec"),
                    ),
                )
                await asyncio.sleep(delay)
