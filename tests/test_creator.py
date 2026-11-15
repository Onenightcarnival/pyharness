"""Creator mode: skills and package sources mounted read-only, templates, generated package reference."""

from __future__ import annotations

import json
import re

import pytest

from conftest import ROOT
from pyharness import Harness, Profile
from pyharness_plugin_manager import SKILLS_DIR, render_template, template_variants
from pyharness_plugin_manager.reference import PACKAGES_MD, render_packages
from testkit import scripted

SKILLS = {
    "pyharness-plugin-development",
    "editing-pyharness-compositions",
    "pyharness-composition-reference",
    "agent-experience",
}


def patch_for(replies):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "http", "config": {"serve": False}},
    ]


def test_skill_files_are_well_formed():
    found = set()
    for skill in SKILLS_DIR.glob("*/SKILL.md"):
        text = skill.read_text(encoding="utf-8")
        head = re.match(r"---\nname: (\S+)\ndescription: \"(.+)\"\n---\n", text)
        assert head, skill
        assert head.group(1) == skill.parent.name
        assert head.group(2).startswith("Use when")
        assert len(text) < 8000, (skill, len(text))
        found.add(head.group(1))
    assert found == SKILLS


def test_packages_reference_is_fresh():
    assert PACKAGES_MD.read_text(encoding="utf-8") == render_packages(), "run: uv run python scripts/gen_packages.py"
    text = PACKAGES_MD.read_text(encoding="utf-8")
    assert "| `pyharness-plugin-manager` | function |" in text
    assert "| `creator` | Creator |" in text


def test_templates_render_without_tokens():
    assert template_variants() == ["basic", "tool-and-route", "ui-panel"]
    for variant in template_variants():
        files = render_template("My Audit", variant)
        assert {"pyproject.toml", "AGENTS.md"} <= set(files)
        assert {f"pyh_my_audit/{f}" for f in ("__init__.py", "plugin.py", "bundle.py", "bundle.yaml")} <= set(files)
        assert not any(
            "__" + t for t in ("DIST", "MODULE", "BUNDLE", "TITLE") if any(f"__{t}__" in v for v in files.values())
        )
        assert 'pyh-my-audit = "pyh_my_audit"' in files["pyproject.toml"]
        for path, text in files.items():
            if path.endswith(".py"):
                compile(text, path, "exec")  # a name of several words renders to valid Python
    assert 'id: "my-audit"' in render_template("My Audit", "ui-panel")["pyh_my_audit/client.js"]
    with pytest.raises(ValueError):
        render_template("x", "nope")


async def test_creator_profile_mounts_skills_read_only(home):
    profile = Profile.init("creator", template="creator", home=str(home))
    assert profile.bundles() == ["base", "creator", "toolkit", "web"]  # toolkit: built in; web: optional preset
    replies = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "read_file",
                    "args": {"file_path": "/skills/pyharness/pyharness-plugin-development/SKILL.md", "limit": 1000},
                    "id": "r1",
                }
            ],
        },
        {
            "content": "",
            "tool_calls": [
                {"name": "write_file", "args": {"file_path": "/skills/pyharness/x.md", "content": "x"}, "id": "w1"}
            ],
        },
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/note.md", "content": "ok"}, "id": "w2"}],
        },
        {"content": "done"},
    ]
    scripted.CALLS.clear()
    async with Harness(profile, patch=patch_for(replies)) as h:
        mounts = h.get("agentLoop").skills()
        assert {
            "label": "pyharness",
            "path": str(SKILLS_DIR),
            "mount": "/skills/pyharness/",
            "owner": "plugin-manager",
            "presets": ["creator"],
        } in mounts
        assert [m["label"] for m in mounts] == ["pyharness", "user"] and mounts[1][
            "owner"
        ] == "config-center"  # user skills: every preset
        assert h.get("agentLoop").config.default_preset == "creator"
        prompt = h.get("prompt").render("creator")
        assert "Extending this harness" not in prompt  # the skill catalog carries it in the creator preset
        assert "## This harness" in prompt and f"`{profile.name}` at {profile.dir}" in prompt
        agents = h.get("agents")
        session = await agents.create_session()
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert (
            results["r1"]["status"] == "success" and "plugin_manager action=install_bundle" in results["r1"]["content"]
        )
        assert results["w1"]["status"] == "error" and "denied" in results["w1"]["content"]
        assert results["w2"]["status"] == "success"  # the workspace itself stays writable
        system = next(c for c in scripted.CALLS if "messages" in c)["messages"][0][1]
        for name in SKILLS:
            assert f"/skills/pyharness/{name}/SKILL.md" in system
        assert "Extending this harness" not in system


async def test_creator_preset_reads_the_mounted_packages(home):
    profile = Profile.init("creator", template="creator", home=str(home))
    docs = "/harness/pyharness_llm/AGENTS.md"
    replies = [
        {"content": "", "tool_calls": [{"name": "read_file", "args": {"file_path": docs}, "id": "r1"}]},
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "read_file",
                    "args": {"file_path": "/harness/pyharness_llm/pyharness_llm/service.py"},
                    "id": "r2",
                }
            ],
        },
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": docs, "content": "x"}, "id": "w1"}],
        },
        {"content": "", "tool_calls": [{"name": "ls", "args": {"path": "/harness"}, "id": "l1"}]},
        {"content": "done"},
        {"content": "", "tool_calls": [{"name": "read_file", "args": {"file_path": docs}, "id": "r3"}]},
        {"content": "done"},
    ]
    async with Harness(profile, patch=patch_for(replies)) as h:
        loop, agents = h.get("agentLoop"), h.get("agents")
        mounts = {m["mount"]: m for m in loop.mounts()}
        assert mounts["/harness/pyharness/"]["path"] == str(ROOT / "packages" / "core")  # the kernel
        assert mounts["/harness/pyharness_llm/"] == {
            "mount": "/harness/pyharness_llm/",
            "path": str(ROOT / "packages" / "llm"),
            "owner": "plugin-manager",
            "presets": ["creator"],
            "writable": False,
        }
        assert all(m["owner"] == "plugin-manager" for m in mounts.values())
        assert "## Harness sources" in h.get("prompt").render("creator")
        assert "## Harness sources" not in h.get("prompt").render("standard")

        inspect = next(t for t in h.get("tools").list() if t.name == "harness_inspect")
        config = json.loads(inspect.invoke({"topic": "config", "name": "llm"}))
        assert config["docs"] == docs and config["package_dir"] == "/harness/pyharness_llm/pyharness_llm/"
        entry = json.loads(inspect.invoke({"topic": "plugins", "name": "dev-context"}))[0]
        assert entry["docs"] == "/harness/pyharness_plugin_manager/AGENTS.md"

        session = await agents.create_session()
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert results["r1"]["status"] == "success" and "# pyharness-llm" in results["r1"]["content"]
        assert results["r2"]["status"] == "success" and "class LLMService" in results["r2"]["content"]
        assert results["w1"]["status"] == "error" and "denied" in results["w1"]["content"]
        assert all(f"/harness/{module}/" in results["l1"]["content"] for module in ("pyharness", "pyharness_llm"))

        session = await agents.create_session(preset="standard")
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert "# pyharness-llm" not in results["r3"]["content"]


async def test_creator_preset_writes_the_profile_plugin_sources(home, tmp_path):
    profile = Profile.init("creator", template="creator", home=str(home))
    sources = profile.documents / "plugins"
    other = tmp_path / "other"
    (other / "plugins").mkdir(parents=True)
    (other / "plugins" / "local.md").write_text("workspace file", encoding="utf-8")
    note = "/plugins/demo/note.md"
    replies = [
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": note, "content": "src"}, "id": "w1"}],
        },
        {"content": "", "tool_calls": [{"name": "ls", "args": {"path": "/plugins"}, "id": "l1"}]},
        {"content": "done"},
        {"content": "", "tool_calls": [{"name": "read_file", "args": {"file_path": note}, "id": "r1"}]},
        {"content": "done"},
    ]
    async with Harness(profile, patch=patch_for(replies)) as h:
        loop, agents, prompt = h.get("agentLoop"), h.get("agents"), h.get("prompt")
        mount = next(m for m in loop.mounts() if m["mount"] == "/plugins/")
        assert (mount["path"], mount["writable"], mount["presets"]) == (str(sources.resolve()), True, ["creator"])
        assert f"`{sources}`" in prompt.render("creator") and "## Plugin sources" not in prompt.render("standard")

        session = await agents.create_session(workspace=str(other))  # any workspace: the same directory
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert results["w1"]["status"] == "success" and (sources / "demo" / "note.md").read_text() == "src"
        assert "/plugins/demo/" in results["l1"]["content"] and "local.md" not in results["l1"]["content"]

        session = await agents.create_session(preset="standard")
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert "src" not in results["r1"]["content"]
    assert not (other / "plugins" / "demo").exists()


async def test_sources_off_leaves_paths_on_disk(home):
    profile = Profile.init("creator", template="creator", home=str(home))
    patch = [*patch_for([]), {"id": "plugin-manager", "config": {"sources": False}}]
    async with Harness(profile, patch=patch) as h:
        assert [m["mount"] for m in h.get("agentLoop").mounts()] == ["/plugins/"]
        assert "## Harness sources" not in h.get("prompt").render("creator")
        inspect = next(t for t in h.get("tools").list() if t.name == "harness_inspect")
        config = json.loads(inspect.invoke({"topic": "config", "name": "llm"}))
        assert config["docs"] == str(ROOT / "packages" / "llm" / "AGENTS.md")


async def test_base_profile_keeps_the_short_guidance(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=patch_for([{"content": "hi"}])) as h:
        loop = h.get("agentLoop")
        assert loop.config.default_preset == "standard" and [p["id"] for p in loop.presets()] == ["standard", "creator"]
        prompt = h.get("prompt").render("standard")
        assert "Extending this harness" in prompt and "Creator preset" in prompt
        assert "Extending this harness" not in h.get("prompt").render("creator")
        assert "## This harness" in prompt
