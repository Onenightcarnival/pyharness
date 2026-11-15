"""
One run of a session: its handle (event log), the :class:`Turn` handed to listeners, the turn record.

| name              | contract                                                                  |
|-------------------|---------------------------------------------------------------------------|
| ``RunHandle``     | event log of one run; each subscriber receives every event from the start |
| ``Turn``          | argument of ``agent/turn-start`` and ``agent/turn-end``                   |
| ``TurnRecorder``  | stats and trajectory of one turn, from the run events and graph updates   |
| ``SessionBusy``   | the session has a running turn                                            |
| ``NotContinuable``| the session's last turn cannot be continued                               |
| ``RestartPending``| a restart is pending; new runs are refused                                |
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage

from .messages import _iter_messages, _text

_ATTACHMENT = re.compile(r"\n*<attached-(?:file|directory)\b[^>]*>.*?</attached-(?:file|directory)>", re.DOTALL)
TURNS = ("pyharness", "turns")  # + (session_id,): one record per turn — stats and trajectory


class SessionBusy(RuntimeError):
    """The session has a running turn."""


class NotContinuable(RuntimeError):
    """The session's last turn cannot be continued: it did not fail, or not with a continuable failure code."""


class RestartPending(RuntimeError):
    """A restart is pending; new runs are refused."""


@dataclass
class Turn:
    session_id: str
    run_id: str
    kind: str  # message | approval | answer | continuation | compact | retry
    input: str | None
    outcome: str | None = None
    model: str | None = None  # route:model selected for the session; None: the default
    started_at: float = field(default_factory=time.time)
    extras: dict[str, Any] = field(default_factory=dict)  # listeners of agent/turn-end attach data for the done event


class RunHandle:
    """Event log of one run; each subscriber receives every event from the start."""

    def __init__(self, session_id: str, kind: str, text: str | None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.kind = kind
        self.input = text
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.task: asyncio.Task[Any] | None = None
        self.recorder: TurnRecorder | None = None
        self._cond = asyncio.Condition()

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._cond:
            self.events.append({"run_id": self.id, **event})
            self._cond.notify_all()

    async def finish(self) -> None:
        async with self._cond:
            self.done = True
            self._cond.notify_all()

    async def subscribe(self, start: int = 0) -> AsyncIterator[dict[str, Any]]:
        index = start
        while True:
            async with self._cond:
                while index >= len(self.events) and not self.done:
                    await self._cond.wait()
                batch = self.events[index:]
                index = len(self.events)
                finished = self.done
            for event in batch:
                yield event
            if finished and index >= len(self.events):
                return

    async def wait(self) -> list[dict[str, Any]]:
        async for _ in self.subscribe(len(self.events)):
            pass
        return self.events


class TurnRecorder:
    """
    Timing, token usage and a compact trajectory of one turn, from the run events and graph updates.

    Records: ``user`` (input), ``step`` (one model call: ttft, duration, tokens, text size, tool calls),
    ``tool`` (call → result: duration, status, sizes), ``retry`` (a model call retried: failure code, wait),
    ``end`` (outcome, and the failure code of an ``error``). Stats sum the steps and tools.
    """

    def __init__(self, turn: Turn) -> None:
        self.turn = turn
        self.started = time.time()
        self.step_start = self.started
        self.first_token: float | None = None
        self.records: list[dict[str, Any]] = []
        self.tools: dict[str, dict[str, Any]] = {}
        self.stats: dict[str, Any] = {
            "steps": 0,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "usage_steps": 0,
            "last_input_tokens": None,
            "llm_ms": 0,
            "tool_ms": 0,
            "ttft_ms": 0,
            "ttft_steps": 0,
            "decode_ms": 0,
            "decode_tokens": 0,
            "duration_ms": 0,
            "compactions": 0,
            "retries": 0,
        }
        if turn.input is not None:
            # @references travel as attachment blocks; the record keeps the typed text
            shown = _ATTACHMENT.sub("", turn.input).rstrip()
            self.records.append(
                {"t": "user", "at": self.started, "chars": len(turn.input), "kind": turn.kind, "preview": shown[:160]}
            )

    def observe_event(self, event: dict[str, Any]) -> None:
        now = time.time()
        kind = event.get("type")
        if kind in ("reasoning", "token") and self.first_token is None:
            self.first_token = now
        elif kind == "tool_call":
            record = {
                "t": "tool",
                "id": event.get("id"),
                "name": event.get("name"),
                "at": now,
                "args_chars": len(json.dumps(event.get("args", {}), ensure_ascii=False)),
            }
            self.records.append(record)
            if event.get("id"):
                self.tools[event["id"]] = record
            self.stats["tool_calls"] += 1
        elif kind == "tool_result":
            record = self.tools.pop(event.get("id"), None)
            if record is not None:
                record["dur_ms"] = round((now - record["at"]) * 1000)
                record["status"] = event.get("status")
                record["result_chars"] = len(event.get("content") or "")
                self.stats["tool_ms"] += record["dur_ms"]
            self.step_start = now
            self.first_token = None
        elif kind == "compact":
            self.records.append(
                {
                    "t": "compact",
                    "at": now,
                    "trigger": event.get("trigger"),
                    "removed": event.get("removed"),
                    "before_tokens": event.get("before_tokens"),
                    "after_tokens": event.get("after_tokens"),
                }
            )
            self.stats["compactions"] += 1
        elif kind == "retry":
            self.records.append(
                {
                    "t": "retry",
                    "at": now,
                    "attempt": event.get("attempt"),
                    "code": event.get("code"),
                    "delay_ms": event.get("delay_ms"),
                }
            )
            self.stats["retries"] += 1
            self.first_token = None  # the retried call starts its answer over

    def observe_update(self, chunk: Any) -> None:
        now = time.time()
        for node, update in (chunk or {}).items():
            if node != "model":
                continue
            for message in _iter_messages(update):
                if not isinstance(message, AIMessage):
                    continue
                st = self.stats
                st["steps"] += 1
                dur = round((now - self.step_start) * 1000)
                st["llm_ms"] += dur
                record: dict[str, Any] = {
                    "t": "step",
                    "at": self.step_start,
                    "dur_ms": dur,
                    "chars": len(_text(message.content)),
                    "tool_calls": len(message.tool_calls or []),
                }
                if self.first_token is not None:
                    record["ttft_ms"] = round((self.first_token - self.step_start) * 1000)
                    st["ttft_ms"] += record["ttft_ms"]
                    st["ttft_steps"] += 1
                usage = getattr(message, "usage_metadata", None) or {}
                if isinstance(usage, dict) and usage.get("output_tokens") is not None:
                    inp = int(usage.get("input_tokens") or 0)
                    out = int(usage.get("output_tokens") or 0)
                    details_in = usage.get("input_token_details") or {}
                    details_out = usage.get("output_token_details") or {}
                    cache_read = int(details_in.get("cache_read") or 0)
                    cache_write = int(details_in.get("cache_creation") or 0)
                    reasoning = int(details_out.get("reasoning") or 0)
                    record.update(
                        {
                            "input_tokens": inp,
                            "output_tokens": out,
                            "cache_read_tokens": cache_read,
                            "cache_write_tokens": cache_write,
                            "reasoning_tokens": reasoning,
                        }
                    )
                    st["input_tokens"] += inp
                    st["output_tokens"] += out
                    st["cache_read_tokens"] += cache_read
                    st["cache_write_tokens"] += cache_write
                    st["reasoning_tokens"] += reasoning
                    st["usage_steps"] += 1
                    st["last_input_tokens"] = inp
                    if self.first_token is not None:
                        st["decode_ms"] += round((now - self.first_token) * 1000)
                        st["decode_tokens"] += out
                self.records.append(record)
                self.step_start = now
                self.first_token = None

    def finish(self, outcome: str, after: int, error: dict[str, Any] | None = None) -> dict[str, Any]:
        """The turn record. ``error`` is ``{"code", "message"}`` of a turn that ended with outcome ``error``."""
        now = time.time()
        self.stats["duration_ms"] = round((now - self.started) * 1000)
        for record in self.tools.values():  # calls without a result (interrupted, cancelled)
            record.setdefault("status", "pending")
        self.records.append({"t": "end", "at": now, "outcome": outcome, **({"code": error["code"]} if error else {})})
        return {
            **({"error": error} if error else {}),
            "run_id": self.turn.run_id,
            "session_id": self.turn.session_id,
            "kind": self.turn.kind,
            "model": self.turn.model,
            "at": self.started,
            "after": after,
            "outcome": outcome,
            "stats": dict(self.stats),
            "records": self.records,
        }
