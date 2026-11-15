"""``AgentService`` (``ctx.agents``): session records, per-session graphs, runs and the post-restart continuation."""

from __future__ import annotations

import asyncio
import time
import uuid
from string import Template
from typing import Any, ClassVar

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from pyharness import Service, package_prompts
from pyharness_llm import CONTINUABLE_CODES, failure_code

from .messages import (
    _checkpoint,
    _images,
    _iter_messages,
    _jsonable,
    _reasoning,
    _summary,
    _text,
    serialize_message,
    user_content,
)
from .runs import TURNS, NotContinuable, RestartPending, RunHandle, SessionBusy, Turn, TurnRecorder

NAMESPACE = ("pyharness", "sessions")
PROMPTS = package_prompts(__file__)

DEFAULT_RESUME: str = PROMPTS["service"]["DEFAULT_RESUME"]


class AgentConfig(BaseModel):
    resume_on_restart: bool = Field(True, description="Send a continuation message to listed sessions after a restart.")
    resume_message: str = Field(
        DEFAULT_RESUME, description="Continuation message; placeholders ${generation}, ${reasons}, ${rollback}."
    )
    title_chars: int = 60


class AgentService(Service):
    """Sessions, runs, approvals, post-restart continuation."""

    key = "agents"
    name = "pyharness-agent"
    inject: ClassVar[list[str]] = ["agentLoop", "store"]
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
        self.ctx.define_event(
            "agent/turn-end", "parallel", "listener(turn: Turn) after a run settles; turn.outcome is set."
        )
        self.ctx.on("app/ready", self._build)
        self.ctx.on("agent/model-retry", self._on_model_retry)
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
        """
        New session; ``workspace`` (root directory), ``mode`` and ``preset`` are validated and defaulted by their
        services.
        """
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
            record["title"] = (
                title_hint.strip().splitlines()[0][: self.config.title_chars] if title_hint.strip() else None
            )
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

    async def failure(self, session_id: str) -> dict[str, Any] | None:
        """
        The failure the session stopped on: ``{"run_id", "code", "message", "continuable"}`` when its last turn
        ended with outcome ``error``; ``None`` otherwise and while a turn runs.

        ``continuable``: the failure code is one of ``CONTINUABLE_CODES`` and the graph stopped inside a step, so
        ``retry_run`` resumes it.
        """
        if self.busy(session_id):
            return None
        turns = await self.turns(session_id)
        last = turns[-1] if turns else None
        if last is None or last.get("outcome") != "error":
            return None
        error = last.get("error") or {}
        code = error.get("code") or "UNKNOWN"
        continuable = False
        if code in CONTINUABLE_CODES:
            state = await self._require_graph().aget_state(self._config(session_id))
            continuable = bool(state.next) and not state.interrupts
        return {"run_id": last.get("run_id"), "code": code, "message": error.get("message"), "continuable": continuable}

    async def retry_run(self, session_id: str, *, model: str | None = None) -> RunHandle:
        """
        Continue the session's failed turn: a run of kind ``retry`` that resumes the graph at the step that
        failed, with no new message. Raises :class:`NotContinuable` unless ``failure()`` is continuable.
        """
        failure = await self.failure(session_id)
        if failure is None:
            raise NotContinuable(f"the last turn of session {session_id} did not fail")
        if not failure["continuable"]:
            raise NotContinuable(f"a turn that failed with {failure['code']} cannot be continued; send a new message")
        return self.start_run(session_id, kind="retry", model=model)

    async def _on_model_retry(self, retry: Any) -> None:
        handle = self._runs.get(retry.session_id) if retry.session_id else None
        if handle is None or handle.done:
            return
        event = {
            "type": "retry",
            "attempt": retry.attempt,
            "max_retries": retry.max_retries,
            "code": retry.code,
            "message": retry.message,
            "delay_ms": retry.delay_ms,
        }
        if handle.recorder is not None:
            handle.recorder.observe_event(event)
        await handle.publish(event)

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
        """
        Start a run and return its handle. ``model`` overrides the session's selection for this run;
        ``images`` are data URLs attached to the user message.

        | arguments                | input to the graph                                                 |
        |--------------------------|--------------------------------------------------------------------|
        | ``content``              | user message                                                       |
        | ``decisions``            | answers to the pending approvals                                   |
        | ``resume``               | ``{interrupt_id: value}`` resuming other interrupts (see below)    |
        | ``content`` + ``marker`` | user-role message tagged ``additional_kwargs["pyharness"]``        |

        ``resume`` carries ``ask_user_question`` answers. ``kind="retry"`` sends no input: the graph resumes at
        the step its last run failed in (see ``retry_run``).

        ``kind="compact"`` with ``marker={"kind": "command", "name": "compact"}`` runs a manual compaction: the
        compaction middleware replaces the history with a checkpoint and ends the run without a model call.
        """
        self._require_graph()
        if self.busy(session_id):
            raise SessionBusy(f"session {session_id} already has a running turn")
        if not self.ctx.lifecycle.accepting_work:
            raise RestartPending("restart pending: configuration change; retry later")
        if kind == "retry":
            payload: Any = None
        elif decisions is not None:
            payload = Command(resume={"decisions": decisions})
            kind = kind or "approval"
        elif resume is not None:
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
        recorder = handle.recorder = TurnRecorder(turn)
        outcome = "completed"
        error: dict[str, Any] | None = None
        async with lifecycle.hold(f"run:{session_id}", session=session_id):
            try:
                record = await self.get_session(session_id)
                if model is None:
                    model = (record or {}).get("model") or None
                turn.model = model
                graph = await self.graph_for(record)
                await self.ctx.parallel("agent/turn-start", turn)
                async for mode, chunk in graph.astream(
                    payload, self._config(session_id, model), stream_mode=["messages", "updates"]
                ):
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
                error = {"code": failure_code(exc), "message": f"{type(exc).__name__}: {exc}"}
                await handle.publish({"type": "error", **error, "continuable": error["code"] in CONTINUABLE_CODES})
            finally:
                turn.outcome = outcome
                try:
                    record = recorder.finish(outcome, len(await self.messages(session_id)), error)
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
                        out.append(
                            {
                                "type": "tool_call",
                                "id": tc.get("id"),
                                "name": tc["name"],
                                "args": _jsonable(tc.get("args", {})),
                            }
                        )
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
            note = Template(PROMPTS["service"]["rollback_note"])
            rollback_note = "\n" + note.substitute(gen=rollback.get("failed_generation"), err=rollback.get("error"))
        fields = _SafeFields(
            generation=lifecycle.generation,
            reasons="; ".join(state.get("reasons") or ["unspecified"]),
            rollback=rollback_note,
        )
        try:
            message = Template(self.config.resume_message).substitute(fields)
        except (ValueError, KeyError):
            self.ctx.logger.warning("resume_message: invalid template; default in use")
            message = Template(DEFAULT_RESUME).substitute(fields)
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
        return "${" + key + "}"
