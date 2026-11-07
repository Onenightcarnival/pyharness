"""Checkpoint messages: markers, the summary prompt, context measurement, cut selection, transcript rendering."""

from __future__ import annotations

import json
import re
import uuid
from string import Template
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from pyharness import package_prompts

CHECKPOINT_KIND = "compact-checkpoint"
COMMAND_KIND = "command"
SUMMARY_OPEN = "<compacted-summary>"
SUMMARY_CLOSE = "</compacted-summary>"
PROMPTS = package_prompts(__file__)

PREAMBLE: str = PROMPTS["checkpoint"]["PREAMBLE"]
SUMMARY_SYSTEM: str = PROMPTS["checkpoint"]["SUMMARY_SYSTEM"]
INSTRUCTION: str = Template(PROMPTS["checkpoint"]["INSTRUCTION"]).substitute(summary_open=SUMMARY_OPEN)


def marker_of(message: BaseMessage) -> dict[str, Any] | None:
    marker = (getattr(message, "additional_kwargs", None) or {}).get("pyharness")
    return marker if isinstance(marker, dict) else None


def is_checkpoint(message: BaseMessage) -> bool:
    marker = marker_of(message)
    return isinstance(message, HumanMessage) and marker is not None and marker.get("kind") == CHECKPOINT_KIND


def command_of(message: BaseMessage) -> str | None:
    """Name of the slash command a user message carries (``{"kind": "command", "name": ...}``)."""
    marker = marker_of(message)
    if isinstance(message, HumanMessage) and marker is not None and marker.get("kind") == COMMAND_KIND:
        return str(marker.get("name") or "")
    return None


def summary_of(content: Any) -> str:
    """The summary text inside a checkpoint message."""
    text = _text(content)
    match = re.search(re.escape(SUMMARY_OPEN) + r"\n?(.*?)\n?" + re.escape(SUMMARY_CLOSE), text, re.DOTALL)
    return match.group(1).strip() if match else text


def measure(messages: list[BaseMessage]) -> int:
    """Tokens in context: the latest response's usage (input + output) plus an estimate of what follows it.

    Usage before the last checkpoint is stale (it priced the history the checkpoint replaced), so the estimate
    covers everything after a compaction until the next model call.
    """
    anchor: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if is_checkpoint(m):
            break
        usage = getattr(m, "usage_metadata", None)
        if isinstance(m, AIMessage) and isinstance(usage, dict) and usage.get("input_tokens") is not None:
            anchor = i
            break
    if anchor is None:
        return count_tokens_approximately(messages)
    usage = messages[anchor].usage_metadata  # type: ignore[union-attr]
    base = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    return base + (count_tokens_approximately(messages[anchor + 1 :]) if anchor + 1 < len(messages) else 0)


def cut_index(messages: list[BaseMessage], retain_tokens: int) -> int | None:
    """Index of the first message kept verbatim; ``None`` when nothing before it is worth summarizing.

    The tail holds at least ``retain_tokens`` (``0``: nothing is kept). The cut never separates an AI message's tool
    calls from their results, and a head that is only an earlier checkpoint is not compacted again.
    """
    n = len(messages)
    keep = n
    if retain_tokens > 0:
        acc = 0
        for i in range(n - 1, -1, -1):
            acc += count_tokens_approximately([messages[i]])
            keep = i
            if acc >= retain_tokens:
                break
    while keep > 0 and keep < n and isinstance(messages[keep], ToolMessage):
        keep -= 1
    if keep <= 0:
        return None
    if all(is_checkpoint(m) for m in messages[:keep]):
        return None
    return keep


def transcript(messages: list[BaseMessage], tool_result_chars: int) -> str:
    """Plain-text rendering of messages for the summarizer (provider-neutral: no tool schemas needed)."""
    lines: list[str] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            lines.append(f"[user]\n{_text(m.content)}")
        elif isinstance(m, AIMessage):
            text = _text(m.content)
            calls = "".join(
                f"\n[tool call] {tc.get('name')}"
                f"({json.dumps(tc.get('args', {}), ensure_ascii=False)[:tool_result_chars]})"
                for tc in (m.tool_calls or [])
            )
            lines.append(f"[assistant]\n{text}{calls}".rstrip())
        elif isinstance(m, ToolMessage):
            body = _text(m.content)
            if len(body) > tool_result_chars:
                body = body[: tool_result_chars // 2] + "\n…(truncated)…\n" + body[-tool_result_chars // 2 :]
            lines.append(
                f"[tool result: {m.name or 'tool'}{'' if m.status == 'success' else ' · ' + str(m.status)}]\n{body}"
            )
        elif isinstance(m, SystemMessage):
            lines.append(f"[system]\n{_text(m.content)}")
    return "\n\n".join(lines)


def checkpoint_message(summary: str, marker: dict[str, Any]) -> HumanMessage:
    content = f"{PREAMBLE}\n\n{SUMMARY_OPEN}\n{summary.strip()}\n{SUMMARY_CLOSE}"
    return HumanMessage(
        content=content, id=str(uuid.uuid4()), additional_kwargs={"pyharness": {"kind": CHECKPOINT_KIND, **marker}}
    )


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b if isinstance(b, str) else str(b.get("text", ""))
            for b in content
            if isinstance(b, str) or (isinstance(b, dict) and b.get("type") == "text")
        )
    return "" if content is None else str(content)
