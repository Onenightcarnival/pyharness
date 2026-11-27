from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .config import Config
from .jobs import JobRegistry
from .pty import Terminal, pty_available


class Host(Protocol):
    """The service, as the routes use it."""

    ctx: Any
    config: Config
    jobs: JobRegistry
    terminals: dict[str, Terminal]

    def status(self) -> dict[str, Any]: ...
    def settings(self) -> dict[str, Any]: ...
    async def save(self, fields: dict[str, Any]) -> dict[str, Any]: ...
    def open_terminal(self, cwd: str | None, cols: int = 80, rows: int = 24, title: str | None = None) -> Terminal: ...
    async def close_terminal(self, terminal_id: str) -> bool: ...


class NewTerminal(BaseModel):
    workspace: str | None = None
    cols: int = Field(80, ge=2, le=500)
    rows: int = Field(24, ge=1, le=300)
    title: str | None = None


class ShellSettings(BaseModel):
    """Settings of the shell tool; a field left out keeps its value."""

    timeout: int | None = Field(None, ge=1)
    max_output_chars: int | None = Field(None, ge=1000)
    promote_on_timeout: bool | None = None
    dialect: str | None = Field(None, pattern="^(auto|bash|pwsh)$")  # auto: by platform
    shell: str | None = Field(None, min_length=1)
    pwsh: str | None = None  # empty: resolved by the fixed order


class Resize(BaseModel):
    cols: int = Field(ge=2, le=500)
    rows: int = Field(ge=1, le=300)


def make_router(service: Host) -> APIRouter:
    router = APIRouter()

    @router.get("/terminal/status")
    async def terminal_status() -> dict[str, Any]:
        return service.status()

    @router.get("/terminal/settings")
    async def shell_settings() -> dict[str, Any]:
        return service.settings()

    @router.put("/terminal/settings")
    async def put_shell_settings(body: ShellSettings) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True, exclude_none=True)
        if "dialect" in fields:
            fields["dialect"] = None if fields["dialect"] == "auto" else fields["dialect"]
        if "pwsh" in body.model_fields_set:
            fields["pwsh"] = body.pwsh or None
        try:
            return await service.save(fields)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/jobs")
    async def list_jobs(session: str | None = None) -> dict[str, Any]:
        return {"jobs": [j.describe() for j in service.jobs.list(session)]}

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str, tail: int = 200) -> dict[str, Any]:
        job = service.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id}")
        return {**job.describe(), "output": job.read(tail_lines=max(1, min(tail, 5000)))}

    @router.delete("/jobs/{job_id}")
    async def kill_job(job_id: str) -> dict[str, Any]:
        job = service.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id}")
        return {"killed": await service.jobs.kill(job_id), **job.describe()}

    @router.get("/terminals")
    async def list_terminals() -> dict[str, Any]:
        return {
            "terminals": [t.describe() for t in service.terminals.values()],
            "available": pty_available() and service.config.terminal_tab,
        }

    @router.post("/terminals")
    async def new_terminal(body: NewTerminal) -> dict[str, Any]:
        if not service.config.terminal_tab:
            raise HTTPException(409, "terminals are disabled in the terminal plugin configuration")
        workspaces = service.ctx.get("workspace", None)
        cwd = body.workspace
        if cwd and workspaces is not None and hasattr(workspaces, "open"):
            try:
                cwd = str(workspaces.open(cwd).root)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(422, str(exc)) from None
        try:
            term = service.open_terminal(cwd, body.cols, body.rows, body.title)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        return term.describe()

    @router.post("/terminals/{terminal_id}/resize")
    async def resize_terminal(terminal_id: str, body: Resize) -> dict[str, Any]:
        term = service.terminals.get(terminal_id)
        if term is None:
            raise HTTPException(404, f"no terminal {terminal_id}")
        term.resize(body.cols, body.rows)
        return term.describe()

    @router.delete("/terminals/{terminal_id}")
    async def close_terminal(terminal_id: str) -> dict[str, Any]:
        if not await service.close_terminal(terminal_id):
            raise HTTPException(404, f"no terminal {terminal_id}")
        return {"closed": True}

    @router.websocket("/terminals/{terminal_id}/ws")
    async def terminal_socket(ws: WebSocket, terminal_id: str) -> None:
        term = service.terminals.get(terminal_id)
        if term is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        if term.buffer:
            await ws.send_bytes(bytes(term.buffer))
        if not term.alive:
            await ws.send_text(json.dumps({"type": "exit", "code": term.exit_code}))
            await ws.close()
            return
        queue = term.subscribe()

        async def pump() -> None:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    await ws.send_text(json.dumps({"type": "exit", "code": term.exit_code}))
                    return
                await ws.send_bytes(chunk)

        pump_task = asyncio.get_running_loop().create_task(pump())
        try:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    term.write(message["bytes"])
                elif message.get("text"):
                    try:
                        control = json.loads(message["text"])
                    except ValueError:
                        term.write(message["text"].encode())
                        continue
                    if control.get("type") == "resize":
                        term.resize(int(control.get("cols") or term.cols), int(control.get("rows") or term.rows))
                    elif control.get("type") == "input":
                        term.write(str(control.get("data") or "").encode())
        except WebSocketDisconnect:
            pass
        finally:
            term.unsubscribe(queue)
            pump_task.cancel()
            with contextlib.suppress(BaseException):
                await pump_task

    return router
