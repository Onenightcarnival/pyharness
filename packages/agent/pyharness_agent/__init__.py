"""``ctx.agents``: sessions and runs over the graph ``ctx.agentLoop`` builds.

| concept    | contract                                                                            |
|------------|-------------------------------------------------------------------------------------|
| session    | LangGraph thread (``ctx.checkpointer``) + metadata record (``ctx.store``)           |
| run        | background task; events to a :class:`RunHandle`                                     |
| subscriber | replay from the start; a disconnect leaves the run running                          |
| hold       | each run holds the lifecycle; a pending restart waits for it                        |
| refusal    | restart pending → :meth:`AgentService.start_run` raises ``RestartPending``          |
| resume     | ``app/started`` of a supervised generation: continuation message per listed session |
| model      | ``session.model`` (``route:model``) reaches the loop as ``configurable.model_spec``    |
| graph      | one graph per (``workspace``, ``mode``, ``preset``) of the session, built on first use |

Run events: ``reasoning``, ``token``, ``image``, ``tool_call``, ``tool_result``, ``compact``, ``interrupt``,
``error``, ``done``. ``compact``: a compaction checkpoint replaced older history (``removed``, ``before_tokens``,
``after_tokens``, ``trigger``, ``summary``).

Images: a user message carries ``image_url`` content blocks (data URLs) beside its text; serialized messages
list them under ``images``; an AI message with image blocks emits ``image`` events and lists them likewise.

| event                | mode     | listener                               |
|----------------------|----------|----------------------------------------|
| ``agent/turn-start`` | parallel | ``(turn: Turn)``                       |
| ``agent/turn-end``   | parallel | ``(turn: Turn)``; ``turn.outcome`` set; ``turn.extras`` reaches the ``done`` event as ``extras`` |

Turn records: every turn is recorded in ``ctx.store`` (``("pyharness", "turns", session_id)``, key run id) with
``stats`` (steps, tool calls, token usage, llm/tool/ttft/decode wall time, duration, compactions) and ``records``
(the trajectory: user, step, tool, compact, end). ``turns(session_id)`` lists them; ``done`` carries the new one as ``extras.turn``.
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

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from pyharness import Service

NAMESPACE = ("pyharness", "sessions")
_ATTACHMENT = re.compile(r"\n*<attached-(?:file|directory)\b[^>]*>.*?</attached-(?:file|directory)>", re.S)
TURNS = ("pyharness", "turns")  # + (session_id,): one record per turn — stats and trajectory


class TurnRecorder:
    """Timing, token usage and a compact trajectory of one turn, from the run events and graph updates.

    Records: ``user`` (input), ``step`` (one model call: ttft, duration, tokens, text size, tool calls),
    ``tool`` (call → result: duration, status, sizes), ``end`` (outcome). Stats sum the steps and tools.
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
        }
        if turn.input is not None:
            shown = _ATTACHMENT.sub("", turn.input).rstrip()  # @references travel as attachment blocks; the record keeps the typed text
            self.records.append({"t": "user", "at": self.started, "chars": len(turn.input), "kind": turn.kind, "preview": shown[:160]})

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

    def finish(self, outcome: str, after: int) -> dict[str, Any]:
        now = time.time()
        self.stats["duration_ms"] = round((now - self.started) * 1000)
        for record in self.tools.values():  # calls without a result (interrupted, cancelled)
            record.setdefault("status", "pending")
        self.records.append({"t": "end", "at": now, "outcome": outcome})
        return {
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


DEFAULT_RESUME = (
    "[pyharness] Restarted into generation {generation}.\n"
    "Reason: {reasons}.{rollback}\n"
    "Task: the task in progress continues. Tools of newly enabled plugins are available; "
    "harness_inspect shows the active plugins."
)


class AgentConfig(BaseModel):
    resume_on_restart: bool = Field(True, description="Send a continuation message to listed sessions after a restart.")
    resume_message: str = DEFAULT_RESUME
    title_chars: int = 60


class SessionBusy(RuntimeError):
    """The session has a running turn."""


class RestartPending(RuntimeError):
    """A restart is pending; new runs are refused."""


@dataclass
class Turn:
    session_id: str
    run_id: str
    kind: str  # message | approval | answer | continuation | compact
    input: str | None
    outcome: str | None = None
    model: str | None = None  # route:model selected for the session; None: the default
    started_at: float = field(default_factory=time.time)
    extras: dict[str, Any] = field(default_factory=dict)  # listeners of agent/turn-end attach data for the done event


class RunHandle:
    """Event log of one run; each subscriber receives every event from the start."""

    def __init__(self, session_id: str, kind: str, input: str | None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.kind = kind
        self.input = input
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.task: asyncio.Task[Any] | None = None
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


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


def _images(content: Any) -> list[str]:
    """Image URLs (data URLs included) of ``image_url`` / ``image`` content blocks."""
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "image_url":
            url = block.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            if isinstance(url, str) and url:
                out.append(url)
        elif kind == "image":
            data = block.get("base64") or block.get("data")
            mime = block.get("mime_type") or block.get("mimeType") or "image/png"
            if isinstance(data, str) and data:
                out.append(f"data:{mime};base64,{data}")
            elif isinstance(block.get("url"), str):
                out.append(block["url"])
    return out


def user_content(text: str, images: list[str] | None = None) -> Any:
    """Content of a user message: plain text, or text and ``image_url`` blocks."""
    if not images:
        return text
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    blocks += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    return blocks


def _reasoning(message: BaseMessage) -> str:
    """Reasoning text of an AI message: ``reasoning_content`` (DeepSeek) or reasoning/thinking blocks."""
    extra = getattr(message, "additional_kwargs", None) or {}
    text = extra.get("reasoning_content")
    if isinstance(text, str) and text:
        return text
    if isinstance(message.content, list):
        parts = []
        for block in message.content:
            if isinstance(block, dict) and block.get("type") in ("reasoning", "thinking"):
                value = block.get("reasoning") or block.get("thinking") or block.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""


def _iter_messages(update: Any) -> list[BaseMessage]:
    if not isinstance(update, dict):
        return []
    messages = update.get("messages")
    if isinstance(messages, BaseMessage):
        return [messages]
    if isinstance(messages, (list, tuple)):
        return [m for m in messages if isinstance(m, BaseMessage)]
    value = getattr(messages, "value", None)  # Overwrite(...)
    if isinstance(value, (list, tuple)):
        return [m for m in value if isinstance(m, BaseMessage)]
    return []


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    data: dict[str, Any] = {"id": message.id, "role": message.type, "content": _text(message.content)}
    if images := _images(message.content):
        data["images"] = images
    if isinstance(message, AIMessage) and (reasoning := _reasoning(message)):
        data["reasoning"] = reasoning
    marker = (getattr(message, "additional_kwargs", None) or {}).get("pyharness")
    if isinstance(marker, dict):
        data["harness"] = marker  # message written by the harness
    if isinstance(message, AIMessage) and message.tool_calls:
        data["tool_calls"] = [{"id": tc.get("id"), "name": tc["name"], "args": tc.get("args", {})} for tc in message.tool_calls]
    if isinstance(message, ToolMessage):
        data["tool_call_id"] = message.tool_call_id
        data["name"] = message.name
        data["status"] = message.status
    return data


def _checkpoint(message: BaseMessage) -> dict[str, Any] | None:
    """Marker of a compaction checkpoint message (``{"kind": "compact-checkpoint", ...}``), else ``None``."""
    marker = (getattr(message, "additional_kwargs", None) or {}).get("pyharness")
    return marker if isinstance(marker, dict) and marker.get("kind") == "compact-checkpoint" else None


def _summary(content: Any) -> str:
    text = _text(content)
    start, end = text.find("<compacted-summary>"), text.rfind("</compacted-summary>")
    return text[start + len("<compacted-summary>") : end].strip() if 0 <= start < end else text


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


class AgentService(Service):
    """Sessions, runs, approvals, post-restart continuation."""

    key = "agents"
    name = "pyharness-agent"
    inject = ["agentLoop", "store"]
    Config = AgentConfig

    def __init__(self, ctx: Any, config: AgentConfig) -> None:
        super().__init__(ctx, config)
        self.graph: Any = None
        self._graphs: dict[tuple[str | None, str, str], Any] = {}
        self._runs: dict[str, RunHandle] = {}
        self._turn_seq: dict[str, int] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self.ctx.define_event("agent/turn-start", "parallel", "listener(turn: Turn) at the start of a run.")
        self.ctx.define_event("agent/turn-end", "parallel", "listener(turn: Turn) after a run settles; turn.outcome is set.")
        self.ctx.on("app/ready", self._build)
        self.ctx.on("app/started", self._resume_after_restart)
        self.ctx.on("app/stopping", self.stop)

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _build(self) -> None:
        self.graph = await self.ctx.agentLoop.build()

    async def graph_for(self, record: dict[str, Any] | None) -> Any:
        """Graph for the session's workspace, mode and preset; the default graph when the loop has no variants."""
        loop = self.ctx.agentLoop
        if record is None or not hasattr(loop, "preset"):
            return self._require_graph()
        workspace = record.get("workspace") or None
        mode = loop.mode(record.get("mode"))
        preset = loop.preset(record.get("preset"))[0]
        key = (workspace, mode, preset)
        if key not in self._graphs:
            self._graphs[key] = await loop.build(workspace=workspace, mode=mode, preset=preset)
        return self._graphs[key]

    def invalidate_graphs(self) -> None:
        self._graphs.clear()

    def _require_graph(self) -> Any:
        if self.graph is None:
            raise RuntimeError("agent graph unavailable before app/ready")
        return self.graph

    def config_for(self, session_id: str, model: str | None = None) -> dict[str, Any]:
        """LangGraph config of the session's thread (``model`` selects the model spec of the call)."""
        return self._config(session_id, model)

    def _config(self, session_id: str, model: str | None = None) -> dict[str, Any]:
        limit = getattr(self.ctx.get("agentLoop"), "recursion_limit", 200)
        configurable: dict[str, Any] = {"thread_id": session_id}
        if model:
            configurable["model_spec"] = model
        return {"configurable": configurable, "recursion_limit": limit}

    # ------------------------------------------------------------------ sessions
    async def create_session(
        self,
        title: str | None = None,
        meta: dict[str, Any] | None = None,
        model: str | None = None,
        workspace: str | None = None,
        mode: str | None = None,
        preset: str | None = None,
    ) -> dict[str, Any]:
        """New session; ``workspace`` (root directory), ``mode`` and ``preset`` are validated and defaulted by their services."""
        loop = self.ctx.get("agentLoop", None)
        workspaces = self.ctx.get("workspace", None)
        if workspaces is not None and hasattr(workspaces, "open"):
            ws = workspaces.open(workspace)
            workspace = None if ws is workspaces.default else str(ws.root)
            await workspaces.remember(workspace)
        if loop is not None and hasattr(loop, "mode"):
            mode = loop.mode(mode)
            preset = loop.preset(preset)[0]
        now = time.time()
        record = {
            "id": uuid.uuid4().hex,
            "title": (title or "")[: self.config.title_chars] or None,
            "created_at": now,
            "updated_at": now,
            "meta": meta or {},
            "model": model or None,
            "workspace": workspace,
            "mode": mode,
            "preset": preset,
        }
        await self.ctx.store.aput(NAMESPACE, record["id"], record)
        return record

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        item = await self.ctx.store.aget(NAMESPACE, session_id)
        return dict(item.value) if item is not None else None

    async def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        items = await self.ctx.store.asearch(NAMESPACE, limit=limit)
        rows = [dict(item.value) | {"busy": self.busy(item.key)} for item in items]
        return sorted(rows, key=lambda r: r.get("updated_at") or 0, reverse=True)

    async def set_model(self, session_id: str, model: str | None) -> dict[str, Any] | None:
        """Select ``model`` (``route:model``; ``None`` = the default) for the session's next requests."""
        return await self._set(session_id, "model", model or None)

    async def set_title(self, session_id: str, title: str | None) -> dict[str, Any] | None:
        """Rename the session; empty keeps automatic titling from the next message."""
        return await self._set(session_id, "title", (title or "").strip()[: self.config.title_chars] or None)

    async def set_mode(self, session_id: str, mode: str | None) -> dict[str, Any] | None:
        """Switch the permission mode; takes effect on the next run."""
        return await self._set(session_id, "mode", self.ctx.agentLoop.mode(mode))

    async def set_preset(self, session_id: str, preset: str | None) -> dict[str, Any] | None:
        """Switch the agent preset; takes effect on the next run."""
        return await self._set(session_id, "preset", self.ctx.agentLoop.preset(preset)[0])

    async def _set(self, session_id: str, field: str, value: Any) -> dict[str, Any] | None:
        record = await self.get_session(session_id)
        if record is None:
            return None
        record[field] = value
        await self.ctx.store.aput(NAMESPACE, session_id, record)
        return record

    async def _touch(self, session_id: str, title_hint: str | None = None) -> None:
        record = await self.get_session(session_id)
        if record is None:
            return
        record["updated_at"] = time.time()
        if not record.get("title") and title_hint:
            record["title"] = title_hint.strip().splitlines()[0][: self.config.title_chars] if title_hint.strip() else None
        await self.ctx.store.aput(NAMESPACE, session_id, record)

    async def turns(self, session_id: str) -> list[dict[str, Any]]:
        """Per-turn records (stats and trajectory), oldest first."""
        items = await self.ctx.store.asearch(TURNS + (session_id,), limit=10000)
        return sorted((dict(i.value) for i in items), key=lambda t: t.get("seq", 0))

    async def _next_turn_seq(self, session_id: str) -> int:
        if session_id not in self._turn_seq:
            self._turn_seq[session_id] = len(await self.turns(session_id))
        self._turn_seq[session_id] += 1
        return self._turn_seq[session_id]

    async def messages(self, session_id: str) -> list[dict[str, Any]]:
        state = await self._require_graph().aget_state(self._config(session_id))
        return [serialize_message(m) for m in (state.values or {}).get("messages", [])]

    async def pending(self, session_id: str) -> list[dict[str, Any]]:
        state = await self._require_graph().aget_state(self._config(session_id))
        return [{"id": i.id, "value": _jsonable(i.value)} for i in (state.interrupts or ())]

    def busy(self, session_id: str) -> bool:
        handle = self._runs.get(session_id)
        return handle is not None and not handle.done

    def current_run(self, session_id: str) -> RunHandle | None:
        return self._runs.get(session_id)

    async def cancel(self, session_id: str) -> bool:
        """Cancel the session's running turn (outcome ``cancelled``); returns whether one was running."""
        handle = self._runs.get(session_id)
        if handle is None or handle.done or handle.task is None:
            return False
        handle.task.cancel()
        await asyncio.gather(handle.task, return_exceptions=True)
        return True

    async def delete_session(self, session_id: str) -> bool:
        """Delete the session's metadata and checkpointed history; returns whether it existed."""
        if self.busy(session_id):
            raise SessionBusy(f"session {session_id} has a running turn")
        if await self.get_session(session_id) is None:
            return False
        await self.ctx.store.adelete(NAMESPACE, session_id)
        for item in await self.ctx.store.asearch(TURNS + (session_id,), limit=10000):
            await self.ctx.store.adelete(TURNS + (session_id,), item.key)
        self._turn_seq.pop(session_id, None)
        checkpointer = self.ctx.get("checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(session_id)
        self._runs.pop(session_id, None)
        return True

    # ------------------------------------------------------------------ runs
    def start_run(
        self,
        session_id: str,
        content: str | None = None,
        *,
        decisions: list[dict[str, Any]] | None = None,
        resume: dict[str, Any] | None = None,
        kind: str | None = None,
        marker: dict[str, Any] | None = None,
        model: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        """Start a run and return its handle. ``model`` overrides the session's selection for this run;
        ``images`` are data URLs attached to the user message.

        | arguments                | input to the graph                                          |
        |--------------------------|-------------------------------------------------------------|
        | ``content``              | user message                                                |
        | ``decisions``            | answers to the pending approvals                            |
        | ``resume``               | ``{interrupt_id: value}`` resuming other interrupts (``ask_user_question`` answers) |
        | ``content`` + ``marker`` | user-role message tagged ``additional_kwargs["pyharness"]`` |

        ``kind="compact"`` with ``marker={"kind": "command", "name": "compact"}`` runs a manual compaction: the
        compaction middleware replaces the history with a checkpoint and ends the run without a model call.
        """
        self._require_graph()
        if self.busy(session_id):
            raise SessionBusy(f"session {session_id} already has a running turn")
        if not self.ctx.lifecycle.accepting_work:
            raise RestartPending("restart pending: configuration change; retry later")
        if decisions is not None:
            from langgraph.types import Command

            payload: Any = Command(resume={"decisions": decisions})
            kind = kind or "approval"
        elif resume is not None:
            from langgraph.types import Command

            payload = Command(resume=resume)
            kind = kind or "answer"
        elif marker is not None:
            payload = {"messages": [HumanMessage(content=content or "", additional_kwargs={"pyharness": marker})]}
            kind = kind or "message"
        else:
            payload = {"messages": [HumanMessage(content=user_content(content or "", images))]}
            kind = kind or "message"
        handle = RunHandle(session_id, kind, content)
        self._runs[session_id] = handle
        task = asyncio.get_running_loop().create_task(self._drive(handle, payload, model))
        handle.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return handle

    async def _drive(self, handle: RunHandle, payload: Any, model: str | None = None) -> None:
        session_id = handle.session_id
        lifecycle = self.ctx.lifecycle
        turn = Turn(session_id=session_id, run_id=handle.id, kind=handle.kind, input=handle.input)
        recorder = TurnRecorder(turn)
        outcome = "completed"
        async with lifecycle.hold(f"run:{session_id}", session=session_id):
            try:
                record = await self.get_session(session_id)
                if model is None:
                    model = (record or {}).get("model") or None
                turn.model = model
                graph = await self.graph_for(record)
                await self.ctx.parallel("agent/turn-start", turn)
                async for mode, chunk in graph.astream(payload, self._config(session_id, model), stream_mode=["messages", "updates"]):
                    if mode == "updates":
                        recorder.observe_update(chunk)
                    for event in self._translate(mode, chunk):
                        recorder.observe_event(event)
                        await handle.publish(event)
                interrupts = await self.pending(session_id)
                if interrupts:
                    outcome = "interrupted"
                    await handle.publish({"type": "interrupt", "interrupts": interrupts})
            except asyncio.CancelledError:
                outcome = "cancelled"
            except Exception as exc:  # noqa: BLE001
                outcome = "error"
                self.ctx.logger.exception("run %s of session %s failed", handle.id, session_id)
                await handle.publish({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                turn.outcome = outcome
                try:
                    record = recorder.finish(outcome, len(await self.messages(session_id)))
                    record["seq"] = await self._next_turn_seq(session_id)
                    await self.ctx.store.aput(TURNS + (session_id,), handle.id, record)
                    turn.extras["turn"] = record
                except Exception:  # pragma: no cover
                    self.ctx.logger.exception("turn record failed")
                try:
                    await self._touch(session_id, handle.input if handle.kind == "message" else None)
                    await self.ctx.parallel("agent/turn-end", turn)
                except Exception:  # pragma: no cover
                    self.ctx.logger.exception("turn-end bookkeeping failed")
                await handle.publish(
                    {
                        "type": "done",
                        "outcome": outcome,
                        "restart_pending": lifecycle.restart_pending is not None,
                        "extras": _jsonable(turn.extras),
                    }
                )
                await handle.finish()

    @staticmethod
    def _translate(mode: str, chunk: Any) -> list[dict[str, Any]]:
        if mode == "messages":
            message, meta = chunk
            if (meta or {}).get("langgraph_node") != "model":
                return []
            if isinstance(message, (AIMessageChunk, AIMessage)):
                out = []
                if reasoning := _reasoning(message):
                    out.append({"type": "reasoning", "text": reasoning})
                if text := _text(message.content):
                    out.append({"type": "token", "text": text})
                return out
            return []
        out: list[dict[str, Any]] = []
        for node, update in (chunk or {}).items():
            if node == "__interrupt__":
                continue
            for message in _iter_messages(update):
                if isinstance(message, HumanMessage) and _checkpoint(message):
                    out.append({"type": "compact", **_checkpoint(message), "summary": _summary(message.content)})
                    continue
                if isinstance(message, AIMessage):
                    for url in _images(message.content):
                        out.append({"type": "image", "url": url})
                if isinstance(message, AIMessage) and message.tool_calls:
                    for tc in message.tool_calls:
                        out.append({"type": "tool_call", "id": tc.get("id"), "name": tc["name"], "args": _jsonable(tc.get("args", {}))})
                elif isinstance(message, ToolMessage):
                    out.append(
                        {
                            "type": "tool_result",
                            "id": message.tool_call_id,
                            "name": message.name,
                            "status": message.status,
                            "content": _text(message.content)[:4000],
                        }
                    )
        return out

    # ------------------------------------------------------------------ restart hand-off
    async def _resume_after_restart(self) -> None:
        lifecycle = self.ctx.lifecycle
        if not self.config.resume_on_restart or not lifecycle.supervised:
            return  # the hand-off belongs to supervised generations
        state = lifecycle.handoff()
        if not state:
            return
        rollback = state.get("rollback")
        rollback_note = ""
        if rollback:
            rollback_note = (
                "\nRollback: generation {gen} failed to boot ({err}). The previous configuration is active; the change is not applied."
            ).format(gen=rollback.get("failed_generation"), err=rollback.get("error"))
        fields = _SafeFields(
            generation=lifecycle.generation,
            reasons="; ".join(state.get("reasons") or ["unspecified"]),
            rollback=rollback_note,
        )
        try:
            message = self.config.resume_message.format_map(fields)
        except (ValueError, IndexError):
            self.ctx.logger.warning("resume_message: invalid format string; default in use")
            message = DEFAULT_RESUME.format_map(fields)
        for session_id in state.get("resume") or []:
            try:
                if await self.get_session(session_id) is None:
                    continue
                if await self.pending(session_id):
                    self.ctx.logger.info("session %s: pending approvals; no continuation", session_id)
                    continue
                self.ctx.logger.info("continuing session %s after restart", session_id)
                self.start_run(
                    session_id,
                    message,
                    kind="continuation",
                    marker={
                        "kind": "continuation",
                        "generation": lifecycle.generation,
                        "reasons": list(state.get("reasons") or []),
                        "rollback": rollback is not None,
                        "rollback_error": (rollback or {}).get("error"),
                    },
                )
            except Exception:
                self.ctx.logger.exception("could not continue session %s after restart", session_id)


class _SafeFields(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


__all__ = ["AgentConfig", "AgentService", "RestartPending", "RunHandle", "SessionBusy", "Turn", "serialize_message"]
