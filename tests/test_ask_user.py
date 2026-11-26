"""ask_user_question: the run pauses on a question card and resumes with the answers."""

from __future__ import annotations

import json

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_ask_user import normalize_answers
from test_agent import scripted_patch, sse_events

QUESTIONS = [
    {
        "id": "mode",
        "question": "Which mode?",
        "header": "Choose mode",
        "options": [{"label": "Fast (Recommended)"}, {"label": "Careful", "description": "Slower"}],
    },
    {"id": "name", "question": "Project name?"},
]


def test_normalize_answers():
    out = normalize_answers(QUESTIONS, {"answers": [{"id": "name", "custom": " demo "}]})
    assert out == [{"id": "mode", "selected": []}, {"id": "name", "selected": [], "custom": "demo"}]
    with pytest.raises(ValueError, match="unknown question ids: nope"):
        normalize_answers(QUESTIONS, [{"id": "nope", "selected": []}])
    with pytest.raises(ValueError):
        normalize_answers(QUESTIONS, "x")


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


async def test_question_pauses_and_answers_resume(profile):
    replies = [
        {"content": "", "tool_calls": [{"name": "ask_user_question", "args": {"questions": QUESTIONS}, "id": "q1"}]},
        {"content": "ok: Fast, demo"},
    ]
    async with (
        Harness(profile, patch=scripted_patch(replies)) as h,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=60) as c,
    ):
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        events = sse_events((await c.post(f"/api/sessions/{sid}/messages", json={"content": "set up"})).text)
        assert [e["type"] for e in events] == ["context", "tool_call", "interrupt", "done"]
        assert events[-1]["outcome"] == "interrupted"
        (pending,) = events[2]["interrupts"]
        assert pending["value"]["kind"] == "ask_user" and [q["id"] for q in pending["value"]["questions"]] == [
            "mode",
            "name",
        ]
        assert pending["value"]["questions"][0]["options"][1] == {"label": "Careful", "description": "Slower"}
        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert detail["pending"][0]["id"] == pending["id"]
        # Messages are refused while the question is open; bad answers are 422.
        assert (await c.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})).status_code == 409
        r = await c.post(f"/api/sessions/{sid}/answers", json={"answers": [{"id": "zzz", "selected": []}]})
        assert r.status_code == 422
        assert (
            await c.post(f"/api/sessions/{sid}/answers", json={"answers": [], "interrupt_id": "nope"})
        ).status_code == 409
        r = await c.post(
            f"/api/sessions/{sid}/answers",
            json={"answers": [{"id": "mode", "selected": ["Fast (Recommended)"]}, {"id": "name", "custom": "demo"}]},
        )
        resumed = sse_events(r.text)
        assert [e["type"] for e in resumed] == ["tool_result", "context", "token", "done"], resumed
        result = json.loads(resumed[0]["content"])
        assert result == {
            "answers": [
                {"id": "mode", "selected": ["Fast (Recommended)"]},
                {"id": "name", "selected": [], "custom": "demo"},
            ]
        }
        assert resumed[-1]["outcome"] == "completed" and resumed[-1]["extras"]["turn"]["kind"] == "answer"
        assert (await c.post(f"/api/sessions/{sid}/answers", json={"answers": []})).status_code == 409
        roles = [m["role"] for m in (await c.get(f"/api/sessions/{sid}")).json()["messages"]]
        assert roles == ["human", "ai", "tool", "ai"]
