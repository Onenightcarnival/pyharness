from __future__ import annotations

import time
import uuid
from string import Template
from typing import Any, ClassVar

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.config import get_config
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from pydantic import BaseModel, Field

from pyxis_harness import Service, package_prompts

from .checkpoint import (
    INSTRUCTION,
    SUMMARY_SYSTEM,
    _text,
    checkpoint_message,
    command_of,
    cut_index,
    measure,
    transcript,
)

PROMPTS = package_prompts(__file__)


class Config(BaseModel):
    auto: bool = True  # compact before a model call once the context reaches threshold_ratio × window
    threshold_ratio: float = Field(0.8, gt=0, le=1)
    retain_ratio: float = Field(0.16, ge=0, lt=1)  # recent tail kept verbatim (automatic compaction)
    default_context_window: int = Field(128_000, gt=0)  # when the model declares no context window
    summary_model: str | None = None  # route:model for the summary call; None: the session's model
    tool_result_chars: int = Field(4000, gt=0)  # longest tool result quoted in the transcript given to the summarizer


class CompactionError(RuntimeError):
    pass


def _configurable() -> dict[str, Any]:
    try:
        return dict(get_config().get("configurable") or {})
    except RuntimeError:  # no run in progress
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
    name = "pyxis-harness-compaction"
    inject: ClassVar[list[str]] = ["agentLoop", "llm"]
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
        self.config = Config.model_validate(
            {**self.config.model_dump(), **{k: v for k, v in fields.items() if v is not None}}
        )
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
        self,
        messages: list[BaseMessage],
        *,
        trigger: str,
        spec: str | None,
        retain: int = 0,
        measured: int | None = None,
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
            "compaction (%s): %d messages → checkpoint; ~%d → ~%d tokens",
            trigger,
            len(head),
            before,
            marker["after_tokens"],
        )
        return [RemoveMessage(id=REMOVE_ALL_MESSAGES), checkpoint, *tail]

    async def summarize(self, messages: list[BaseMessage], spec: str | None) -> str:
        model = self.ctx.llm.resolve(self.config.summary_model or spec)
        prompt = [
            SystemMessage(content=SUMMARY_SYSTEM),
            HumanMessage(
                content=Template(PROMPTS["service"]["summary_request"]).substitute(
                    transcript=transcript(messages, self.config.tool_result_chars), instruction=INSTRUCTION
                )
            ),
        ]
        response = await model.ainvoke(prompt)
        text = _text(getattr(response, "content", response)).strip()
        if not text:
            raise CompactionError("summarization produced no text")
        return text
