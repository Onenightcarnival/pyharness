"""``ctx.compaction``: context compaction — a checkpoint summary replaces older history.

| trigger | when                                                                      | kept verbatim                      |
|---------|---------------------------------------------------------------------------|------------------------------------|
| auto    | before a model call, once the measured context reaches ``threshold_ratio`` × window | the tail worth ``retain_ratio`` × window |
| manual  | ``/compact`` — a run of kind ``compact`` (``POST /sessions/{id}/compact``) | nothing: the whole history is summarized |

Measurement: the usage of the latest model response (input + output tokens) plus an estimate of the messages after
it; without usage (first steps, right after a compaction) the estimate covers everything. The window is the model's
declared ``context_window`` (Settings → Models), else ``default_context_window``.

The cut never separates a tool call from its results. The summary comes from the session's model (``summary_model``
overrides) prompted with a structured checkpoint template; the replacement is a user message whose
``additional_kwargs["pyharness"]`` is ``{"kind": "compact-checkpoint", ...}`` — the Web UI shows it as a marker, the
run stream carries a ``compact`` event, and the turn record a ``compact`` entry. Automatic compaction failures are
logged and the turn continues; manual ones fail the run.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from pydantic import BaseModel, Field

from pyharness import Service

CHECKPOINT_KIND = "compact-checkpoint"
COMMAND_KIND = "command"
SUMMARY_OPEN = "<compacted-summary>"
SUMMARY_CLOSE = "</compacted-summary>"

PREAMBLE = (
    "This is an automatically generated checkpoint condensing an earlier span of the conversation to free up "
    "context. Treat the captured context as established background and build on it without restating it. Continue "
    "the task directly from the messages that follow, without acknowledging this checkpoint."
)

SUMMARY_SYSTEM = (
    "You are a compaction engine for an AI coding assistant. You condense a conversation transcript into a structured checkpoint."
)

INSTRUCTION = f"""Condense the conversation transcript ABOVE into a structured checkpoint that lets another model resume the work with no loss of essential context.

Output EXACTLY the Markdown structure below: keep every section, in order. Use terse bullets, not prose paragraphs. Write "(none)" for an empty section — never drop a section.

## Primary Request and Intent
- [the user's original and evolving goals; quote verbatim where the exact wording matters]

## Key Technical Concepts
- [technologies, frameworks, patterns, and conventions in play]

## Files and Code
- [exact path: why it matters, key changes or snippets]

## Errors and Fixes
- [error: how it was resolved, plus any related user feedback]

## Pending Jobs
- [explicitly requested work not yet completed]

## Current Work
- [precisely what was in progress at this checkpoint]

## Next Step
- [the single next action, directly in line with the most recent request, or "(none)"]

## Critical Context
- [decisions and their rationale, constraints, user preferences, open questions, data needed to continue]

Rules:
- Write concise engineering prose in the language the user writes in. Preserve exact file paths, commands, error strings, identifiers, numeric values, function signatures, and syntax fragments.
- Capture user feedback and explicit instructions faithfully, especially corrections.
- Do NOT mention this summarization request or that the context was compacted.
- Output only the checkpoint text: do not call any tool or take any other action.
- If the transcript already contains a {SUMMARY_OPEN} block, it is a PRIOR checkpoint. Do not copy it forward verbatim: preserve still-true facts, drop stale ones, and merge newer information into a single consolidated summary under the same structure."""


class Config(BaseModel):
    auto: bool = True  # compact before a model call once the context reaches threshold_ratio × window
    threshold_ratio: float = Field(0.8, gt=0, le=1)
    retain_ratio: float = Field(0.16, ge=0, lt=1)  # recent tail kept verbatim (automatic compaction)
    default_context_window: int = Field(128_000, gt=0)  # when the model declares no context window
    summary_model: str | None = None  # route:model for the summary call; None: the session's model
    tool_result_chars: int = Field(4000, gt=0)  # longest tool result quoted in the transcript given to the summarizer


class CompactionError(RuntimeError):
    pass


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
    match = re.search(re.escape(SUMMARY_OPEN) + r"\n?(.*?)\n?" + re.escape(SUMMARY_CLOSE), text, re.S)
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
                f"\n[tool call] {tc.get('name')}({json.dumps(tc.get('args', {}), ensure_ascii=False)[:tool_result_chars]})"
                for tc in (m.tool_calls or [])
            )
            lines.append(f"[assistant]\n{text}{calls}".rstrip())
        elif isinstance(m, ToolMessage):
            body = _text(m.content)
            if len(body) > tool_result_chars:
                body = body[: tool_result_chars // 2] + "\n…(truncated)…\n" + body[-tool_result_chars // 2 :]
            lines.append(f"[tool result: {m.name or 'tool'}{'' if m.status == 'success' else ' · ' + str(m.status)}]\n{body}")
        elif isinstance(m, SystemMessage):
            lines.append(f"[system]\n{_text(m.content)}")
    return "\n\n".join(lines)


def checkpoint_message(summary: str, marker: dict[str, Any]) -> HumanMessage:
    content = f"{PREAMBLE}\n\n{SUMMARY_OPEN}\n{summary.strip()}\n{SUMMARY_CLOSE}"
    return HumanMessage(content=content, id=str(uuid.uuid4()), additional_kwargs={"pyharness": {"kind": CHECKPOINT_KIND, **marker}})


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


def _configurable() -> dict[str, Any]:
    try:
        from langgraph.config import get_config

        return dict(get_config().get("configurable") or {})
    except Exception:
        return {}


class CompactionMiddleware(AgentMiddleware):
    """Before each model call: the ``/compact`` command, else automatic compaction under pressure."""

    def __init__(self, service: CompactionService) -> None:
        super().__init__()
        self.service = service

    @property
    def name(self) -> str:  # type: ignore[override]
        return "PyHarnessCompaction"

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages: list[BaseMessage] = list(state.get("messages") or [])
        if not messages:
            return None
        spec = _configurable().get("model_spec") or self.service.ctx.llm.default
        last = messages[-1]
        if command_of(last) == "compact":
            update = await self.service.compact_messages(messages[:-1], trigger="manual", spec=spec)
            return {"messages": update or [RemoveMessage(id=last.id)], "jump_to": "end"}
        if not self.service.config.auto:
            return None
        try:
            update = await self.service.compact_if_needed(messages, spec)
        except Exception as exc:  # noqa: BLE001 — the turn goes on with the full context
            self.service.ctx.logger.warning("automatic compaction failed: %s; continuing the turn", exc)
            return None
        return {"messages": update} if update else None


class CompactionService(Service):
    key = "compaction"
    name = "pyharness-compaction"
    inject = ["agentLoop", "llm"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.last: dict[str, Any] | None = None  # the latest compaction (diagnostics)

    async def start(self) -> None:
        self.ctx.agentLoop.add_middleware(CompactionMiddleware(self))

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        return self.config.model_dump()

    def update(self, **fields: Any) -> dict[str, Any]:
        """Replace configuration fields in place (validated); the next model call uses them."""
        self.config = Config.model_validate({**self.config.model_dump(), **{k: v for k, v in fields.items() if v is not None}})
        return self.settings()

    def window(self, spec: str | None) -> int:
        try:
            declared = self.ctx.llm.context_window(spec)
        except Exception:  # noqa: BLE001
            declared = None
        return int(declared or self.config.default_context_window)

    # ------------------------------------------------------------------ compaction
    async def compact_if_needed(self, messages: list[BaseMessage], spec: str | None) -> list[BaseMessage] | None:
        window = self.window(spec)
        measured = measure(messages)
        if measured < window * self.config.threshold_ratio:
            return None
        return await self.compact_messages(
            messages, trigger="auto", spec=spec, retain=int(window * self.config.retain_ratio), measured=measured
        )

    async def compact_messages(
        self, messages: list[BaseMessage], *, trigger: str, spec: str | None, retain: int = 0, measured: int | None = None
    ) -> list[BaseMessage] | None:
        """The ``messages`` state update replacing the compacted head with a checkpoint; ``None`` when nothing to do."""
        keep = cut_index(messages, retain)
        if keep is None:
            return None
        head, tail = messages[:keep], messages[keep:]
        summary = await self.summarize(head, spec)
        before = measured if measured is not None else count_tokens_approximately(messages)
        marker = {
            "id": uuid.uuid4().hex,
            "trigger": trigger,
            "at": time.time(),
            "removed": len(head),
            "before_tokens": before,
            "model": self.config.summary_model or spec,
        }
        checkpoint = checkpoint_message(summary, marker)
        if count_tokens_approximately([checkpoint]) >= count_tokens_approximately(head):
            raise CompactionError("the summary is not smaller than the history it would replace")
        marker["after_tokens"] = count_tokens_approximately([checkpoint, *tail])
        checkpoint.additional_kwargs["pyharness"]["after_tokens"] = marker["after_tokens"]
        for m in tail:
            if m.id is None:
                m.id = str(uuid.uuid4())
        self.last = {**marker, "kept": len(tail)}
        self.ctx.logger.info(
            "compaction (%s): %d messages → checkpoint; ~%d → ~%d tokens", trigger, len(head), before, marker["after_tokens"]
        )
        return [RemoveMessage(id=REMOVE_ALL_MESSAGES), checkpoint, *tail]

    async def summarize(self, messages: list[BaseMessage], spec: str | None) -> str:
        model = self.ctx.llm.resolve(self.config.summary_model or spec)
        prompt = [
            SystemMessage(content=SUMMARY_SYSTEM),
            HumanMessage(
                content=f"Conversation transcript:\n\n{transcript(messages, self.config.tool_result_chars)}\n\n---\n\n{INSTRUCTION}"
            ),
        ]
        response = await model.ainvoke(prompt)
        text = _text(getattr(response, "content", response)).strip()
        if not text:
            raise CompactionError("summarization produced no text")
        return text


__all__ = [
    "CHECKPOINT_KIND",
    "COMMAND_KIND",
    "CompactionError",
    "CompactionMiddleware",
    "CompactionService",
    "Config",
    "checkpoint_message",
    "command_of",
    "cut_index",
    "is_checkpoint",
    "measure",
    "summary_of",
    "transcript",
]
