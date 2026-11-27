from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_agent.service import APPROVALS, rejectable
from testkit import tools as testtools

DANGER = {"content": "", "tool_calls": [{"name": "danger", "args": {"target": "prod"}, "id": "d1"}]}


def patch(replies, *, timeout=None, by_generation=None):
    scripted = {"replies": replies, **({"by_generation": by_generation} if by_generation else {})}
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": scripted},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "testtools", "name": "testkit.tools", "after": "tools"},
        {"id": "http", "config": {"serve": False}},
        {"id": "agents", "merge": True, "config": {"approval_timeout": timeout}},
        {"id": "agent-loop", "merge": True, "config": {"default_mode": "workspace-write"}},
    ]


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


async def settled(agents, session_id, *, runs):
    """Wait until the session's ``runs``-th turn is recorded."""
    for _ in range(200):
        if len(await agents.turns(session_id)) >= runs and not agents.busy(session_id):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the run did not settle")


def test_rejectable_is_one_approval_whose_calls_can_be_rejected():
    request = {"name": "danger", "args": {}}
    approval = {"action_requests": [request], "review_configs": [{"allowed_decisions": ["approve", "reject"]}]}
    assert rejectable([{"id": "i", "value": approval}]) == [request]
    assert rejectable([]) is None
    assert rejectable([{"id": "i", "value": {"kind": "ask_user", "questions": []}}]) is None
    assert rejectable([{"id": "i", "value": approval}, {"id": "j", "value": approval}]) is None
    only_approve = {**approval, "review_configs": [{"allowed_decisions": ["approve"]}]}
    assert rejectable([{"id": "i", "value": only_approve}]) is None


async def test_approval_past_its_time_limit_is_rejected(profile):
    testtools.RESULTS.clear()
    async with Harness(profile, patch=patch([DANGER, {"content": "moved on"}], timeout=0.3)) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        before = time.time()
        events = await agents.start_run(session["id"], "go").wait()
        interrupt = next(e for e in events if e["type"] == "interrupt")
        assert before + 0.3 <= interrupt["deadline"] <= time.time() + 0.3
        assert agents.approval_deadline(session["id"]) == interrupt["deadline"]
        assert (await h.get("store").aget(APPROVALS, session["id"])).value == {"deadline": interrupt["deadline"]}

        await settled(agents, session["id"], runs=2)
        turns = await agents.turns(session["id"])
        assert [(t["kind"], t["outcome"]) for t in turns] == [("message", "interrupted"), ("approval", "completed")]
        messages = await agents.messages(session["id"])
        assert (
            messages[-2]["status"] == "error"
            and "within 0.3 s, so the call was not executed" in messages[-2]["content"]
        )
        assert messages[-1]["content"] == "moved on" and testtools.RESULTS == []
        assert agents.approval_deadline(session["id"]) is None
        assert await h.get("store").aget(APPROVALS, session["id"]) is None


async def test_a_decision_in_time_ends_the_time_limit(profile):
    testtools.RESULTS.clear()
    async with Harness(profile, patch=patch([DANGER, {"content": "done"}], timeout=0.4)) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        await agents.start_run(session["id"], "go").wait()
        events = await agents.start_run(session["id"], decisions=[{"type": "approve"}]).wait()
        assert events[-1]["outcome"] == "completed" and testtools.RESULTS == [("danger", "destroyed prod")]
        assert agents.approval_deadline(session["id"]) is None
        await asyncio.sleep(0.6)
        assert len(await agents.turns(session["id"])) == 2


async def test_approvals_wait_without_a_time_limit(profile):
    async with Harness(profile, patch=patch([DANGER])) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        events = await agents.start_run(session["id"], "go").wait()
        assert "deadline" not in next(e for e in events if e["type"] == "interrupt")
        assert agents.approval_deadline(session["id"]) is None
        assert await h.get("store").asearch(APPROVALS) == []


async def test_time_limit_survives_a_restart(profile):
    testtools.RESULTS.clear()
    replies = {"replies": [DANGER], "by_generation": {2: [{"content": "moved on"}]}}
    async with Harness(profile, patch=patch(**replies, timeout=0.5)) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        await agents.start_run(session["id"], "go").wait()
        deadline = agents.approval_deadline(session["id"])
    async with Harness(profile, patch=patch(**replies, timeout=0.5), generation=2) as h2:
        agents = h2.get("agents")
        assert agents.approval_deadline(session["id"]) == deadline
        await settled(agents, session["id"], runs=2)
        assert (await agents.messages(session["id"]))[-1]["content"] == "moved on" and testtools.RESULTS == []
    # Without a time limit the next generation drops what is left of one.
    async with Harness(profile, patch=patch([DANGER], timeout=0.5), generation=3) as h3:
        agents = h3.get("agents")
        other = await agents.create_session()
        await agents.start_run(other["id"], "go").wait()
    async with Harness(profile, patch=patch([]), generation=4) as h4:
        assert h4.get("agents").approval_deadline(other["id"]) is None
        assert await h4.get("store").asearch(APPROVALS) == []
        assert await h4.get("agents").pending(other["id"])


async def test_time_limit_setting(profile):
    async with Harness(profile, patch=patch([DANGER])) as h:
        http, agents = h.get("http"), h.get("agents")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t") as c:
            assert (await c.get("/api/agent")).json()["approval_timeout"] is None
            saved = (await c.put("/api/settings/agent", json={"approval_timeout": 120})).json()
            assert saved["approval_timeout"] == 120 and agents.config.approval_timeout == 120
            assert (await c.put("/api/settings/agent", json={"approval_timeout": 0})).status_code == 422
            # Other fields leave it alone; a pending approval reports its deadline.
            assert (await c.put("/api/settings/agent", json={"default_mode": "workspace-write"})).json()[
                "approval_timeout"
            ] == 120
            sid = (await c.post("/api/sessions", json={})).json()["id"]
            await c.post(f"/api/sessions/{sid}/messages", json={"content": "go"})
            detail = (await c.get(f"/api/sessions/{sid}")).json()
            assert time.time() + 100 < detail["approval_deadline"] <= time.time() + 120
            assert (await c.put("/api/settings/agent", json={"approval_timeout": None})).json()[
                "approval_timeout"
            ] is None
    entry = next(op for op in profile.patch_ops_raw() if op["id"] == "agents")
    assert entry["config"] == {"approval_timeout": None}
