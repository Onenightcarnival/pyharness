from __future__ import annotations

import asyncio
from string import Template
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage
from langgraph.config import get_config
from langgraph.constants import TAG_NOSTREAM

from pyharness import package_toml

from .review import KIND, Review, ReviewError, parse, prompt, tool_schema

NOTES: dict[str, str] = package_toml(__file__)["NOTES"]
EVENT = "tool_review"
ALL_DECISIONS = ["approve", "edit", "reject", "respond"]  # decisions of a gate declared as ``True``


def review_of(messages: list[Any], call_id: str | None) -> dict[str, str] | None:
    """Record of the review of the call ``call_id`` in the last AI message; ``None`` without one."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            marker = message.additional_kwargs.get("pyharness")
            reviews = marker.get("reviews") if isinstance(marker, dict) and marker.get("kind") == KIND else None
            return (reviews or {}).get(call_id)
    return None


def note(review: dict[str, str] | None) -> str:
    """Approval card text of a call the review did not allow."""
    if review is None:
        return NOTES["unreviewed"]
    if review.get("error"):
        return Template(NOTES["failed"]).substitute(error=review["error"])
    if review.get("reason"):
        return Template(NOTES["denied"]).substitute(reason=review["reason"])
    return NOTES["denied_plain"]


def reviewed(gates: dict[str, Any]) -> dict[str, Any]:
    """
    ``gates`` (``tool name -> gate``) that ask only for a call its review did not allow: the gate's own ``when``
    still decides first, and the description opens with the review's note.
    """
    return {name: _reviewed(gate) for name, gate in gates.items() if gate}


def _reviewed(gate: bool | dict[str, Any]) -> dict[str, Any]:
    config = dict(gate) if isinstance(gate, dict) else {"allowed_decisions": list(ALL_DECISIONS)}
    inner_when, inner_description = config.get("when"), config.get("description")

    def when(request: Any) -> bool:
        if inner_when is not None and not inner_when(request):
            return False
        review = review_of(request.state.get("messages") or [], request.tool_call.get("id"))
        return review is None or review.get("decision") != "allow"

    def description(tool_call: Any, state: Any, runtime: Any) -> str:
        own = inner_description(tool_call, state, runtime) if callable(inner_description) else inner_description
        return "\n\n".join(
            part for part in (note(review_of(state.get("messages") or [], tool_call.get("id"))), own) if part
        )

    return {**config, "when": when, "description": description}


def _ai_message(response: Any) -> AIMessage | None:
    if isinstance(response, ExtendedModelResponse):
        response = response.model_response
    messages = response.result if isinstance(response, ModelResponse) else [response]
    return next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)


class ReviewMiddleware(AgentMiddleware):
    """
    Reviews the gated tool calls of each model reply before the approval step reads them.

    The records live on the AI message: ``additional_kwargs["pyharness"] = {"kind": "auto-review", "reviews":
    {tool call id: record}}``. Each review is also a ``tool_review`` run event.
    """

    def __init__(self, ctx: Any, config: Any, gates: dict[str, Any], *, subagent: bool = False) -> None:
        super().__init__()
        self._ctx = ctx
        self._config = config
        self._gates = {name: gate for name, gate in gates.items() if gate}
        self._subagent = subagent

    @property
    def name(self) -> str:  # type: ignore[override]
        return "PyHarnessAutoReview"

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        response = await handler(request)
        message = _ai_message(response)
        calls = [call for call in (message.tool_calls if message else []) if self._gated(call, request)]
        if not calls:
            return response
        session_id = (get_config().get("configurable") or {}).get("thread_id")
        workspace = await self._workspace(session_id)
        reviews: dict[str, dict[str, str]] = {}
        for call in calls:
            review = await self._review(request, call, workspace)
            reviews[call["id"]] = review.record()
            await self._publish(session_id, call, review)
        message.additional_kwargs["pyharness"] = {"kind": KIND, "reviews": reviews}
        return response

    def _gated(self, call: dict[str, Any], request: Any) -> bool:
        gate = self._gates.get(call["name"])
        if gate is None or not call.get("id"):
            return False
        when = gate.get("when") if isinstance(gate, dict) else None
        if when is None:
            return True
        try:
            return bool(when(ToolCallRequest(tool_call=call, tool=None, state=request.state, runtime=request.runtime)))
        except Exception:  # noqa: BLE001 - a predicate that needs the tool's own runtime: reviewed
            return True

    async def _review(self, request: Any, call: dict[str, Any], workspace: str | None) -> Review:
        model = self._ctx.llm.resolve(self._config.model) if self._config.model else request.model
        messages = prompt(
            request.messages,
            call,
            tool=tool_schema(request.tools, call["name"]),
            workspace=workspace,
            subagent=self._subagent,
        )
        try:
            reply = await asyncio.wait_for(
                model.ainvoke(messages, config={"tags": [TAG_NOSTREAM]}), self._config.timeout
            )
            return parse(str(reply.text))
        except ReviewError as exc:
            return Review("deny", error=str(exc))
        except TimeoutError:
            return Review("deny", error=f"no verdict within {self._config.timeout:g} s")
        except Exception as exc:  # noqa: BLE001 - a review that fails asks the user
            self._ctx.logger.warning("auto review of %s failed: %s: %s", call["name"], type(exc).__name__, exc)
            return Review("deny", error=f"{type(exc).__name__}: {exc}")

    async def _workspace(self, session_id: str | None) -> str | None:
        agents, workspaces = self._ctx.get("agents", None), self._ctx.get("workspace", None)
        if agents is None or workspaces is None or not session_id or not hasattr(workspaces, "open"):
            return None
        record = await agents.get_session(session_id)
        return str(workspaces.open((record or {}).get("workspace") or None).root)

    async def _publish(self, session_id: str | None, call: dict[str, Any], review: Review) -> None:
        agents = self._ctx.get("agents", None)
        if agents is not None and hasattr(agents, "publish"):
            await agents.publish(session_id, {"type": EVENT, "id": call["id"], "name": call["name"], **review.record()})
