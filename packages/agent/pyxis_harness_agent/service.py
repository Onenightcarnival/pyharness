from __future__ import annotations

import asyncio
import time
import uuid
from string import Template
from typing import Any, ClassVar

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from pyxis_harness import Service, package_prompts
from pyxis_harness_llm import CONTINUABLE_CODES, failure_code

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
APPROVALS = ("pyharness", "approvals")  # session id -> {"deadline"}: tool approvals that wait under a time limit
PROMPTS = package_prompts(__file__)

DEFAULT_RESUME: str = PROMPTS["service"]["DEFAULT_RESUME"]


class AgentConfig(BaseModel):
    resume_on_restart: bool = Field(True, description="Send a continuation message to listed sessions after a restart.")
    resume_message: str = Field(
        DEFAULT_RESUME, description="Continuation message; placeholders ${generation}, ${reasons}, ${rollback}."
    )
    title_chars: int = 60
    approval_timeout: float | None = Field(
        None, gt=0, description="Seconds a tool approval waits for a decision before it is rejected; None: no limit."
    )
    max_steps: int | None = Field(
        None, gt=0, description="Model calls of the main agent in one turn; the turn pauses there. None: no limit."
    )
    temporary_ttl: float | None = Field(
        86_400.0,
        gt=0,
        description="Seconds a temporary session stays after its last turn; None: until it is deleted or a restart.",
    )


SWEEP_SECONDS = 300.0  # longest wait between two sweeps of expired temporary sessions
STEP_LIMIT = "STEP_LIMIT"
CONTINUABLE = (*CONTINUABLE_CODES, STEP_LIMIT)  # failure codes a turn can be continued from


class StepLimit(RuntimeError):
    """The turn reached ``max_steps``: it stops before the next model call and can be continued."""

    code = STEP_LIMIT


def rejectable(interrupts: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """
    Action requests of the pending tool approval; ``None`` unless that approval is the only pending interrupt and
    each of its calls can be rejected.
    """
    if len(interrupts) != 1 or not isinstance(interrupts[0].get("value"), dict):
        return None
    value = interrupts[0]["value"]
    requests, configs = value.get("action_requests") or [], value.get("review_configs") or []
    if not requests or any("reject" not in (c.get("allowed_decisions") or []) for c in configs):
        return None
    return requests


class AgentService(Service):
    """Sessions, runs, approvals, post-restart continuation."""

    key = "agents"
    name = "pyxis-harness-agent"
    inject: ClassVar[list[str]] = ["agentLoop", "store"]
    Config = AgentConfig

    def __init__(self, ctx: Any, config: AgentConfig) -> None:
        super().__init__(ctx, config)
        self.graph: Any = None
        self._chat_graph: Any = None  # the graph of temporary sessions
        self._graphs: dict[tuple[str | None, str, str], Any] = {}
        self._runs: dict[str, RunHandle] = {}
        self._turn_seq: dict[str, int] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._deadlines: dict[str, float] = {}  # session id -> when its pending tool approval is rejected
        self._timers: dict[str, asyncio.Task[Any]] = {}

    async def start(self) -> None:
        self.ctx.define_event("agent/turn-start", "parallel", "listener(turn: Turn) at the start of a run.")
        self.ctx.define_event(
            "agent/turn-end", "parallel", "listener(turn: Turn) after a run settles; turn.outcome is set."
        )
        self.ctx.define_event(
            "agent/session-delete", "parallel", "listener(session: dict) before a session's records are removed."
        )
        self.ctx.on("app/ready", self._build)
        self.ctx.on("agent/model-retry", self._on_model_retry)
        self.ctx.on("agent/model-request", self._limit_steps)
        self.ctx.on("app/started", self._resume_after_restart)
        self.ctx.on("app/started", self._restore_deadlines)
        self.ctx.on("app/started", self._sweep_temporary)
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
        """
        Graph for the session's workspace, mode and preset; the default graph when the loop has no variants.
        A temporary session: the chat graph.
        """
        loop = self.ctx.agentLoop
        if record is not None and record.get("temporary"):
            return await self._chat()
        if record is None or not hasattr(loop, "preset"):
            return self._require_graph()
        workspace = record.get("workspace") or None
        mode = loop.mode(record.get("mode"))
        preset = loop.preset(record.get("preset"))[0]
        key = (workspace, mode, preset)
        if key not in self._graphs:
            self._graphs[key] = await loop.build(workspace=workspace, mode=mode, preset=preset)
        return self._graphs[key]

    async def _chat(self) -> Any:
        if self._chat_graph is None:
            self._chat_graph = await self.ctx.agentLoop.build_chat()
        return self._chat_graph

    def invalidate_graphs(self) -> None:
        self._graphs.clear()
        self._chat_graph = None

    def _require_graph(self) -> Any:
        if self.graph is None:
            raise RuntimeError("agent graph unavailable before app/ready")
        return self.graph

    # ------------------------------------------------------------------ persistence of a session
    async def is_temporary(self, session_id: str) -> bool:
        """Whether the session is a temporary one: its record lives in ``ctx.temporary``."""
        temporary = self.ctx.get("temporary", None)
        return temporary is not None and await temporary.store.aget(NAMESPACE, session_id) is not None

    async def store_for(self, session_id: str) -> Any:
        """Store of the session's records: ``ctx.temporary.store`` for a temporary session, else ``ctx.store``."""
        return self.ctx.temporary.store if await self.is_temporary(session_id) else self.ctx.store

    async def _state(self, session_id: str) -> Any:
        """State of the session's thread, read from the checkpointer that holds it."""
        graph = await self._chat() if await self.is_temporary(session_id) else self._require_graph()
        return await graph.aget_state(self._config(session_id))

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
        temporary: bool = False,
    ) -> dict[str, Any]:
        """
        New session; ``workspace`` (root directory), ``mode`` and ``preset`` are validated and defaulted by their
        services.

        ``temporary``: a chat without workspace, permission mode or preset. Its thread and records live in
        ``ctx.temporary``; it is deleted on request, ``temporary_ttl`` after its last turn, and with the process.
        """
        if temporary and self.ctx.get("temporary", None) is None:
            raise ValueError("temporary sessions need the `temporary` service (entry checkpoint-temporary)")
        if temporary and (workspace or mode or preset):
            raise ValueError("a temporary session has no workspace, permission mode or preset")
        loop = self.ctx.get("agentLoop", None)
        workspaces = self.ctx.get("workspace", None)
        if not temporary and workspaces is not None and hasattr(workspaces, "open"):
            ws = workspaces.open(workspace)
            workspace = None if ws is workspaces.default else str(ws.root)
            await workspaces.remember(workspace)
        if not temporary and loop is not None and hasattr(loop, "mode"):
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
            "temporary": temporary,
        }
        await self._store(record).aput(NAMESPACE, record["id"], record)
        return record

    def _store(self, record: dict[str, Any]) -> Any:
        return self.ctx.temporary.store if record.get("temporary") else self.ctx.store

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        item = await (await self.store_for(session_id)).aget(NAMESPACE, session_id)
        return dict(item.value) if item is not None else None

    async def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Sessions, most recently updated first: the stored ones and the temporary ones (``temporary: true``)."""
        temporary = self.ctx.get("temporary", None)
        items = await self.ctx.store.asearch(NAMESPACE, limit=limit)
        if temporary is not None:
            items = [*items, *await temporary.store.asearch(NAMESPACE, limit=limit)]
        rows = [dict(item.value) | {"busy": self.busy(item.key)} for item in items]
        return sorted(rows, key=lambda r: r.get("updated_at") or 0, reverse=True)

    async def set_model(self, session_id: str, model: str | None) -> dict[str, Any] | None:
        """Select ``model`` (``route:model``; ``None`` = the default) for the session's next requests."""
        return await self._set(session_id, "model", model or None)

    async def set_title(self, session_id: str, title: str | None) -> dict[str, Any] | None:
        """Rename the session; empty keeps automatic titling from the next message."""
        return await self._set(session_id, "title", (title or "").strip()[: self.config.title_chars] or None)

    async def set_mode(self, session_id: str, mode: str | None) -> dict[str, Any] | None:
        """Switch the permission mode; takes effect on the next run. A temporary session has none."""
        await self._with_workspace(session_id)
        return await self._set(session_id, "mode", self.ctx.agentLoop.mode(mode))

    async def set_preset(self, session_id: str, preset: str | None) -> dict[str, Any] | None:
        """Switch the agent preset; takes effect on the next run. A temporary session has none."""
        await self._with_workspace(session_id)
        return await self._set(session_id, "preset", self.ctx.agentLoop.preset(preset)[0])

    async def _with_workspace(self, session_id: str) -> None:
        if await self.is_temporary(session_id):
            raise ValueError("a temporary session has no workspace, permission mode or preset")

    async def _set(self, session_id: str, field: str, value: Any) -> dict[str, Any] | None:
        record = await self.get_session(session_id)
        if record is None:
            return None
        record[field] = value
        await self._store(record).aput(NAMESPACE, session_id, record)
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
        await self._store(record).aput(NAMESPACE, session_id, record)

    async def turns(self, session_id: str) -> list[dict[str, Any]]:
        """Per-turn records (stats and trajectory), oldest first."""
        items = await (await self.store_for(session_id)).asearch((*TURNS, session_id), limit=10000)
        return sorted((dict(i.value) for i in items), key=lambda t: t.get("seq", 0))

    async def _next_turn_seq(self, session_id: str) -> int:
        if session_id not in self._turn_seq:
            self._turn_seq[session_id] = len(await self.turns(session_id))
        self._turn_seq[session_id] += 1
        return self._turn_seq[session_id]

    async def messages(self, session_id: str) -> list[dict[str, Any]]:
        state = await self._state(session_id)
        return [serialize_message(m) for m in (state.values or {}).get("messages", [])]

    async def pending(self, session_id: str) -> list[dict[str, Any]]:
        state = await self._state(session_id)
        return [{"id": i.id, "value": _jsonable(i.value)} for i in (state.interrupts or ())]

    async def failure(self, session_id: str) -> dict[str, Any] | None:
        """
        The failure the session stopped on: ``{"run_id", "code", "message", "continuable"}`` when its last turn
        ended with outcome ``error``; ``None`` otherwise and while a turn runs.

        ``continuable``: the failure code is one of ``CONTINUABLE`` (a continuable model failure, or the step
        limit) and the graph stopped inside a step, so ``retry_run`` resumes it.
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
        if code in CONTINUABLE:
            state = await self._state(session_id)
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

    async def publish(self, session_id: str | None, event: dict[str, Any]) -> bool:
        """Publish ``event`` on the session's running turn; returns whether one is running."""
        handle = self._runs.get(session_id) if session_id else None
        if handle is None or handle.done:
            return False
        if handle.recorder is not None:
            handle.recorder.observe_event(event)
        await handle.publish(event)
        return True

    async def _limit_steps(self, call: Any, next: Any) -> Any:
        """Before a model call of the main agent: stop the turn that has made ``max_steps`` of them."""
        handle = self._runs.get(call.session_id) if call.session_id else None
        limit = self.config.max_steps
        counted = handle is not None and handle.recorder is not None and not call.meta.get("subagent")
        if limit and counted and handle.recorder.stats["steps"] >= limit:
            raise StepLimit(f"the turn reached its limit of {limit} steps")
        return await next()

    def set_max_steps(self, steps: int | None) -> int | None:
        """Change the step limit of turns (live; a running turn follows it); the settings API persists it."""
        if steps is not None and steps <= 0:
            raise ValueError("max_steps is a positive number of model calls, or null for no limit")
        self.config.max_steps = steps
        return steps

    async def _on_model_retry(self, retry: Any) -> None:
        await self.publish(
            retry.session_id,
            {
                "type": "retry",
                "attempt": retry.attempt,
                "max_retries": retry.max_retries,
                "code": retry.code,
                "message": retry.message,
                "delay_ms": retry.delay_ms,
            },
        )

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
        """
        Delete the session's metadata and checkpointed history; returns whether it existed.

        ``agent/session-delete`` runs first: listeners remove what they keep of the session.
        """
        if self.busy(session_id):
            raise SessionBusy(f"session {session_id} has a running turn")
        record = await self.get_session(session_id)
        if record is None:
            return False
        store = self._store(record)
        await self.ctx.parallel("agent/session-delete", record)
        await self._disarm(session_id)
        await store.adelete(NAMESPACE, session_id)
        for item in await store.asearch((*TURNS, session_id), limit=10000):
            await store.adelete((*TURNS, session_id), item.key)
        self._turn_seq.pop(session_id, None)
        checkpointer = (
            self.ctx.temporary.checkpointer if record.get("temporary") else self.ctx.get("checkpointer", None)
        )
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
                await self._disarm(session_id)
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
                    deadline = await self._deadline(session_id, interrupts)
                    await handle.publish(
                        {"type": "interrupt", "interrupts": interrupts, **({"deadline": deadline} if deadline else {})}
                    )
            except asyncio.CancelledError:
                outcome = "cancelled"
            except Exception as exc:
                outcome = "error"
                self.ctx.logger.exception("run %s of session %s failed", handle.id, session_id)
                error = {"code": failure_code(exc), "message": f"{type(exc).__name__}: {exc}"}
                await handle.publish({"type": "error", **error, "continuable": error["code"] in CONTINUABLE})
            finally:
                turn.outcome = outcome
                try:
                    record = recorder.finish(outcome, len(await self.messages(session_id)), error)
                    record["seq"] = await self._next_turn_seq(session_id)
                    await (await self.store_for(session_id)).aput((*TURNS, session_id), handle.id, record)
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
                self._arm(session_id)

    # ------------------------------------------------------------------ temporary sessions
    async def expire_temporary(self, now: float | None = None) -> list[str]:
        """Delete the temporary sessions whose last turn is ``temporary_ttl`` old; returns their ids."""
        temporary = self.ctx.get("temporary", None)
        ttl = self.config.temporary_ttl
        if temporary is None or ttl is None:
            return []
        before = (time.time() if now is None else now) - ttl
        expired = []
        for item in await temporary.store.asearch(NAMESPACE, limit=10000):
            if (item.value.get("updated_at") or 0) < before and not self.busy(item.key):
                await self.delete_session(item.key)
                expired.append(item.key)
        return expired

    async def _sweep_temporary(self) -> None:
        if self.ctx.get("temporary", None) is None:
            return
        task = asyncio.get_running_loop().create_task(self._sweep())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(min((self.config.temporary_ttl or SWEEP_SECONDS) / 4, SWEEP_SECONDS))
            try:
                expired = await self.expire_temporary()
            except Exception:  # pragma: no cover
                self.ctx.logger.exception("temporary sessions: sweep failed")
                continue
            if expired:
                self.ctx.logger.info("temporary sessions: %d expired", len(expired))

    # ------------------------------------------------------------------ approval time limit
    def approval_deadline(self, session_id: str) -> float | None:
        """Time (epoch seconds) at which the session's pending tool approval is rejected; ``None`` without one."""
        return self._deadlines.get(session_id)

    def set_approval_timeout(self, seconds: float | None) -> float | None:
        """Change the time limit of tool approvals raised from now on (live); the settings API persists it."""
        if seconds is not None and seconds <= 0:
            raise ValueError("approval_timeout is a positive number of seconds, or null for no limit")
        self.config.approval_timeout = seconds
        return seconds

    async def _deadline(self, session_id: str, interrupts: list[dict[str, Any]]) -> float | None:
        if self.config.approval_timeout is None or rejectable(interrupts) is None:
            return None
        deadline = time.time() + self.config.approval_timeout
        self._deadlines[session_id] = deadline
        await (await self.store_for(session_id)).aput(APPROVALS, session_id, {"deadline": deadline})
        return deadline

    def _arm(self, session_id: str) -> None:
        if session_id not in self._deadlines or session_id in self._timers:
            return
        task = asyncio.get_running_loop().create_task(self._expire(session_id, self._deadlines[session_id]))
        self._timers[session_id] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _disarm(self, session_id: str) -> None:
        timer = self._timers.pop(session_id, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        if self._deadlines.pop(session_id, None) is not None:
            await (await self.store_for(session_id)).adelete(APPROVALS, session_id)

    async def _expire(self, session_id: str, deadline: float) -> None:
        await asyncio.sleep(max(0.0, deadline - time.time()))
        requests = rejectable(await self.pending(session_id))
        if requests is None or self.busy(session_id):
            await self._disarm(session_id)
            return
        limit = f"{self.config.approval_timeout or 0:g} s"
        message = Template(PROMPTS["service"]["approval_timeout"]).substitute(limit=limit)
        try:
            self.start_run(session_id, decisions=[{"type": "reject", "message": message}] * len(requests))
        except RestartPending:  # the next generation restores the deadline and rejects
            self._timers.pop(session_id, None)
            return
        self.ctx.logger.info("session %s: approval of %d call(s) timed out; rejected", session_id, len(requests))

    async def _restore_deadlines(self) -> None:
        for item in await self.ctx.store.asearch(APPROVALS, limit=10000):
            if self.config.approval_timeout is None:
                await self.ctx.store.adelete(APPROVALS, item.key)
                continue
            self._deadlines[item.key] = float(item.value["deadline"])
            self._arm(item.key)

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
