"""``HarnessMiddleware``: LangChain middleware that routes model and tool calls through the harness.

| hook       | route                                                                           |
|------------|---------------------------------------------------------------------------------|
| model call | model from ``configurable.model_spec`` or ``ctx.llm.default`` when it differs from the built one; |
|            | then ``agent/model-request`` (waterfall)                                        |
| tool call  | ``ctx.tools.execute``                                                           |

:class:`ModelCall` is the payload ``agent/model-request`` listeners receive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config

from pyharness_tools import ToolCall


@dataclass
class ModelCall:
    """One model call as ``agent/model-request`` listeners see it."""

    session_id: str | None
    request: Any  # langchain ModelRequest; replaceable: call.request = call.request.override(...)
    meta: dict[str, Any] = field(default_factory=dict)


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
        return await self._ctx.waterfall("agent/model-request", call, final=lambda c: handler(c.request))
