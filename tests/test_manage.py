"""Bundle installation: pip/uv into the profile site, preflight, rollback, agent-facing tool."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pyharness import Harness, Profile, manage
from testkit import tools as testtools


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def patch_for(replies):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "testtools", "name": "testkit.tools", "after": "tools"},
        {"id": "http", "config": {"serve": False}},
    ]


async def test_install_preflight_boot_and_uninstall(profile, example_bundle, tmp_path):
    result = await manage.install_bundle(profile, example_bundle)
    assert result["application"] == "saved", result
    assert result["bundles"] == ["audit"]
    assert profile.bundles() == ["base", "audit", "web"]  # web: optional preset, on by default
    assert result["preflight"]["ok"] is True

    testtools.RESULTS.clear()
    replies = [{"content": "", "tool_calls": [{"name": "shout", "args": {"text": "a"}, "id": "c1"}]}, {"content": "ok"}]
    async with Harness(profile, patch=patch_for(replies)) as h:
        states = {e["id"]: e["state"] for e in h.loader.snapshot()}
        assert states["audit"] == "active"
        agents = h.get("agents")
        session = await agents.create_session(preset="creator")
        await agents.start_run(session["id"], "go").wait()
        routes = {r["path"] for r in h.get("http").routes()}
        assert "/audit" in routes
    lines = (profile.data / "audit.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["tool"] == "shout"

    removed = await manage.uninstall_bundle(profile, "audit")
    assert removed["application"] == "saved"
    assert profile.bundles() == ["base", "web"]
    assert not any(d.name == "pyharness-audit" for d in profile.site_distributions())


async def test_broken_bundle_is_rejected_and_rolled_back(profile, example_bundle, tmp_path):
    broken = tmp_path / "broken-audit"
    shutil.copytree(example_bundle, broken)
    init = broken / "src" / "pyharness_audit" / "__init__.py"
    init.write_text(init.read_text().replace('inject = ["tools"]', 'inject = ["tools"]\nraise ImportError("deliberately broken")'))
    before = profile.read_state()
    result = await manage.install_bundle(profile, broken)
    assert result["application"] == "rejected", result
    assert result["stage"] == "preflight"
    assert any("deliberately broken" in str(e.get("error")) for e in result["errors"])
    assert profile.read_state() == before
    assert not any(d.name == "pyharness-audit" for d in profile.site_distributions())


async def test_bundle_without_entry_point_is_rejected(profile, tmp_path):
    pkg = tmp_path / "plain"
    (pkg / "plain_pkg").mkdir(parents=True)
    (pkg / "plain_pkg" / "__init__.py").write_text("")
    (pkg / "pyproject.toml").write_text(
        '[project]\nname = "plain-pkg"\nversion = "0.1.0"\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["plain_pkg"]\n'
    )
    result = await manage.install_bundle(profile, pkg)
    assert result["application"] == "rejected"
    assert "pyharness.bundles" in result["error"]
    assert profile.site_distributions() == []


async def test_agent_installs_a_bundle_through_the_tool(profile, example_bundle, home):
    """plugin_manager on an existing directory, through approval."""
    workspace = Path(profile.variables()["cwd"])
    shutil.copytree(example_bundle, workspace / "plugins" / "audit")
    replies = [
        {
            "content": "",
            "tool_calls": [{"name": "plugin_manager", "args": {"action": "install_bundle", "target": "/plugins/audit"}, "id": "pm1"}],
        },
        {"content": "installed"},
    ]
    async with Harness(profile, patch=patch_for(replies), supervised=True) as h:
        agents = h.get("agents")
        session = await agents.create_session(preset="creator")
        events = await agents.start_run(session["id"], "install the audit plugin").wait()
        interrupt = next(e for e in events if e["type"] == "interrupt")
        assert interrupt["interrupts"][0]["value"]["action_requests"][0]["name"] == "plugin_manager"
        events = await agents.start_run(session["id"], decisions=[{"type": "approve"}]).wait()
        result = json.loads(next(e for e in events if e["type"] == "tool_result")["content"])
        assert result["application"] == "restart-scheduled", result
        assert events[-1]["restart_pending"] is True
        assert h.lifecycle.exit_code == 75  # turn ended: restart due
        resume = json.loads((profile.runtime / "resume.json").read_text())
        assert resume["resume"] == [session["id"]]
    assert "audit" in profile.bundles()


async def test_read_only_actions_need_no_approval(profile):
    replies = [
        {"content": "", "tool_calls": [{"name": "plugin_manager", "args": {"action": "list"}, "id": "l1"}]},
        {"content": "listed"},
    ]
    async with Harness(profile, patch=patch_for(replies)) as h:
        agents = h.get("agents")
        session = await agents.create_session(preset="creator")
        events = await agents.start_run(session["id"], "list plugins").wait()
        assert not any(e["type"] == "interrupt" for e in events)
        listing = json.loads(next(e for e in events if e["type"] == "tool_result")["content"])
        assert {"id": "plugin-manager", "name": "pyharness-plugin-manager", "state": "active", "source": "bundle:base"} in listing[
            "entries"
        ]


def test_install_targets_are_classified():
    assert manage.requirement_name("pyh-todo==0.1.0") == "pyh-todo"
    assert manage.requirement_name("pyh_todo>=1,<2") == "pyh_todo"
    assert manage.requirement_name("/plugins/todo") is None and manage.requirement_name("a b") is None
    assert manage.looks_like_path("./plugins/todo") and manage.looks_like_path("~/x") and manage.looks_like_path("/tmp")
    assert not manage.looks_like_path("pyh-todo") and not manage.looks_like_path("pyh-todo==0.1.0")


async def test_install_package_rejects_a_bad_requirement(profile):
    result = await manage.install_package(profile, "not a requirement")
    assert result["application"] == "rejected" and result["stage"] == "install"
    assert "not a package requirement" in result["error"]
