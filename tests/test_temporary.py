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
from testkit import tools as testtools

DANGER = {"content": "", "tool_calls": [{"name": "danger", "args": {"target": "prod"}, "id": "d1"}]}
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


async def test_a_temporary_session_stays_out_of_the_session_store(profile, workspace):
    git(workspace, "init", "-q")
    git(workspace, "commit", "-q", "--allow-empty", "-m", "init")
    async with Harness(profile, patch=patch([WRITE, {"content": "written"}, {"content": "kept"}])) as h, client(h) as c:
        agents = h.get("agents")
        created = (await c.post("/api/sessions", json={"temporary": True})).json()
        sid = created["id"]
        assert created["temporary"] is True and await agents.is_temporary(sid)
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "write it"})).text)
        assert events[-1]["outcome"] == "completed" and events[-1]["extras"]["changes"]["total"] == 1

        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert [m["role"] for m in detail["messages"]] == ["human", "ai", "tool", "ai"]
        assert detail["temporary"] is True and detail["title"] == "write it"
        assert len(detail["turns"]) == 1 and len(detail["changes"]) == 1
        assert await stored(h, sid) == NOTHING

        kept = (await c.post("/api/sessions", json={})).json()
        assert kept["temporary"] is False
        await c.post(f"/api/sessions/{kept['id']}/messages", json={"content": "hello"})
        assert (await stored(h, kept["id"]))["record"] is not None
        listed = {s["id"]: s["temporary"] for s in (await c.get("/api/sessions")).json()}
        assert listed == {sid: True, kept["id"]: False}

        changes = h.get("workspaceChanges")
        directory = changes._dirs[sid]
        assert directory.is_dir()
        assert (await c.delete(f"/api/sessions/{sid}")).json() == {"deleted": True}
        assert not directory.exists() and sid not in changes._dirs
        assert (await c.get(f"/api/sessions/{sid}")).status_code == 404
        temporary = h.get("temporary")
        assert await temporary.store.asearch(("pyharness",), limit=100) == []
        assert await temporary.checkpointer.aget_tuple({"configurable": {"thread_id": sid}}) is None


async def test_an_approval_of_a_temporary_session(profile):
    testtools.RESULTS.clear()
    limited = [{"id": "agents", "merge": True, "config": {"approval_timeout": 120}}]
    async with Harness(profile, patch=patch([DANGER, {"content": "finished"}], extra=limited)) as h, client(h) as c:
        sid = (await c.post("/api/sessions", json={"temporary": True})).json()["id"]
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "go"})).text)
        assert events[-2]["type"] == "interrupt" and events[-1]["outcome"] == "interrupted"
        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert detail["pending"] and time.time() < detail["approval_deadline"] <= time.time() + 120
        assert await h.get("temporary").store.aget(APPROVALS, sid) is not None
        assert await stored(h, sid) == NOTHING
        approved = await c.post(f"/api/sessions/{sid}/approvals", json={"decisions": [{"type": "approve"}]})
        assert sse(approved.text)[-1]["outcome"] == "completed" and testtools.RESULTS == [("danger", "destroyed prod")]
        assert (await c.get(f"/api/sessions/{sid}")).json()["messages"][-1]["content"] == "finished"
        assert await h.get("temporary").store.aget(APPROVALS, sid) is None


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
