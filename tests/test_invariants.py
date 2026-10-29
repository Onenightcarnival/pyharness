"""Cross-cutting invariants: tool pipeline, workspace protection, upgrades, lifecycle, approvals, redaction."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from pyharness import Harness, Profile, manage
from pyharness.events import EventBus
from testkit import tools as testtools


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def scripted(replies, extra=()):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "testtools", "name": "testkit.tools", "after": "tools"},
        {"id": "http", "config": {"serve": False}},
        *extra,
    ]


async def run_turn(h, text="go"):
    agents = h.get("agents")
    session = await agents.create_session()
    return session, await agents.start_run(session["id"], text).wait()


# Subagent tool calls: tools/execute and tools/result ---------------------------------------------
async def test_subagent_tool_calls_use_the_pipeline(profile):
    testtools.RESULTS.clear()
    replies = [
        {"content": "", "tool_calls": [{"name": "task", "args": {"description": "shout x", "subagent_type": "general-purpose"}, "id": "t1"}]},
        {"content": "", "tool_calls": [{"name": "shout", "args": {"text": "from subagent"}, "id": "s1"}]},
        {"content": "subagent done"},
        {"content": "all done"},
    ]
    async with Harness(profile, patch=scripted(replies)) as h:
        _, events = await run_turn(h)
        assert events[-1]["outcome"] == "completed"
    assert ("shout", "FROM SUBAGENT") in testtools.RESULTS
    assert any(name == "task" for name, _ in testtools.RESULTS)


# Harness home: closed to the agent's file tools --------------------------------------------------
async def test_workspace_containing_home_is_protected(profile, home, tmp_path, monkeypatch):
    monkeypatch.setenv("PYH_WORKSPACE", str(tmp_path))  # tmp_path contains the harness home
    target = f"/{home.relative_to(tmp_path).as_posix()}/profiles/web/harness.patch.yaml"
    before = (profile.patch_path).read_text()
    replies = [
        {"content": "", "tool_calls": [{"name": "write_file", "args": {"file_path": target, "content": "[]"}, "id": "w1"}]},
        {"content": "tried"},
    ]
    async with Harness(profile, patch=scripted(replies)) as h:
        ws = h.get("workspace")
        assert ws.protected == [home.resolve()]
        with pytest.raises(ValueError):
            ws.resolve(target)
        _, events = await run_turn(h)
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["status"] == "error" or "denied" in result["content"].lower(), result
    assert profile.patch_path.read_text() == before


async def test_workspace_inside_home_is_refused(profile, home, monkeypatch):
    monkeypatch.setenv("PYH_WORKSPACE", str(home / "profiles"))
    async with Harness(profile, patch=scripted([])) as h:
        rt = h.loader.get("workspace")
        assert rt.state.value == "failed" and "inside the harness home" in rt.error


# Rejected upgrade: previous version stays installed ----------------------------------------------
def _variant(example: Path, dest: Path, version: str, broken: bool) -> Path:
    shutil.copytree(example, dest)
    pyproject = dest / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('version = "0.1.0"', f'version = "{version}"'))
    if broken:
        init = dest / "src" / "pyharness_audit" / "__init__.py"
        init.write_text(init.read_text().replace('inject = ["tools"]', 'inject = ["tools"]\nraise ImportError("broken upgrade")'))
    return dest


async def test_rejected_upgrade_restores_previous_version(profile, example_bundle, tmp_path):
    assert (await manage.install_bundle(profile, example_bundle))["application"] == "saved"
    bad = await manage.install_bundle(profile, _variant(example_bundle, tmp_path / "v2bad", "0.2.0", broken=True))
    assert bad["application"] == "rejected" and bad["stage"] == "preflight"
    versions = sorted(d.version for d in profile.site_distributions())
    assert versions == ["0.1.0"]
    from pyharness.preflight import run_preflight

    assert (await run_preflight(profile))["ok"] is True

    good = await manage.install_bundle(profile, _variant(example_bundle, tmp_path / "v3", "0.3.0", broken=False))
    assert good["application"] == "saved"
    assert sorted(d.version for d in profile.site_distributions()) == ["0.3.0"]  # stale dist-info pruned
    assert (await manage.uninstall_bundle(profile, "audit"))["application"] == "saved"
    assert profile.site_distributions() == []
    assert not list(profile.runtime.glob("site-backup-*"))


# Lifecycle hooks: every listener runs ------------------------------------------------------------
async def test_series_runs_every_listener_and_propagates_errors():
    bus = EventBus()
    bus.define("h", "series")
    seen = []
    bus.on("h", lambda: seen.append(1) or "returned")
    bus.on("h", lambda: seen.append(2))
    await bus.series("h")
    assert seen == [1, 2]

    def boom():
        raise RuntimeError("x")

    bus.on("h", boom)
    with pytest.raises(RuntimeError):
        await bus.series("h")


async def test_ready_listener_returning_a_value_does_not_skip_the_agent_build(profile):
    def apply(ctx):
        ctx.on("app/ready", lambda: ctx.prompt.add("extra", "extra section"))  # returns a disposer

    sys.modules["tk_returning"] = types.SimpleNamespace(apply=apply, inject=["prompt"], __name__="tk_returning")
    patch = scripted([{"content": "built"}], extra=[{"id": "returning", "name": "tk_returning", "after": "prompt"}])
    async with Harness(profile, patch=patch) as h:
        assert h.get("agents").graph is not None


# Restart pending: new work refused ---------------------------------------------------------------
async def test_new_runs_are_refused_while_a_restart_is_pending(profile):
    from pyharness_agent import RestartPending

    async with Harness(profile, patch=scripted([])) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        h.lifecycle.request_restart("change")
        with pytest.raises(RestartPending):
            agents.start_run(session["id"], "hi")


# Approval gates: per owner -----------------------------------------------------------------------
async def test_approval_gates_are_per_owner(profile):
    def gate_then_fail(ctx):
        ctx.tools.require_approval("execute", {"allowed_decisions": ["approve", "reject", "edit"]})
        raise RuntimeError("fails after gating")

    sys.modules["tk_gatefail"] = types.SimpleNamespace(apply=gate_then_fail, inject=["tools"], __name__="tk_gatefail")
    patch = scripted([], extra=[{"id": "workspace", "config": {"shell": True}, "merge": True}, {"id": "gatefail", "name": "tk_gatefail"}])
    async with Harness(profile, patch=patch) as h:
        assert h.loader.get("gatefail").state.value == "failed"
        gates = h.get("tools").interrupt_on()
        assert gates["execute"] == {"allowed_decisions": ["approve", "reject"]}


# inspect: interpolated values redacted -----------------------------------------------------------
async def test_inspect_redacts_environment_values(profile, monkeypatch):
    monkeypatch.setenv("PYH_TEST_SECRET", "sk-very-secret")
    patch = scripted([], extra=[{"id": "llm", "config": {"default": "scripted:test", "providers": {"openai": {"api_key": "${env:PYH_TEST_SECRET}"}}}}])
    async with Harness(profile, patch=patch) as h:
        tool = next(t for t in h.get("tools").list() if t.name == "harness_inspect")
        text = tool.invoke({"topic": "config", "name": "llm"})
        assert "sk-very-secret" not in text
        assert "redacted" in text


# SIGHUP: graceful restart, no rollback -----------------------------------------------------------
def test_sighup_restarts_without_rollback(home, tmp_path):
    profile = Profile.init("sig", template="empty", home=str(home))
    markers = tmp_path / "markers"
    profile.save_patch([{"id": "marker", "name": "testkit.marker", "config": {"marker_dir": str(markers)}}])
    proc = subprocess.Popen(
        [sys.executable, "-m", "pyharness.cli", "--home", str(home), "run", "-p", "sig"],
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        while not (markers / "gen-1.json").exists():
            assert time.monotonic() < deadline and proc.poll() is None
            time.sleep(0.1)
        proc.send_signal(signal.SIGHUP)
        while not (markers / "gen-2.json").exists():
            assert time.monotonic() < deadline and proc.poll() is None
            time.sleep(0.1)
    finally:
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0, out[-2000:]
    history = [json.loads(line) for line in (profile.runtime / "supervisor.log.jsonl").read_text().splitlines()]
    events = [(h["generation"], h["event"], h.get("code")) for h in history]
    assert (1, "exited", 75) in events
    assert not any(e[1] in ("boot-failed", "rolled-back") for e in events)
