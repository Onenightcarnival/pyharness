"""Temporary sessions: thread and records in ``ctx.temporary``, never in the session store."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_agent.runs import TURNS
from pyxis_harness_agent.service import APPROVALS, NAMESPACE
from testkit import scripted, tools as testtools

WRITE = {
    "content": "",
    "tool_calls": [{"name": "write_file", "args": {"file_path": "/n.txt", "content": "x\n"}, "id": "w1"}],
}


def patch(replies, *, extra=None):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "testtools", "name": "testkit.tools", "after": "tools"},
        {"id": "http", "config": {"serve": False}},
        {"id": "agent-loop", "merge": True, "config": {"default_mode": "workspace-write"}},
        *(extra or []),
    ]


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120)


def git(cwd, *args):
    author = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **author}, check=True, capture_output=True)


def sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


async def stored(h, session_id):
    """What the session store and the checkpointer hold of the session."""
    store = h.get("store")
    thread = await h.get("agents").graph.aget_state({"configurable": {"thread_id": session_id}})
    return {
        "record": await store.aget(NAMESPACE, session_id),
        "turns": await store.asearch((*TURNS, session_id)),
        "approval": await store.aget(APPROVALS, session_id),
        "changes": await store.asearch(("pyharness", "changes", session_id)),
        "messages": (thread.values or {}).get("messages", []),
    }


NOTHING = {"record": None, "turns": [], "approval": None, "changes": [], "messages": []}


def tools_of(graph):
    """Names of the tools a compiled agent graph can call."""
    node = getattr(graph, "bound", graph).nodes.get("tools")
    return sorted(node.bound.tools_by_name) if node is not None else []


async def test_a_temporary_session_is_a_chat_outside_the_session_store(profile, workspace):
    scripted.CALLS.clear()
    async with Harness(profile, patch=patch([{"content": "hi there"}, {"content": "kept"}])) as h, client(h) as c:
        agents = h.get("agents")
        created = (await c.post("/api/sessions", json={"temporary": True})).json()
        sid = created["id"]
        assert (created["temporary"], created["workspace"], created["mode"], created["preset"]) == (
            True,
            None,
            None,
            None,
        )
        assert await agents.is_temporary(sid)
        (workspace / "a.txt").write_text("secret\n")
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "read @a.txt"})).text)
        assert events[-1]["outcome"] == "completed" and "references" not in {e["type"] for e in events}

        system, user = scripted.CALLS[-1]["messages"][0][1], scripted.CALLS[-1]["messages"][-1][1]
        assert "## Temporary chat" in system and "Workspace root" not in system and "Permission mode" not in system
        assert user == "read @a.txt"  # no workspace: the reference stays text
        assert tools_of(await agents.graph_for(created)) == ["web_fetch", "web_search"]  # the default chat_tools
        assert "write_file" in tools_of(await agents.graph_for(None))

        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert [m["role"] for m in detail["messages"]] == ["human", "ai"] and detail["title"] == "read @a.txt"
        assert len(detail["turns"]) == 1
        assert detail["changes"] == [] and await stored(h, sid) == NOTHING

        for field in ("mode", "preset"):
            refused = await c.put(f"/api/sessions/{sid}/{field}", json={field: "read-only"})
            assert refused.status_code == 422 and "temporary" in refused.json()["detail"]
        for extra in ({"workspace": str(workspace)}, {"mode": "read-only"}, {"preset": "creator"}):
            assert (await c.post("/api/sessions", json={"temporary": True, **extra})).status_code == 422

        kept = (await c.post("/api/sessions", json={})).json()
        assert kept["temporary"] is False and kept["mode"] == "workspace-write"
        await c.post(f"/api/sessions/{kept['id']}/messages", json={"content": "hello"})
        assert (await stored(h, kept["id"]))["record"] is not None
        listed = {s["id"]: s["temporary"] for s in (await c.get("/api/sessions")).json()}
        assert listed == {sid: True, kept["id"]: False}

        assert (await c.delete(f"/api/sessions/{sid}")).json() == {"deleted": True}
        assert (await c.get(f"/api/sessions/{sid}")).status_code == 404
        temporary = h.get("temporary")
        assert await temporary.store.asearch(("pyharness",), limit=100) == []
        assert await temporary.checkpointer.aget_tuple({"configurable": {"thread_id": sid}}) is None


async def test_a_temporary_chat_keeps_the_listed_tools_without_an_approval_gate(profile):
    testtools.RESULTS.clear()
    shout = {"content": "", "tool_calls": [{"name": "shout", "args": {"text": "hi"}, "id": "s1"}]}
    listed = [{"id": "agent-loop", "merge": True, "config": {"chat_tools": ["shout", "danger", "absent"]}}]
    async with Harness(profile, patch=patch([shout, {"content": "done"}], extra=listed)) as h, client(h) as c:
        created = (await c.post("/api/sessions", json={"temporary": True})).json()
        assert tools_of(await h.get("agents").graph_for(created)) == ["shout"]  # danger asks for approval
        events = sse((await c.post(f"/api/sessions/{created['id']}/messages", json={"content": "go"})).text)
        assert [e["type"] for e in events if e["type"].startswith("tool")] == ["tool_call", "tool_result"]
        assert events[-1]["outcome"] == "completed" and testtools.RESULTS == [("shout", "HI")]
        assert await stored(h, created["id"]) == NOTHING


async def test_a_deleted_session_leaves_no_change_summaries(profile, workspace):
    git(workspace, "init", "-q")
    git(workspace, "commit", "-q", "--allow-empty", "-m", "init")
    async with Harness(profile, patch=patch([WRITE, {"content": "written"}])) as h, client(h) as c:
        sid = (await c.post("/api/sessions", json={"mode": "full-access"})).json()["id"]
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "write it"})).text)
        assert events[-1]["extras"]["changes"]["total"] == 1
        changes = h.get("workspaceChanges")
        directory = changes._dirs[sid]
        assert directory.is_dir() and len((await stored(h, sid))["changes"]) == 1
        assert (await c.delete(f"/api/sessions/{sid}")).json() == {"deleted": True}
        assert not directory.exists() and sid not in changes._dirs
        assert await stored(h, sid) == NOTHING


async def test_temporary_sessions_end_with_the_process(profile):
    async with Harness(profile, patch=patch([{"content": "a"}, {"content": "b"}])) as h:
        agents = h.get("agents")
        gone = await agents.create_session(temporary=True)
        kept = await agents.create_session()
        await agents.start_run(gone["id"], "x").wait()
        await agents.start_run(kept["id"], "y").wait()
    profile.runtime.mkdir(parents=True, exist_ok=True)
    handoff = {"reasons": ["test"], "resume": [gone["id"], kept["id"]]}
    (profile.runtime / "resume.json").write_text(json.dumps(handoff))
    async with Harness(profile, patch=patch([{"content": "continuing"}]), generation=2, supervised=True) as h2:
        agents = h2.get("agents")
        assert await agents.get_session(gone["id"]) is None
        assert [s["id"] for s in await agents.list_sessions()] == [kept["id"]]
        assert await agents.messages(gone["id"]) == []
        for _ in range(200):
            if len(await agents.turns(kept["id"])) == 2 and not agents.busy(kept["id"]):
                break
            await asyncio.sleep(0.02)
        assert (await agents.messages(kept["id"]))[-1]["content"] == "continuing"


async def test_a_temporary_session_expires_after_its_last_turn(profile):
    short = [{"id": "agents", "merge": True, "config": {"temporary_ttl": 60}}]
    async with Harness(profile, patch=patch([{"content": "a"}], extra=short)) as h:
        agents = h.get("agents")
        old, fresh, kept = (
            await agents.create_session(temporary=True),
            await agents.create_session(temporary=True),
            await agents.create_session(),
        )
        await agents.start_run(old["id"], "x").wait()
        now = time.time()
        assert await agents.expire_temporary(now + 30) == []
        await agents.set_title(fresh["id"], "still here")
        record = await agents.get_session(fresh["id"])
        await h.get("temporary").store.aput(NAMESPACE, fresh["id"], record | {"updated_at": now + 40})
        assert await agents.expire_temporary(now + 90) == [old["id"]]
        assert {s["id"] for s in await agents.list_sessions()} == {fresh["id"], kept["id"]}
        agents.config.temporary_ttl = None
        assert await agents.expire_temporary(now + 10_000) == []


async def test_temporary_sessions_need_their_provider(profile):
    without = [{"id": "checkpoint-temporary", "remove": True}]
    async with Harness(profile, patch=patch([{"content": "a"}], extra=without)) as h, client(h) as c:
        refused = await c.post("/api/sessions", json={"temporary": True})
        assert refused.status_code == 422 and "temporary" in refused.json()["detail"]
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        assert (
            sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "x"})).text)[-1]["outcome"]
            == "completed"
        )
        assert await h.get("agents").expire_temporary() == []
