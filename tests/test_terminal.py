"""Terminal plugin: the shell tool of each platform, process trees, background jobs, PTY terminals."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_terminal import (
    JobRegistry,
    Shell,
    Terminal,
    decode,
    pty_available,
    pwsh_candidates,
    resolve_pwsh,
    shell_of,
    tail,
)

HTTP_OFF = {"id": "http", "config": {"serve": False}}
posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX")
SHELL = shell_of(None, "bash", None)  # the shell of this host
# The same commands in each dialect.
COMMANDS = {
    "bash": {
        "both_streams": "echo hi; echo err >&2",
        "exit_3": "exit 3",
        "nothing": "true",
        "cwd": "pwd",
        "set_and_leave": "export PYH_T=1; mkdir -p sub; cd sub",
        "read_back": 'echo "[${PYH_T:-unset}]"',
        "non_ascii": "echo 中文",
        "many_lines": "seq 1 5000",
        "start_then_sleep": "echo start; sleep 30",
        "sleep": "sleep 30",
        "one_two": "echo one; sleep 0.3; echo two",
        "run": '"{program}" "{script}"',
    },
    "pwsh": {
        "both_streams": "Write-Output hi; [Console]::Error.WriteLine('err')",
        "exit_3": "exit 3",
        "nothing": "$null",
        "cwd": "(Get-Location).Path",
        "set_and_leave": "$env:PYH_T = '1'; New-Item -ItemType Directory -Force sub | Out-Null; Set-Location sub",
        "read_back": "if ($env:PYH_T) { \"[$env:PYH_T]\" } else { '[unset]' }",
        "non_ascii": "Write-Output '中文'",
        "many_lines": "1..5000",
        "start_then_sleep": "Write-Output start; Start-Sleep -Seconds 30",
        "sleep": "Start-Sleep -Seconds 30",
        "one_two": "Write-Output one; Start-Sleep -Milliseconds 300; Write-Output two",
        "run": '& "{program}" "{script}"',
    },
}[SHELL.dialect]
# A process that starts a child, prints the child's pid, and stays.
TREE = """\
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(child.pid, flush=True)
time.sleep(60)
"""


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        listed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False
        )
        return str(pid) in listed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def gone(pid: int, seconds: float = 5.0) -> bool:
    for _ in range(int(seconds / 0.1)):
        if not alive(pid):
            return True
        await asyncio.sleep(0.1)
    return False


async def output_of(job, text: str, seconds: float = 20.0) -> str:
    """The job's output once it contains ``text``."""
    for _ in range(int(seconds / 0.1)):
        if text in job.read() or job.ended_at is not None:
            break
        await asyncio.sleep(0.1)
    return job.read()


def test_the_shell_follows_the_platform():
    assert shell_of(None, "bash", None, "linux") == Shell("bash", "bash")
    assert shell_of(None, "/opt/bin/bash", None, "darwin").argv("ls") == ["/opt/bin/bash", "-c", "ls"]
    windows = shell_of(None, "bash", "C:\\ps\\pwsh.exe", "win32")
    assert windows.dialect == "pwsh" and windows.executable == "C:\\ps\\pwsh.exe"
    argv = windows.argv("Get-ChildItem")
    assert argv[:5] == ["C:\\ps\\pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
    assert argv[5].endswith("; Get-ChildItem") and "[Console]::OutputEncoding" in argv[5] and len(argv) == 6
    # The dialect is a choice: bash on Windows (Git Bash), PowerShell elsewhere.
    assert shell_of("bash", "C:\\Git\\bin\\bash.exe", None, "win32") == Shell("bash", "C:\\Git\\bin\\bash.exe")
    assert shell_of("pwsh", "bash", None, "linux") == Shell("pwsh", "pwsh")
    assert Shell("bash", "bash").environment({"A": "1", "TERM": "xterm"}) == {
        "A": "1",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PAGER": "cat",
        "GIT_PAGER": "cat",
    }
    assert "TERM" not in Shell("pwsh", "pwsh").environment({})


def test_powershell_resolution_order():
    env = {"ProgramFiles": "D:\\Programs", "SystemRoot": "C:\\Windows", "PATH": 'C:\\Tools;"C:\\My Apps\\ps";;'}
    seven = "D:\\Programs\\PowerShell\\7\\pwsh.exe"
    legacy = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    assert pwsh_candidates(env) == [seven, "C:\\Tools\\pwsh.exe", "C:\\My Apps\\ps\\pwsh.exe", legacy]
    assert resolve_pwsh(None, env, "win32", lambda path: True) == seven
    assert resolve_pwsh(None, env, "win32", lambda path: "My Apps" in path or path == legacy).startswith("C:\\My Apps")
    assert resolve_pwsh(None, env, "win32", lambda path: path == legacy) == legacy
    assert resolve_pwsh(None, env, "win32", lambda path: False) == "pwsh"
    assert resolve_pwsh("X:\\custom.exe", env, "win32", lambda path: True) == "X:\\custom.exe"
    assert resolve_pwsh(None, env, "linux", lambda path: True) == "pwsh"


def test_output_text():
    assert tail("short", 10) == ("short", False)
    assert tail("first line\n" + "x" * 30 + "\nlast\n", 40) == ("x" * 30 + "\nlast\n", True)  # from a line start
    assert tail("y" * 100, 20) == ("y" * 20, True)
    assert decode("中文".encode()) == "中文"
    assert decode(b"caf\xe9")  # bytes that are not UTF-8 still come out as text
    assert decode(b"one\r\ntwo\r\n") == "one\ntwo\n"


async def test_a_command_is_one_process_tree(tmp_path: Path):
    jobs = JobRegistry(tmp_path / "jobs", SHELL, grace=1.0)
    try:
        job = await jobs.start(COMMANDS["both_streams"], str(tmp_path), foreground=True)
        assert await jobs.wait(job, 30) and job.status == "exited" and job.exit_code == 0
        assert job.read().split() == ["hi", "err"] and job.tail(1000)[1] is False
        failed = await jobs.start(COMMANDS["exit_3"], str(tmp_path))
        assert await jobs.wait(failed, 30) and failed.status == "failed" and failed.exit_code == 3
        spoken = await jobs.start(COMMANDS["non_ascii"], str(tmp_path))
        assert await jobs.wait(spoken, 30) and spoken.read().strip() == "中文"
        # Stopping a job ends the processes it started, not only the shell.
        script = tmp_path / "tree.py"
        script.write_text(TREE, encoding="utf-8")
        tree = await jobs.start(COMMANDS["run"].format(program=sys.executable, script=script), str(tmp_path))
        child = int((await output_of(tree, "\n")).strip())
        assert alive(child)
        assert await jobs.kill(tree.id) and tree.status == "killed" and tree.ended_at is not None
        assert await gone(child)
        assert await jobs.kill(tree.id) is False  # already ended
        # Discarding a job forgets it and removes its log.
        jobs.discard(job)
        assert jobs.get(job.id) is None and not job.log.exists()
        jobs.discard(failed, keep_log=True)
        assert failed.log.exists()
    finally:
        await jobs.close()


@posix
async def test_a_process_that_ignores_sigterm_is_killed_after_the_grace(tmp_path: Path):
    jobs = JobRegistry(tmp_path / "jobs", SHELL, grace=0.5)
    try:
        job = await jobs.start("trap '' TERM; echo ready; sleep 60", str(tmp_path))
        await output_of(job, "ready")
        assert await jobs.kill(job.id) and job.signal == "SIGKILL"
        polite = await jobs.start("echo ready; sleep 60", str(tmp_path))
        await output_of(polite, "ready")
        assert await jobs.kill(polite.id) and polite.signal == "SIGTERM"
    finally:
        await jobs.close()


async def test_tools_jobs_and_terminals(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h:
        service = h.get("terminal")
        tools = {t.name: t for t in h.get("tools").list()}
        name = SHELL.dialect  # one shell tool, named after the shell of the platform
        assert {name, "job_output", "job_list", "job_kill"} <= set(tools)
        assert not {"bash", "pwsh", "run_in_background"} - {name} & set(tools)
        assert set(tools[name].args) == {"command", "timeout", "workdir", "run_in_background", "name"}
        gates = h.get("tools").interrupt_on()
        assert name in gates and "job_output" not in gates
        shell = tools[name]
        root = service.default_root()
        # Every call is a fresh shell in the workspace root: no directory or variable carries over.
        assert Path((await shell.ainvoke({"command": COMMANDS["cwd"]})).strip()).resolve() == root.resolve()
        await shell.ainvoke({"command": COMMANDS["set_and_leave"]})
        assert Path((await shell.ainvoke({"command": COMMANDS["cwd"]})).strip()).resolve() == root.resolve()
        assert (await shell.ainvoke({"command": COMMANDS["read_back"]})).strip() == "[unset]"
        # ``workdir``: relative to the workspace root, or absolute.
        inside = await shell.ainvoke({"command": COMMANDS["cwd"], "workdir": "sub"})
        assert Path(inside.strip()).resolve() == (root / "sub").resolve()
        absolute = await shell.ainvoke({"command": COMMANDS["cwd"], "workdir": str(root / "sub")})
        assert Path(absolute.strip()).resolve() == (root / "sub").resolve()
        assert (await shell.ainvoke({"command": COMMANDS["cwd"], "workdir": "nowhere"})).startswith("Error: workdir")
        # The result: the output, then one marker per fact.
        assert (await shell.ainvoke({"command": COMMANDS["both_streams"]})).split() == ["hi", "err"]
        assert await shell.ainvoke({"command": COMMANDS["nothing"]}) == "(no output)"
        assert await shell.ainvoke({"command": COMMANDS["exit_3"]}) == "(no output)\n[exit code: 3]"
        assert (await shell.ainvoke({"command": " "})).startswith("Error")
        assert service.jobs.jobs == {} and not list(service.jobs.log_dir.glob("*.log"))  # nothing is left behind
        # Long output: its tail, and the file holding all of it.
        long = await shell.ainvoke({"command": COMMANDS["many_lines"]})
        body, marker = long.rsplit("\n", 1)
        assert body.endswith("\n4999\n5000") and len(body) <= service.config.max_output_chars
        assert marker.startswith("[output truncated; full output: ") and "1\n" not in body[:2]
        kept = Path(marker.removeprefix("[output truncated; full output: ").removesuffix("]"))
        assert decode(kept.read_bytes()).split()[:2] == ["1", "2"]
        # A command that reaches its timeout goes on as a background job.
        slow = await shell.ainvoke({"command": COMMANDS["start_then_sleep"], "timeout": 6})
        assert slow.startswith("start") and "[still running after 6s; moved to background job " in slow
        promoted = slow.rsplit(" ", 1)[1].rstrip("]")
        assert service.jobs.get(promoted).status == "running" and service.jobs.get(promoted).foreground is False
        assert (await tools["job_kill"].ainvoke({"job_id": promoted})) == f"job {promoted} stopped"
        # Background jobs: started by the same tool; output in a log, status through the tools and the API.
        started = await shell.ainvoke({"command": COMMANDS["one_two"], "run_in_background": True, "name": "demo"})
        job_id = json.loads(started)["job_id"]
        waited = await tools["job_output"].ainvoke({"job_id": job_id, "wait": True, "timeout": 30})
        assert "exited" in waited and waited.split()[-2:] == ["one", "two"]
        assert job_id in await tools["job_list"].ainvoke({})
        sleeper = json.loads(await shell.ainvoke({"command": COMMANDS["sleep"], "run_in_background": True}))["job_id"]
        assert (await tools["job_kill"].ainvoke({"job_id": sleeper})) == f"job {sleeper} stopped"
        assert "not running" in await tools["job_kill"].ainvoke({"job_id": sleeper})
        assert (await tools["job_output"].ainvoke({"job_id": "nope"})).startswith("Error")
        # A cancelled call stops its command.
        call = asyncio.ensure_future(shell.ainvoke({"command": COMMANDS["sleep"]}))
        for _ in range(100):
            running = [j for j in service.jobs.jobs.values() if j.foreground]
            if running:
                break
            await asyncio.sleep(0.05)
        pid = running[0].tree.pid
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert await gone(pid) and not [j for j in service.jobs.jobs.values() if j.foreground]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c:
            jobs = (await c.get("/api/jobs")).json()["jobs"]
            assert {j["id"]: j["status"] for j in jobs} == {job_id: "exited", sleeper: "killed", promoted: "killed"}
            detail = (await c.get(f"/api/jobs/{job_id}?tail=1")).json()
            assert detail["output"].strip().endswith("two") and detail["exit_code"] == 0
            assert (await c.get("/api/jobs/nope")).status_code == 404
            status = (await c.get("/api/terminal/status")).json()
            assert status["pty"] is pty_available() and status["shell"]["dialect"] == name
            if pty_available():
                term = (await c.post("/api/terminals", json={"cols": 60, "rows": 10})).json()
                assert term["alive"] and term["cols"] == 60
                live = service.terminals[term["id"]]
                queue = live.subscribe()
                live.write(b"echo pyh-$((20+22))\n")
                got = b""
                for _ in range(100):
                    try:
                        chunk = await asyncio.wait_for(queue.get(), 1)
                    except TimeoutError:
                        break
                    if chunk is None:
                        break
                    got += chunk
                    if b"pyh-42" in got:
                        break
                assert b"pyh-42" in got
                assert (await c.post(f"/api/terminals/{term['id']}/resize", json={"cols": 100, "rows": 30})).json()[
                    "cols"
                ] == 100
                assert term["id"] in [x["id"] for x in (await c.get("/api/terminals")).json()["terminals"]]
                assert (await c.delete(f"/api/terminals/{term['id']}")).json() == {"closed": True}
                assert not live.alive and (await c.delete(f"/api/terminals/{term['id']}")).status_code == 404
        # Read-only mode leaves the shell tool out of the graph; other modes keep it.
        loop = h.get("agentLoop")
        seen: list[set[str]] = []

        async def record(kwargs, next):
            seen.append({t.name for t in kwargs["tools"]})
            return await next()

        h.ctx.on("agent-loop/build", record)
        await loop.build(mode="read-only")
        await loop.build(mode="workspace-write")
        assert name not in seen[0] and "job_list" in seen[0]
        assert {name, "job_list"} <= seen[1]


async def test_without_background_jobs_the_timeout_stops_the_command(home):
    profile = Profile.init("web", home=str(home))
    for config in ({"promote_on_timeout": False}, {"jobs_tool": False}):
        async with Harness(profile, patch=[HTTP_OFF, {"id": "terminal", "config": config}]) as h:
            tools = {t.name: t for t in h.get("tools").list()}
            shell = tools[SHELL.dialect]
            assert ("job_output" in tools) is ("jobs_tool" not in config)
            assert ("run_in_background" in shell.args) is ("jobs_tool" not in config)
            out = await shell.ainvoke({"command": COMMANDS["start_then_sleep"], "timeout": 6})
            assert out.startswith("start") and "[timed out after 6s; the command was stopped]" in out
            assert "background job" not in out and h.get("terminal").jobs.jobs == {}


@posix
async def test_terminal_class_exit(tmp_path: Path):
    if not pty_available():
        pytest.skip("no pty")
    term = Terminal("t1", "/bin/sh", str(tmp_path), 40, 10, 10_000)
    term.open()
    queue = term.subscribe()
    term.write(b"exit 3\n")
    for _ in range(50):
        chunk = await asyncio.wait_for(queue.get(), 2)
        if chunk is None:
            break
    assert term.exit_code == 3 and not term.alive
