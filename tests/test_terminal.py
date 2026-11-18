"""Terminal plugin: persistent shell, background jobs, PTY terminals, tool registration and mode handling."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_terminal import ShellSession, Terminal, clip, pty_available

HTTP_OFF = {"id": "http", "config": {"serve": False}}
posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell")


@posix
async def test_shell_session_persists_cwd_and_env(tmp_path: Path):
    shell = ShellSession("bash", tmp_path)
    try:
        r = await shell.run("export PYH_T=1; mkdir -p sub; cd sub; echo hi; echo err >&2", 10)
        assert (
            r["exit_code"] == 0
            and r["output"].splitlines() == ["hi", "err"]
            and r["cwd"] == str((tmp_path / "sub").resolve())
        )
        r = await shell.run('echo "$PYH_T $(basename "$PWD")"; exit_code_test() { return 3; }; exit_code_test', 10)
        assert r["output"] == "1 sub" and r["exit_code"] == 3
        r = await shell.run("cat", 10)  # stdin is /dev/null: no hang
        assert r["exit_code"] == 0
        r = await shell.run("echo start; sleep 5; echo never", 1)
        assert r["timed_out"] is True and r["output"] == "start" and r["exit_code"] is None
        r = await shell.run("pwd", 10)  # a fresh shell in the last known directory
        assert r["cwd"].endswith("sub") and shell.restarts == 1
    finally:
        await shell.close()
    assert clip("x" * 100, 20).startswith("xxxxxxxxxx\n…[80 characters omitted]…\n")


@posix
async def test_tools_jobs_and_terminals(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h:
        service = h.get("terminal")
        tools = {t.name: t for t in h.get("tools").list()}
        assert {"bash", "run_in_background", "job_output", "job_list", "job_kill"} <= set(tools)
        gates = h.get("tools").interrupt_on()
        assert "bash" in gates and "run_in_background" in gates and "job_output" not in gates
        # The shell starts in the workspace root; the directory persists.
        out = await tools["bash"].ainvoke({"command": "pwd; mkdir -p d1; cd d1"})
        assert str(service.default_root()) in out and "[exit code 0; cwd" in out and out.strip().endswith("d1]")
        assert "no output" in await tools["bash"].ainvoke({"command": "true"})
        # Background jobs: output in a log, status through the tools and the API.
        started = await tools["run_in_background"].ainvoke({"command": "echo one; sleep 0.3; echo two", "name": "demo"})
        job_id = json.loads(started)["job_id"]
        waited = await tools["job_output"].ainvoke({"job_id": job_id, "wait": True, "timeout": 10})
        assert "exited" in waited and "one\ntwo" in waited
        assert job_id in await tools["job_list"].ainvoke({})
        long = json.loads(await tools["run_in_background"].ainvoke({"command": "sleep 30"}))["job_id"]
        assert (await tools["job_kill"].ainvoke({"job_id": long})) == f"job {long} stopped"
        assert "not running" in await tools["job_kill"].ainvoke({"job_id": long})
        assert (await tools["job_output"].ainvoke({"job_id": "nope"})).startswith("Error")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c:
            jobs = (await c.get("/api/jobs")).json()["jobs"]
            assert {j["id"]: j["status"] for j in jobs} == {job_id: "exited", long: "killed"}
            detail = (await c.get(f"/api/jobs/{job_id}?tail=1")).json()
            assert detail["output"].endswith("two") and detail["exit_code"] == 0
            assert (await c.get("/api/jobs/nope")).status_code == 404
            assert (await c.get("/api/terminal/status")).json()["pty"] is pty_available()
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
        # Read-only mode leaves the shell tools out of the graph; other modes keep them.
        loop = h.get("agentLoop")
        seen: list[set[str]] = []

        async def record(kwargs, next):
            seen.append({t.name for t in kwargs["tools"]})
            return await next()

        h.ctx.on("agent-loop/build", record)
        await loop.build(mode="read-only")
        await loop.build(mode="workspace-write")
        assert "bash" not in seen[0] and "run_in_background" not in seen[0] and "job_list" in seen[0]
        assert {"bash", "run_in_background", "job_list"} <= seen[1]


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
