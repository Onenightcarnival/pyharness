from __future__ import annotations

import json
import time
from string import Template
from typing import Any, Protocol

from langchain_core.tools import tool
from langgraph.config import get_config
from pydantic import Field, create_model

from pyxis_harness import package_prompts

from .config import Config
from .jobs import Job, JobRegistry
from .shell import Shell, tail


class Host(Protocol):
    """The service, as the tools use it."""

    config: Config
    jobs: JobRegistry
    shell: Shell

    @property
    def background(self) -> bool: ...
    async def run(
        self, command: str, *, session_id: str | None = None, timeout: int | None = None, workdir: str | None = None
    ) -> dict[str, Any]: ...
    async def start_job(
        self, command: str, *, session_id: str | None = None, workdir: str | None = None, name: str | None = None
    ) -> Job: ...


PROMPTS = package_prompts(__file__)
MARKERS = {name: Template(text) for name, text in PROMPTS["markers"].items()}


def _thread_id() -> str | None:
    try:
        return dict(get_config().get("configurable") or {}).get("thread_id")
    except RuntimeError:  # no run in progress
        return None


def render(result: dict[str, Any]) -> str:
    """A foreground result as the model reads it: the output, then one marker line per fact."""
    marks = [
        ("truncated", result["truncated"], {"log": result["log"]}),
        ("promoted", result["job_id"] is not None, {"seconds": result["timeout"], "job": result["job_id"]}),
        ("timed_out", result["timed_out"], {"seconds": result["timeout"]}),
        ("stopped", result["stopped"], {}),
        ("signal", result["signal"] is not None, {"signal": result["signal"]}),
        ("exit_code", result["signal"] is None and result["exit_code"] not in (0, None), {"code": result["exit_code"]}),
    ]
    lines = [MARKERS[name].substitute(values) for name, shown, values in marks if shown]
    body = result["output"].rstrip("\n") or MARKERS["empty"].substitute()
    return "\n".join([body, *lines])


def shell_args(config: Config, background: bool) -> Any:
    """Arguments of the shell tool; ``run_in_background`` and ``name`` exist only with background jobs."""
    texts = PROMPTS["args"]
    timeout = texts["timeout_promote" if background and config.promote_on_timeout else "timeout_kill"]
    fields: dict[str, Any] = {
        "command": (str, Field(description=texts["command"])),
        "timeout": (
            int | None,
            Field(None, description=Template(timeout).substitute(default=config.timeout, max=config.max_timeout)),
        ),
        "workdir": (str | None, Field(None, description=texts["workdir"])),
    }
    if background:
        fields["run_in_background"] = (bool, Field(False, description=texts["run_in_background"]))
        fields["name"] = (str | None, Field(None, description=texts["name"]))
    return create_model("ShellArgs", **fields)


def shell_tool(service: Host) -> Any:
    """The ``bash`` or ``pwsh`` tool: one command, one fresh shell."""

    @tool(
        service.shell.dialect,
        description=PROMPTS["tools"][service.shell.dialect],
        args_schema=shell_args(service.config, service.background),
    )
    async def shell(
        command: str,
        timeout: int | None = None,
        workdir: str | None = None,
        run_in_background: bool = False,
        name: str | None = None,
    ) -> str:
        if not command.strip():
            return "Error: command must be a non-empty string."
        try:
            if run_in_background:
                job = await service.start_job(command, session_id=_thread_id(), workdir=workdir, name=name)
                return json.dumps(
                    {"job_id": job.id, "name": job.name, "cwd": job.cwd, "status": job.status, "log": str(job.log)}
                )
            return render(await service.run(command, session_id=_thread_id(), timeout=timeout, workdir=workdir))
        except (ValueError, OSError) as exc:  # no such workdir, no such shell
            return f"Error: {exc}"

    return shell


def job_tools(service: Host) -> list[Any]:
    @tool("job_output", description=PROMPTS["tools"]["job_output"])
    async def job_output(job_id: str, tail_lines: int | None = None, wait: bool = False, timeout: int = 60) -> str:
        job = service.jobs.get(job_id)
        if job is None:
            return f"Error: no job {job_id}. job_list shows the known jobs."
        if wait and job.ended_at is None:
            await service.jobs.wait(job, min(timeout, service.config.max_timeout))
        lines = job.read(tail_lines=tail_lines or service.config.job_tail_lines)
        text, cut = tail(lines, service.config.max_output_chars)
        if cut:
            text = f"{text.rstrip(chr(10))}\n{MARKERS['truncated'].substitute(log=job.log)}"
        info = job.describe()
        status = info["status"] + (f" (exit code {info['exit_code']})" if info["exit_code"] is not None else "")
        return (
            f"[job {job.id} {job.name!r}: {status}]\n{text}"
            if text
            else f"[job {job.id} {job.name!r}: {status}; no output yet]"
        )

    @tool("job_list", description=PROMPTS["tools"]["job_list"])
    async def job_list() -> str:
        jobs = service.jobs.list()
        if not jobs:
            return "No background jobs."
        return "\n".join(
            f"{j.id}  {j.status:<8} {j.name}  (started {time.strftime('%H:%M:%S', time.localtime(j.started_at))})"
            for j in jobs
        )

    @tool("job_kill", description=PROMPTS["tools"]["job_kill"])
    async def job_kill(job_id: str) -> str:
        if await service.jobs.kill(job_id):
            return f"job {job_id} stopped"
        return f"job {job_id} is not running" if service.jobs.get(job_id) else f"Error: no job {job_id}"

    return [job_output, job_list, job_kill]
