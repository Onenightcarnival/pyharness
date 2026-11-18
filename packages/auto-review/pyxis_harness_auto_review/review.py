from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from pyxis_harness import package_prompts, package_toml

KIND = "auto-review"
PAIRS = {("low", "allow"), ("medium", "allow"), ("medium", "deny"), ("high", "deny")}  # valid (risk, decision)
POLICY: str = package_prompts(__file__)["review"]["policy"]
HISTORY: dict[str, int] = package_toml(__file__)["HISTORY"]
ATTACHMENT = re.compile(r"\n*<attached-(?:file|directory)\b[^>]*>.*?</attached-(?:file|directory)>", re.DOTALL)


class ReviewError(ValueError):
    """The reviewer's reply is not a verdict."""


@dataclass(frozen=True)
class Review:
    """
    Outcome of one review.

    | outcome | fields                                         |
    |---------|------------------------------------------------|
    | allowed | ``decision="allow"``, ``risk``                 |
    | denied  | ``decision="deny"``, ``risk``, ``reason``?     |
    | failed  | ``decision="deny"``, ``error``                 |
    """

    decision: str
    risk: str | None = None
    reason: str | None = None
    error: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def record(self) -> dict[str, str]:
        fields = {"decision": self.decision, "risk": self.risk, "reason": self.reason, "error": self.error}
        return {k: v for k, v in fields.items() if v}


def parse(text: str) -> Review:
    """Verdict of a reviewer reply: one JSON object with a valid ``(risk, decision)`` pair."""
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        raise ReviewError(f"the reviewer's reply is not a JSON object: {text[:200]!r}") from None
    if not isinstance(data, dict) or (data.get("risk"), data.get("decision")) not in PAIRS:
        raise ReviewError(f"the reviewer's reply is not a verdict: {text[:200]!r}")
    reason = data.get("reason")
    denied = data["decision"] == "deny" and isinstance(reason, str) and reason.strip()
    return Review(data["decision"], data["risk"], reason.strip() if denied else None)


def _clip(text: str, chars: int) -> str:
    return text if len(text) <= chars else text[:chars] + f"… [{len(text) - chars} more characters]"


def _text(message: BaseMessage) -> str:
    return ATTACHMENT.sub("", str(message.text)).strip()


def history(messages: list[BaseMessage], *, subagent: bool = False) -> list[dict[str, Any]]:
    """
    Items a review reads, oldest first.

    | message                                     | item                                    |
    |---------------------------------------------|-----------------------------------------|
    | human, typed by the user                    | ``user-instruction``; no attachments    |
    | human, the first one of a subagent          | ``parent-instruction``                  |
    | human, written by the harness               | ``checkpoint``                          |
    | AI                                          | ``fact`` per tool call; no text         |
    | tool result, system                         | none                                    |
    """
    items: list[dict[str, Any]] = []
    first = True
    for message in messages:
        if isinstance(message, HumanMessage):
            written = isinstance(message.additional_kwargs.get("pyharness"), dict)
            role = "checkpoint" if written else "parent-instruction" if subagent and first else "user-instruction"
            first = False
            if text := _text(message):
                items.append({"role": role, "text": _clip(text, HISTORY["text_chars"])})
        elif isinstance(message, AIMessage):
            for call in message.tool_calls:
                args = _clip(json.dumps(call.get("args") or {}, ensure_ascii=False), HISTORY["args_chars"])
                items.append({"role": "fact", "tool_call": {"name": call["name"], "args": args}})
    return items[-HISTORY["items"] :]


def tool_schema(tools: list[Any], name: str) -> dict[str, Any] | None:
    """``{"name", "description", "parameters"}`` of the tool ``name`` among a model request's tools."""
    for tool in tools:
        if (tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)) != name:
            continue
        try:
            return dict(convert_to_openai_tool(tool)["function"])
        except Exception:  # noqa: BLE001 - a tool without a convertible schema
            return {"name": name, "description": getattr(tool, "description", "")}
    return None


def prompt(
    messages: list[BaseMessage],
    call: dict[str, Any],
    *,
    tool: dict[str, Any] | None = None,
    workspace: str | None = None,
    subagent: bool = False,
) -> list[BaseMessage]:
    """Reviewer input for the pending ``call`` after ``messages``."""
    document = {
        "environment": {"workspace": workspace},
        "history": history(messages, subagent=subagent),
        "tool": tool,
        "pending": {"name": call["name"], "args": call.get("args") or {}},
    }
    return [SystemMessage(content=POLICY), HumanMessage(content=json.dumps(document, ensure_ascii=False, default=str))]
