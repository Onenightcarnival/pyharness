"""Creator mode: skills mounted read-only, catalog in the system prompt, templates, generated package reference."""

from __future__ import annotations

import re

import pytest
from pyharness_plugin_manager import SKILLS_DIR, render_template, template_variants
from pyharness_plugin_manager.reference import PACKAGES_MD, render_packages

from pyharness import Harness, Profile
from testkit import scripted

SKILLS = {"pyharness-plugin-development", "editing-pyharness-compositions", "pyharness-composition-reference", "agent-experience"}


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
        assert "pyproject.toml" in files and "pyh_my_audit/__init__.py" in files and "pyh_my_audit/bundle.yaml" in files
        assert not any("__" + t for t in ("DIST", "MODULE", "BUNDLE", "TITLE") if any(f"__{t}__" in v for v in files.values()))
        assert 'pyh-my-audit = "pyh_my_audit"' in files["pyproject.toml"]
    assert 'id: "my-audit"' in render_template("My Audit", "ui-panel")["pyh_my_audit/client.js"]
    with pytest.raises(ValueError):
        render_template("x", "nope")


async def test_creator_profile_mounts_skills_read_only(home):
    profile = Profile.init("creator", template="creator", home=str(home))
    assert profile.bundles() == ["base", "creator"]
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
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/skills/pyharness/x.md", "content": "x"}, "id": "w1"}],
        },
        {"content": "", "tool_calls": [{"name": "write_file", "args": {"file_path": "/note.md", "content": "ok"}, "id": "w2"}]},
        {"content": "done"},
    ]
    scripted.CALLS.clear()
    async with Harness(profile, patch=patch_for(replies)) as h:
        mounts = h.get("agentLoop").skills()
        assert mounts == [
            {
                "label": "pyharness",
                "path": str(SKILLS_DIR),
                "mount": "/skills/pyharness/",
                "owner": "plugin-manager",
                "presets": ["creator"],
            }
        ]
        assert h.get("agentLoop").config.default_preset == "creator"
        prompt = h.get("prompt").render("creator")
        assert "Extending this harness" not in prompt  # the skill catalog carries it in the creator preset
        assert "## This harness" in prompt and f"`{profile.name}` at {profile.dir}" in prompt
        agents = h.get("agents")
        session = await agents.create_session()
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert results["r1"]["status"] == "success" and "plugin_manager action=install_bundle" in results["r1"]["content"]
        assert results["w1"]["status"] == "error" and "denied" in results["w1"]["content"]
        assert results["w2"]["status"] == "success"  # the workspace itself stays writable
        system = next(c for c in scripted.CALLS if "messages" in c)["messages"][0][1]
        for name in SKILLS:
            assert f"/skills/pyharness/{name}/SKILL.md" in system
        assert "Extending this harness" not in system


async def test_base_profile_keeps_the_short_guidance(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=patch_for([{"content": "hi"}])) as h:
        loop = h.get("agentLoop")
        assert loop.config.default_preset == "standard" and [p["id"] for p in loop.presets()] == ["standard", "creator"]
        prompt = h.get("prompt").render("standard")
        assert "Extending this harness" in prompt and "Creator preset" in prompt
        assert "Extending this harness" not in h.get("prompt").render("creator")
        assert "## This harness" in prompt
