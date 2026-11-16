from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from pyharness_agent import NotContinuable, RestartPending, SessionBusy

from . import references
from .highlight import escaped_lines, lines as highlighted_lines
from .models import (
    Approvals,
    NewMessage,
    NewSession,
    QuestionAnswers,
    SessionMode,
    SessionModel,
    SessionPreset,
    SessionTitle,
)

try:
    from pyharness_ask_user import normalize_answers
except ImportError:  # optional plugin package; the answers route answers 503 without it
    normalize_answers = None


def _sse(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        async for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def build_sessions_router(ctx: Any) -> APIRouter:
    router = APIRouter()
    agents = ctx.agents

    async def require(session_id: str) -> dict[str, Any]:
        session = await agents.get_session(session_id)
        if session is None:
            raise HTTPException(404, f"no session {session_id}")
        return session

    @router.get("/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return await agents.list_sessions()

    @router.post("/sessions")
    async def create_session(body: NewSession | None = None) -> dict[str, Any]:
        body = body or NewSession()
        try:
            return await agents.create_session(
                title=body.title, model=body.model, workspace=body.workspace, mode=body.mode, preset=body.preset
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.put("/sessions/{session_id}")
    async def rename_session(session_id: str, body: SessionTitle) -> dict[str, Any]:
        record = await agents.set_title(session_id, body.title)
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.put("/sessions/{session_id}/model")
    async def set_session_model(session_id: str, body: SessionModel) -> dict[str, Any]:
        record = await agents.set_model(session_id, body.model)
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.put("/sessions/{session_id}/mode")
    async def set_session_mode(session_id: str, body: SessionMode) -> dict[str, Any]:
        try:
            record = await agents.set_mode(session_id, body.mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.put("/sessions/{session_id}/preset")
    async def set_session_preset(session_id: str, body: SessionPreset) -> dict[str, Any]:
        try:
            record = await agents.set_preset(session_id, body.preset)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        session = await require(session_id)
        changes = ctx.get("workspaceChanges", None)
        llm = ctx.get("llm", None)
        return {
            **session,
            "busy": agents.busy(session_id),
            "messages": await agents.messages(session_id),
            "pending": await agents.pending(session_id),
            "approval_deadline": agents.approval_deadline(session_id),
            "failure": await agents.failure(session_id),
            "changes": await changes.summaries(session_id) if changes is not None else [],
            "turns": await agents.turns(session_id),
            "context_window": llm.context_window(session.get("model"))
            if llm is not None and hasattr(llm, "context_window")
            else None,
        }

    @router.get("/sessions/{session_id}/turns")
    async def session_turns(session_id: str) -> dict[str, Any]:
        """Per-turn records: stats (steps, tokens, wall time) and the trajectory (user, step, tool, end)."""
        await require(session_id)
        return {"turns": await agents.turns(session_id)}

    @router.get("/sessions/{session_id}/changes")
    async def session_changes(session_id: str) -> dict[str, Any]:
        """Changed-file summaries of the session's turns (``pyharness-workspace-changes``)."""
        await require(session_id)
        changes = ctx.get("workspaceChanges", None)
        return {"changes": await changes.summaries(session_id) if changes is not None else []}

    @router.get("/sessions/{session_id}/changes/{run_id}/diff")
    async def session_changes_diff(session_id: str, run_id: str, index: int = 0) -> dict[str, Any]:
        """Hunks of one listed file with highlighted lines; ``available: false`` after a restart."""
        await require(session_id)
        changes = ctx.get("workspaceChanges", None)
        if changes is None:
            raise HTTPException(503, "workspace changes unavailable")
        try:
            diff = await changes.diff(session_id, run_id, index)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        name = diff["path"].rsplit("/", 1)[-1]
        for hunk in diff.get("hunks", []):
            for side, kinds in (("old", ("ctx", "del")), ("new", ("ctx", "add"))):
                rows = [line for line in hunk["lines"] if line["kind"] in kinds]
                text = "\n".join(line["text"] for line in rows)
                html = await asyncio.to_thread(highlighted_lines, text, None, name) or escaped_lines(text)
                for line, markup in zip(rows, html, strict=False):
                    if side == "new" or line["kind"] == "del":
                        line["html"] = markup
        return diff

    @router.post("/sessions/{session_id}/messages")
    async def post_message(session_id: str, body: NewMessage) -> StreamingResponse:
        session = await require(session_id)
        if await agents.pending(session_id):
            raise HTTPException(409, "the session is waiting for approval decisions")
        if body.images:
            llm = ctx.get("llm", None)
            spec = session.get("model") or (llm.default if llm is not None else None)
            if llm is not None and llm.accepts_images(spec) is False:
                raise HTTPException(
                    422,
                    f"model {spec} does not accept image input; "
                    "choose a model with image input or edit its input types in Settings",
                )
        content = body.content
        refs: list[dict[str, Any]] = []
        workspaces = ctx.get("workspace", None)
        if workspaces is not None and hasattr(workspaces, "open") and "@" in content:
            try:
                content, refs = references.expand(content, workspaces.open(session.get("workspace")))
            except Exception:
                ctx.logger.exception("expanding @references failed")
        try:
            handle = agents.start_run(session_id, content, images=body.images or None)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        if refs:  # tells the page which @references travelled with the message
            await handle.publish({"type": "references", "refs": refs})
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/approvals")
    async def post_approvals(session_id: str, body: Approvals) -> StreamingResponse:
        await require(session_id)
        if not await agents.pending(session_id):
            raise HTTPException(409, "nothing is waiting for approval")
        try:
            handle = agents.start_run(session_id, decisions=body.decisions)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/compact")
    async def post_compact(session_id: str) -> StreamingResponse:
        """
        Manual compaction: a run of kind ``compact`` whose stream carries ``compact`` (when history was replaced)
        and ``done``.
        """
        await require(session_id)
        if ctx.get("compaction", None) is None:
            raise HTTPException(503, "compaction plugin unavailable")
        if await agents.pending(session_id):
            raise HTTPException(409, "the session is waiting for approval decisions")
        try:
            handle = agents.start_run(
                session_id, "/compact", kind="compact", marker={"kind": "command", "name": "compact"}
            )
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/retry")
    async def post_retry(session_id: str) -> StreamingResponse:
        """
        Continue the failed last turn: a run of kind ``retry`` that resumes the step that failed, without a new
        message (SSE like a message). 409 unless the session's ``failure`` is ``continuable``.
        """
        await require(session_id)
        try:
            handle = await agents.retry_run(session_id)
        except (SessionBusy, NotContinuable) as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/answers")
    async def post_answers(session_id: str, body: QuestionAnswers) -> StreamingResponse:
        """Answer the pending ``ask_user_question`` and resume the run (SSE like a message)."""
        await require(session_id)
        pending = [
            i
            for i in await agents.pending(session_id)
            if isinstance(i.get("value"), dict) and i["value"].get("kind") == "ask_user"
        ]
        if not pending:
            raise HTTPException(409, "no question is waiting for an answer")
        target = next((i for i in pending if body.interrupt_id in (None, i["id"])), None)
        if target is None:
            raise HTTPException(409, f"no pending question with interrupt id {body.interrupt_id!r}")
        if normalize_answers is None:
            raise HTTPException(503, "ask-user plugin unavailable")
        try:
            answers = normalize_answers(target["value"].get("questions") or [], body.answers)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        try:
            handle = agents.start_run(session_id, resume={target["id"]: {"answers": answers}})
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/cancel")
    async def cancel(session_id: str) -> dict[str, Any]:
        await require(session_id)
        return {"cancelled": await agents.cancel(session_id)}

    @router.delete("/sessions/{session_id}")
    async def delete(session_id: str) -> dict[str, Any]:
        try:
            deleted = await agents.delete_session(session_id)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        if not deleted:
            raise HTTPException(404, f"no session {session_id}")
        return {"deleted": True}

    @router.get("/sessions/{session_id}/stream", response_model=None)
    async def attach(session_id: str) -> Response:
        await require(session_id)
        handle = agents.current_run(session_id)
        if handle is None or handle.done:
            return Response(status_code=204)
        return _sse(handle.subscribe())

    return router
