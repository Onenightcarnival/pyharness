"""Headline flow, real processes.

agent installs a bundle → supervisor restart → session continues in the next generation → new plugin in use
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from pyharness import Profile


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sse(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def wait_for(fn, timeout=60.0, step=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(step)
    raise AssertionError("condition not met in time")


def test_agent_extends_itself_across_a_restart(home, example_bundle, tmp_path):
    profile = Profile.init("web", home=str(home))
    workspace = Path(os.environ["PYH_CWD"])
    shutil.copytree(example_bundle, workspace / "plugins" / "audit")
    port = free_port()
    install = {"name": "plugin_manager", "args": {"action": "install_bundle", "target": "/plugins/audit"}, "id": "pm1"}
    use = {"name": "shout", "args": {"text": "after restart"}, "id": "s1"}
    profile.save_patch(
        [
            {
                "id": "scripted",
                "name": "testkit.scripted",
                "after": "llm",
                "config": {
                    "by_generation": {
                        1: [{"content": "", "tool_calls": [install]}, {"content": "Installed; restart after this turn."}],
                        2: [{"content": "", "tool_calls": [use]}, {"content": "Verified: the audit plugin recorded the call."}],
                    }
                },
            },
            {"id": "llm", "config": {"default": "scripted:test"}},
            {"id": "testtools", "name": "testkit.tools", "after": "tools", "config": {"gate_danger": False}},
            {"id": "http", "config": {"port": port}},
        ]
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "pyharness.cli", "--home", str(home), "run", "-p", "web"],
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}/api"
    try:
        with httpx.Client(base_url=base, timeout=60, trust_env=False) as client:
            assert wait_for(lambda: client.get("/health").json()["generation"] == 1)
            sid = client.post("/sessions", json={"preset": "creator"}).json()["id"]
            events = sse(client.post(f"/sessions/{sid}/messages", json={"content": "install the audit plugin"}).text)
            assert events[-1]["outcome"] == "interrupted"
            events = sse(client.post(f"/sessions/{sid}/approvals", json={"decisions": [{"type": "approve"}]}).text)
            result = json.loads(next(e for e in events if e["type"] == "tool_result")["content"])
            assert result["application"] == "restart-scheduled", result
            assert events[-1]["restart_pending"] is True

            assert wait_for(lambda: client.get("/health").json()["generation"] == 2, timeout=90)
            detail = wait_for(
                lambda: (
                    (d := client.get(f"/sessions/{sid}").json())
                    and not d["busy"]
                    and d["messages"][-1]["role"] == "ai"
                    and "Verified" in d["messages"][-1]["content"]
                    and d
                ),
                timeout=60,
            )
            contents = [m["content"] for m in detail["messages"]]
            assert any("Restarted into generation 2" in c for c in contents)
            plugins = {e["id"]: e["state"] for e in client.get("/plugins").json()["entries"]}
            assert plugins["audit"] == "active"
            audit = httpx.get(f"http://127.0.0.1:{port}/audit", trust_env=False).json()
            assert [row["tool"] for row in audit] == ["shout"]
    finally:
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0, out[-3000:]
    assert "generation 2 ready" in out
