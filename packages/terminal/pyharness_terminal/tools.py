"""LangChain tools over the terminal service: ``bash``, ``run_in_background`` and the ``job_*`` tools."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool
from langgraph.config import get_config

from .shell import clip

if TYPE_CHECKING:
    from .service import TerminalService


def _thread_id() -> str | None:
    try:
        return dict(get_config().get("configurable") or {}).get("thread_id")
    except Exception:
        return None


def bash_tool(service: TerminalService) -> Any:
    @tool("bash")
    async def bash(command: str, timeout: int | None = None) -> str:
        """Run a bash command in this session's persistent shell. The working directory and environment variables
        persist between calls (the shell starts in the workspace root); stdin is /dev/null. Returns stdout and
        stderr with the exit code; long output is clipped. `timeout` is in seconds (default 120). For commands
        that run longer than a few minutes or servers, use run_in_background instead."""
        if not command.strip():
            return "Error: command must be a non-empty string."
        r = await service.run(command, session_id=_thread_id(), timeout=timeout)
        body = clip(r["output"], service.config.max_output_chars)
        if r["timed_out"]:
            return (
                f"{body}\n\n[timed out after {min(timeout or service.config.timeout, service.config.max_timeout)}s; "
                f"the shell was killed and restarts in {r['cwd']}. Use run_in_background for long commands.]"
            )
        if r["exit_code"] is None:
            return f"{body}\n\n[the shell exited; a new one starts in {r['cwd']} on the next call]"
        return (
            f"{body}\n\n[exit code {r['exit_code']}; cwd {r['cwd']}]"
            if body
            else f"[exit code {r['exit_code']}; cwd {r['cwd']}; no output]"
        )

    return bash


def background_tool(service: TerminalService) -> Any:
    @tool("run_in_background")
    async def run_in_background(command: str, name: str | None = None) -> str:
        """Start a long-running bash command (a build, a test suite, a dev server) as a background job in the
        shell's current directory and return its job id at once. Read its output later with job_output, list
        jobs with job_list, stop it with job_kill. Output goes to a log file, not to the chat."""
        if not command.strip():
            return "Error: command must be a non-empty string."
        job = await service.start_job(command, session_id=_thread_id(), name=name)
        return json.dumps(
            {"job_id": job.id, "name": job.name, "cwd": job.cwd, "status": job.status, "log": str(job.log)}
        )

    return run_in_background


def job_tools(service: TerminalService) -> list[Any]:
    @tool("job_output")
    async def job_output(job_id: str, tail_lines: int | None = None, wait: bool = False, timeout: int = 60) -> str:
        """Read a background job's output (the last `tail_lines` lines, default 200) and its status. With `wait`
        the call blocks until the job finishes or `timeout` seconds pass; a timed-out wait leaves it running."""
        job = service.jobs.get(job_id)
        if job is None:
            return f"Error: no job {job_id}. job_list shows the known jobs."
        if wait and job.ended_at is None:
            await service.jobs.wait(job, min(timeout, service.config.max_timeout))
        text = clip(job.read(tail_lines=tail_lines or service.config.job_tail_lines), service.config.max_output_chars)
        info = job.describe()
        status = info["status"] + (f" (exit code {info['exit_code']})" if info["exit_code"] is not None else "")
        return (
            f"[job {job.id} {job.name!r}: {status}]\n{text}"
            if text
            else f"[job {job.id} {job.name!r}: {status}; no output yet]"
        )

    @tool("job_list")
    async def job_list() -> str:
        """List background jobs (running and finished) with their ids, names and statuses."""
        jobs = service.jobs.list()
        if not jobs:
            return "No background jobs."
        return "\n".join(
            f"{j.id}  {j.status:<8} {j.name}  (started {time.strftime('%H:%M:%S', time.localtime(j.started_at))})"
            for j in jobs
        )

    @tool("job_kill")
    async def job_kill(job_id: str) -> str:
        """Stop a running background job."""
        if await service.jobs.kill(job_id):
            return f"job {job_id} stopped"
        return f"job {job_id} is not running" if service.jobs.get(job_id) else f"Error: no job {job_id}"

    return [job_output, job_list, job_kill]
