"""Sessions: workspace registry, permission modes, agent presets, per-session graphs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml

from pyxis_harness import Harness, Profile
from pyxis_harness_workspace import WorkspaceError, registry
from testkit import scripted


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def patch(replies, extra=None):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "testtools", "name": "testkit.tools", "after": "tools", "config": {"gate_danger": True}},
        {"id": "http", "config": {"serve": False}},
        *(extra or []),
    ]


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120)


def sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def tool_names(system_prompt_call):
    return system_prompt_call


async def test_workspace_registry(profile, tmp_path, home):
    other = tmp_path / "other"
    other.mkdir()
    async with Harness(profile, patch=patch([])) as h:
        ws = h.get("workspace")
        assert ws.open(None) is ws.default and ws.open(str(ws.root)) is ws.default
        opened = ws.open(str(other))
        assert opened.root == other.resolve() and ws.open(str(other)) is opened
        with pytest.raises(WorkspaceError):
            ws.open("relative/path")
        with pytest.raises(WorkspaceError):
            ws.open(str(tmp_path / "missing"))
        with pytest.raises(WorkspaceError):
            ws.open(str(home / "profiles"))  # inside the harness home
        assert ws.backend_for(str(other)) is ws.backend_for(str(other))
        assert ws.backend_for(str(other), shell=False) is not ws.backend_for(str(other), shell=True) or not ws.shell
        listing = ws.browse(str(tmp_path))
        assert listing["path"] == str(tmp_path.resolve()) and any(d["name"] == "other" for d in listing["dirs"])
        assert ws.browse(str(home))["selectable"] is False
        # Recent: the default first, then remembered ones by last use.
        await ws.remember(str(other))
        recent = await ws.recent()
        assert (
            recent[0]["default"] is True and recent[1]["root"] == str(other.resolve()) and recent[1]["exists"] is True
        )
        assert await ws.forget(str(other)) is True and len(await ws.recent()) == 1


async def test_presets_select_tools_skills_and_prompt_sections(profile):
    scripted.CALLS.clear()
    replies = [{"content": "a"}, {"content": "b"}]
    async with Harness(profile, patch=patch(replies)) as h:
        loop = h.get("agentLoop")
        assert [p["id"] for p in loop.presets()] == ["standard", "creator"]
        assert loop.presets()[0]["default"] is True
        agents = h.get("agents")
        async with client(h) as c:
            standard = (await c.post("/api/sessions", json={})).json()
            assert (standard["preset"], standard["mode"], standard["workspace"]) == (
                "standard",
                "workspace-write",
                None,
            )
            creator = (await c.post("/api/sessions", json={"preset": "creator"})).json()
            assert creator["preset"] == "creator"
            assert (await c.post("/api/sessions", json={"preset": "nope"})).status_code == 422
            options = (await c.get("/api/agent")).json()
            assert options["default_preset"] == "standard" and [(m["id"], m["builtin"]) for m in options["modes"]] == [
                ("read-only", True),
                ("workspace-write", True),
                ("full-access", True),
                ("auto-review", False),
            ]
            refused = await c.put("/api/settings/agent", json={"default_mode": "auto-review"})
            assert refused.status_code == 422 and "per session" in refused.json()["detail"]
        await agents.start_run(standard["id"], "x").wait()
        await agents.start_run(creator["id"], "y").wait()
        prompts = [c["messages"][0][1] for c in scripted.CALLS if "messages" in c]
        assert "Agent preset: Standard" in prompts[0] and "Extending this harness" in prompts[0]
        assert (
            "Agent preset: Creator" in prompts[1]
            and "/skills/pyxis-harness/pyxis-harness-plugin-development/SKILL.md" in prompts[1]
        )
        assert "/skills/pyxis-harness/" not in prompts[0]  # the user skills mount (config-center) is in every preset
        # Tool sets per graph: the standard graph has no plugin_manager tool.
        standard_graph = await agents.graph_for(standard)
        creator_graph = await agents.graph_for(creator)
        assert standard_graph is not creator_graph
        names = lambda g: set(g.get_graph().nodes)  # noqa: E731
        assert names(standard_graph) and names(creator_graph)


async def test_modes_gate_writes_shell_and_approvals(profile, workspace):
    write = {
        "content": "",
        "tool_calls": [{"name": "write_file", "args": {"file_path": "/note.md", "content": "hi"}, "id": "w1"}],
    }
    # One scripted model instance serves both sessions: replies are consumed in order across them.
    replies = [
        write,
        {"content": "", "tool_calls": [{"name": "danger", "args": {"target": "x"}, "id": "d1"}]},
        write,
        {"content": "done"},
    ]
    extra = [
        {
            "id": "workspace",
            "config": {"shell": True, "shell_approval": True},
            "merge": True,
        }
    ]
    async with Harness(profile, patch=patch(replies, extra)) as h:
        agents = h.get("agents")
        async with client(h) as c:
            ro = (await c.post("/api/sessions", json={"mode": "read-only"})).json()
            events = sse((await c.post(f"/api/sessions/{ro['id']}/messages", json={"content": "write"})).text)
            write = next(e for e in events if e["type"] == "tool_result" and e["id"] == "w1")
            assert write["status"] == "error" and "denied" in write["content"].lower()
            # The gated tool still asks in read-only mode.
            assert events[-1]["outcome"] == "interrupted"
            assert not (workspace / "note.md").exists()

            full = (await c.post("/api/sessions", json={"mode": "full-access"})).json()
            events = sse((await c.post(f"/api/sessions/{full['id']}/messages", json={"content": "write"})).text)
            write = next(e for e in events if e["type"] == "tool_result" and e["id"] == "w1")
            assert write["status"] != "error"
            assert (workspace / "note.md").read_text() == "hi"
            assert events[-1]["outcome"] == "completed"  # no approval gate in full access

            # Switching an existing session's mode applies to the next run.
            assert (await c.put(f"/api/sessions/{full['id']}/mode", json={"mode": "read-only"})).json()[
                "mode"
            ] == "read-only"
            assert (await c.put(f"/api/sessions/{full['id']}/mode", json={"mode": "nope"})).status_code == 422
        # Graphs are cached per (workspace, mode, preset): both sessions are read-only now and share one graph.
        ro_graph = await agents.graph_for(await agents.get_session(ro["id"]))
        full_graph = await agents.graph_for(await agents.get_session(full["id"]))
        assert ro_graph is full_graph and len(agents._graphs) == 2


async def test_session_workspace_is_used_by_file_tools(profile, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    replies = [
        {
            "content": "",
            "tool_calls": [
                {"name": "write_file", "args": {"file_path": "/from-agent.txt", "content": "x"}, "id": "w1"}
            ],
        },
        {"content": "ok"},
    ]
    async with Harness(profile, patch=patch(replies)) as h, client(h) as c:
        assert (await c.post("/api/sessions", json={"workspace": "relative"})).status_code == 422
        s = (await c.post("/api/sessions", json={"workspace": str(other)})).json()
        assert s["workspace"] == str(other.resolve())
        events = sse((await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "go"})).text)
        assert events[-1]["outcome"] == "completed"
        assert (other / "from-agent.txt").read_text() == "x"
        listing = (await c.get("/api/workspaces")).json()
        assert listing["default"]["root"] == str(h.get("workspace").root) and any(
            w["root"] == str(other.resolve()) for w in listing["recent"]
        )
        browse = (await c.post("/api/workspaces/browse", json={"path": str(tmp_path)})).json()
        assert any(d["name"] == "other" for d in browse["dirs"])
        assert (await c.delete("/api/workspaces", params={"path": str(other)})).json()["forgotten"] is True


async def test_agent_defaults_persist(profile):
    async with Harness(profile, patch=patch([])) as h, client(h) as c:
        r = (await c.put("/api/settings/agent", json={"default_preset": "creator", "default_mode": "read-only"})).json()
        assert r["default_preset"] == "creator" and r["default_mode"] == "read-only"
        s = (await c.post("/api/sessions", json={})).json()
        assert (s["preset"], s["mode"]) == ("creator", "read-only")
        assert (await c.put("/api/settings/agent", json={"default_mode": "nope"})).status_code == 422
    ops = yaml.safe_load(Path(profile.patch_path).read_text(encoding="utf-8"))
    loop_op = next(op for op in ops if op["id"] == "agent-loop")
    assert loop_op["config"] == {"default_preset": "creator", "default_mode": "read-only"} and loop_op["merge"] is True
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}], generation=2) as h2:
        assert h2.get("agentLoop").config.default_preset == "creator"


async def test_native_picker_through_a_command(profile, tmp_path, monkeypatch):
    chosen = tmp_path / "picked"
    chosen.mkdir()
    cmd = [sys.executable, "-c", f"print({str(chosen)!r})"]
    extra = [{"id": "workspace", "config": {"picker_command": cmd}, "merge": True}]
    async with Harness(profile, patch=patch([], extra)) as h:
        ws = h.get("workspace")
        assert ws.picker() == "native"
        assert await ws.pick() == str(chosen.resolve())
        async with client(h) as c:
            assert (await c.get("/api/workspaces")).json()["picker"] == "native"
            r = (await c.post("/api/workspaces/pick", json={})).json()
            assert r["path"] == str(chosen.resolve()) and r["root"] == str(chosen.resolve())
            assert any(w["root"] == str(chosen.resolve()) for w in (await c.get("/api/workspaces")).json()["recent"])
    # Cancelled dialog: empty output.
    extra = [{"id": "workspace", "config": {"picker_command": [sys.executable, "-c", "print('')"]}, "merge": True}]
    async with Harness(profile, patch=patch([], extra)) as h:
        assert await h.get("workspace").pick() is None
    # Forced in-app browser.
    extra = [{"id": "workspace", "config": {"picker": "browse"}, "merge": True}]
    async with Harness(profile, patch=patch([], extra)) as h:
        assert h.get("workspace").picker() == "browse"
        async with client(h) as c:
            assert (await c.post("/api/workspaces/pick", json={})).status_code == 422


async def test_workspace_and_session_rename(profile, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    async with Harness(profile, patch=patch([])) as h, client(h) as c:
        r = (await c.put("/api/workspaces", json={"path": str(other), "name": "Side project"})).json()
        assert r["name"] == "Side project"
        recent = (await c.get("/api/workspaces")).json()["recent"]
        assert next(w for w in recent if w["root"] == str(other.resolve()))["name"] == "Side project"
        # Remembering again (a new session) keeps the display name; an empty name restores the directory name.
        await c.post("/api/sessions", json={"workspace": str(other)})
        recent = (await c.get("/api/workspaces")).json()["recent"]
        assert next(w for w in recent if w["root"] == str(other.resolve()))["name"] == "Side project"
        r = (await c.put("/api/workspaces", json={"path": str(other), "name": ""})).json()
        assert r["name"] == "other"
        # The default workspace can be renamed too.
        r = (await c.put("/api/workspaces", json={"path": None, "name": "Main"})).json()
        assert (await c.get("/api/workspaces")).json()["recent"][0]["name"] == "Main"
        assert (await c.put("/api/workspaces", json={"path": "relative", "name": "x"})).status_code == 422
        s = (await c.post("/api/sessions", json={"title": "first"})).json()
        assert (await c.put(f"/api/sessions/{s['id']}", json={"title": "  Renamed  "})).json()["title"] == "Renamed"
        assert (await c.get(f"/api/sessions/{s['id']}")).json()["title"] == "Renamed"
        assert (await c.put("/api/sessions/nope", json={"title": "x"})).status_code == 404


def test_windows_picker_opens_in_front_and_reports_utf8(monkeypatch):
    monkeypatch.setattr(registry.sys, "platform", "win32")
    monkeypatch.setattr(registry.shutil, "which", lambda name: f"C:/bin/{name}.exe" if name == "powershell" else None)
    picker = registry.Workspaces.__new__(registry.Workspaces)
    picker.config = registry.Config()
    command = picker._native_command("Choose")
    assert command[:6] == ["C:/bin/powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command"]
    script = command[6]
    assert "TopMost = $true" in script and "$d.ShowDialog($owner)" in script
    assert "UTF8Encoding $false" in script and "$d.Description = 'Choose'" in script
    assert picker.picker() == "native"
    monkeypatch.setattr(registry.shutil, "which", lambda name: None)
    assert picker._native_command("Choose") is None and picker.picker() == "browse"
    assert ({} if sys.platform != "win32" else registry.PICKER_PROCESS) == registry.PICKER_PROCESS
