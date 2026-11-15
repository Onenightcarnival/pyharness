from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config

from pyharness_llm import failure_code, retry_after_ms
from pyharness_tools import ToolCall


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


def _configurable() -> dict[str, Any]:
    try:
        return dict(get_config().get("configurable") or {})
    except Exception:
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
