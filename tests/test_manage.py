"""Bundle installation: pip/uv into the profile site, preflight, rollback, agent-facing tool."""

from __future__ import annotations

import json
import shutil
from textwrap import dedent

import pytest

from pyxis_harness import Harness, Profile, manage
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
    assert profile.bundles() == ["base", "audit", "toolkit", "web"]  # toolkit: built in; web: optional preset
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
    assert profile.bundles() == ["base", "toolkit", "web"]
    assert not any(d.name == "pyxis-harness-audit" for d in profile.site_distributions())


async def test_broken_bundle_is_rejected_and_rolled_back(profile, example_bundle, tmp_path):
    broken = tmp_path / "broken-audit"
    shutil.copytree(example_bundle, broken)
    plugin = broken / "pyxis_harness_audit" / "plugin.py"
    plugin.write_text(
        plugin.read_text().replace('inject = ["tools"]', 'inject = ["tools"]\nraise ImportError("deliberately broken")')
    )
    before = profile.read_state()
    result = await manage.install_bundle(profile, broken)
    assert result["application"] == "rejected", result
    assert result["stage"] == "preflight"
    assert any("deliberately broken" in str(e.get("error")) for e in result["errors"])
    assert profile.read_state() == before
    assert not any(d.name == "pyxis-harness-audit" for d in profile.site_distributions())


async def test_bundle_without_entry_point_is_rejected(profile, tmp_path):
    pkg = tmp_path / "plain"
    (pkg / "plain_pkg").mkdir(parents=True)
    (pkg / "plain_pkg" / "__init__.py").write_text("")
    (pkg / "pyproject.toml").write_text(
        dedent(
            """
            [project]
            name = "plain-pkg"
            version = "0.1.0"
            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"
            [tool.hatch.build.targets.wheel]
            packages = ["plain_pkg"]
            """
        ).strip()
    )
    result = await manage.install_bundle(profile, pkg)
    assert result["application"] == "rejected"
    assert "pyxis_harness.bundles" in result["error"]
    assert profile.site_distributions() == []


async def test_agent_installs_a_bundle_through_the_tool(profile, example_bundle):
    """plugin_manager on a directory of the profile's plugin sources, through approval."""
    shutil.copytree(example_bundle, profile.documents / "plugins" / "audit")
    replies = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "plugin_manager",
                    "args": {"action": "install_bundle", "target": "/plugins/audit"},
                    "id": "pm1",
                }
            ],
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


async def test_install_target_resolves_in_the_session_workspace(profile, example_bundle, tmp_path):
    other = tmp_path / "other"
    shutil.copytree(example_bundle, other / "mine" / "audit")
    install = {"name": "plugin_manager", "args": {"action": "install_bundle", "target": "/mine/audit"}, "id": "pm1"}
    replies = [{"content": "", "tool_calls": [install]}, {"content": "installed"}]
    async with Harness(profile, patch=patch_for(replies), supervised=True) as h:
        agents = h.get("agents")
        session = await agents.create_session(preset="creator", workspace=str(other))
        await agents.start_run(session["id"], "install the audit plugin").wait()
        events = await agents.start_run(session["id"], decisions=[{"type": "approve"}]).wait()
        result = json.loads(next(e for e in events if e["type"] == "tool_result")["content"])
        assert result["application"] == "restart-scheduled", result
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
        preview = next(e for e in events if e["type"] == "tool_result")["content"]  # events carry a 4000-char preview
        assert preview.startswith("{") and '"id": "plugin-manager"' in preview and '"source": "bundle:base"' in preview


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
