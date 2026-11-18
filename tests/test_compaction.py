"""Context compaction: measurement, cut selection, automatic and manual compaction over the scripted model, settings."""

from __future__ import annotations

import httpx
import pytest
import yaml
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from pyxis_harness import Harness, Profile
from pyxis_harness_compaction import checkpoint_message, cut_index, is_checkpoint, measure, summary_of
from test_agent import scripted_patch, sse_events
from testkit import scripted

LONG = "lorem ipsum dolor sit amet " * 60  # ~1600 chars ≈ 400 tokens by the approximate counter


def test_measure_prefers_usage_after_the_last_checkpoint():
    ai = AIMessage(content="ok", usage_metadata={"input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010})
    human = HumanMessage(content="x" * 400)
    assert measure([HumanMessage(content="hi"), ai, human]) == 1010 + measure([human])
    cp = checkpoint_message("summary", {"id": "1"})
    assert is_checkpoint(cp) and summary_of(cp.content) == "summary"
    # Usage before the checkpoint priced the replaced history: estimate everything instead.
    assert measure([ai, cp, human]) < 1010


def test_cut_index_keeps_tool_results_with_their_call():
    messages = [
        HumanMessage(content=LONG),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
        ToolMessage(content=LONG, tool_call_id="c1"),
        ToolMessage(content="short", tool_call_id="c1"),
        AIMessage(content="done"),
    ]
    # Retaining a few tokens would cut inside the tool results; the cut moves before the AI call.
    assert cut_index(messages, 10) == 1
    assert cut_index(messages, 0) == len(messages)  # manual: everything summarized
    assert cut_index(messages, 10**9) is None  # nothing to summarize
    assert cut_index([checkpoint_message("s", {}), HumanMessage(content="hi")], 0) == 2
    assert cut_index([checkpoint_message("s", {})], 0) is None


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


async def test_automatic_and_manual_compaction(profile):
    scripted.CALLS.clear()
    replies = [
        {"content": "first reply"},
        {"content": "## Primary Request and Intent\n- SUMMARY ONE"},  # the summarizer's call (automatic)
        {"content": "second reply"},
        {"content": "## Primary Request and Intent\n- SUMMARY TWO"},  # the summarizer's call (/compact)
    ]
    patch = scripted_patch(
        replies,
        extra=[
            {"id": "compaction", "config": {"default_context_window": 600, "threshold_ratio": 0.8, "retain_ratio": 0.2}}
        ],
    )
    async with Harness(profile, patch=patch) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t") as client:
            sid = (await client.post("/api/sessions", json={})).json()["id"]
            first = sse_events((await client.post(f"/api/sessions/{sid}/messages", json={"content": LONG})).text)
            assert [e["type"] for e in first] == ["token", "done"]
            # Second turn: ~800 estimated tokens ≥ 480 → the head (first exchange) becomes a checkpoint.
            second = sse_events(
                (await client.post(f"/api/sessions/{sid}/messages", json={"content": LONG + " again"})).text
            )
            kinds = [e["type"] for e in second]
            assert kinds == ["compact", "token", "done"], kinds
            compact = second[0]
            assert compact["trigger"] == "auto" and compact["removed"] == 2 and "SUMMARY ONE" in compact["summary"]
            assert compact["after_tokens"] < compact["before_tokens"]
            turn = second[-1]["extras"]["turn"]
            assert turn["stats"]["compactions"] == 1 and [r["t"] for r in turn["records"]] == [
                "user",
                "compact",
                "step",
                "end",
            ]
            detail = (await client.get(f"/api/sessions/{sid}")).json()
            roles = [(m["role"], m.get("harness", {}).get("kind")) for m in detail["messages"]]
            assert roles == [("human", "compact-checkpoint"), ("human", None), ("ai", None)]
            assert "SUMMARY ONE" in detail["messages"][0]["content"]
            # The summarizer saw a transcript, not the live prompt.
            summary_calls = [
                c
                for c in scripted.CALLS
                if "messages" in c and c["messages"][0][0] == "system" and "compaction engine" in c["messages"][0][1]
            ]
            assert len(summary_calls) == 1 and "Conversation transcript" in summary_calls[0]["messages"][1][1]
            # Manual: everything becomes one checkpoint; no model call.
            manual = sse_events((await client.post(f"/api/sessions/{sid}/compact")).text)
            assert [e["type"] for e in manual] == ["compact", "done"]
            assert (
                manual[0]["trigger"] == "manual" and manual[0]["removed"] == 3 and "SUMMARY TWO" in manual[0]["summary"]
            )
            assert manual[-1]["extras"]["turn"]["kind"] == "compact"
            detail = (await client.get(f"/api/sessions/{sid}")).json()
            assert [m.get("harness", {}).get("kind") for m in detail["messages"]] == ["compact-checkpoint"]
            # Nothing left to compact: the run ends without a compact event and the history is unchanged.
            again = sse_events((await client.post(f"/api/sessions/{sid}/compact")).text)
            assert [e["type"] for e in again] == ["done"] and again[0]["outcome"] == "completed"
            assert len((await client.get(f"/api/sessions/{sid}")).json()["messages"]) == 1
            # Settings: applied in place and persisted.
            r = await client.put("/api/settings/compaction", json={"auto": False, "threshold_ratio": 0.5})
            assert r.status_code == 200 and r.json()["auto"] is False and r.json()["threshold_ratio"] == 0.5
            assert (await client.get("/api/settings/compaction")).json()["retain_ratio"] == 0.2
            assert (await client.put("/api/settings/compaction", json={"threshold_ratio": 3})).status_code == 422
        patch_ops = yaml.safe_load(profile.patch_path.read_text())
        entry = next(op for op in patch_ops if op.get("id") == "compaction")
        assert entry["config"]["auto"] is False and entry["config"]["threshold_ratio"] == 0.5
