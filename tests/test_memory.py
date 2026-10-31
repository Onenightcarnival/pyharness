"""Career memory: store commits and history, memory_get / memory_save tools, the agent-access switch, the HTTP routes."""

from __future__ import annotations

import json

import httpx
import pytest
from pyharness_memory import MemoryService
from pyharness_memory.store import MemoryError, MemoryStore, sort_entries

from pyharness import Harness, Profile

HTTP_OFF = {"id": "http", "config": {"serve": False}}


def run(tool, args):
    """Invoke as the agent loop does (a full tool call, so the injected call id is present)."""
    return json.loads(tool.invoke({"name": tool.name, "args": args, "id": "call-1", "type": "tool_call"}).content)


def test_store_commits_validates_and_keeps_history(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    assert store.state() == {
        "schemaVersion": 1,
        "revision": 0,
        "entries": [{"id": "profile", "kind": "profile", "fields": {}}],
        "agentTools": True,
        "history": [],
    }
    st = store.commit(
        {
            "baseRevision": 0,
            "summary": "seed",
            "changes": [
                {"id": "w1", "kind": "work", "fields": {"organization": "ACME", "startDate": "2024-01-01", "endDate": "present"}},
                {"id": "p1", "kind": "project", "fields": {"title": "Port", "workId": "w1", "startDate": "2025-02-01"}},
                {"id": "l1", "kind": "lesson", "fields": {"parentId": "p1", "lesson": "Read before writing."}},
            ],
        },
        "human",
        "ui",
    )
    assert (
        st["revision"] == 1
        and [e["id"] for e in st["entries"]] == ["profile", "w1", "p1", "l1"]
        and st["entries"][1]["createdAt"].endswith("Z")
    )
    assert st["history"][0]["actor"] == "human" and st["history"][0]["summary"] == "seed"
    with pytest.raises(MemoryError, match="conflict"):
        store.commit({"baseRevision": 0, "summary": "stale", "changes": []}, "human", "ui")
    for bad, code in [
        ({"id": "x", "kind": "lesson", "fields": {"parentId": "nope", "lesson": "x"}}, "reference"),
        ({"id": "x", "kind": "project", "fields": {"title": ""}}, "content"),
        ({"id": "x", "kind": "work", "fields": {"organization": "A", "startDate": "2024-13-01"}}, "date"),
        ({"id": "x", "kind": "work", "fields": {"organization": "A", "startDate": "2024-02-01", "endDate": "2024-01-01"}}, "dateRange"),
        ({"id": "p1", "kind": "project", "remove": True}, "reference"),  # l1 still references it
        ({"id": "profile", "kind": "profile", "remove": True}, "invalid"),
    ]:
        with pytest.raises(MemoryError) as info:
            store.commit({"baseRevision": 1, "summary": "bad", "changes": [bad]}, "human", "ui")
        assert info.value.code == code, bad
    with pytest.raises(MemoryError, match="protected"):
        store.commit({"baseRevision": 1, "summary": "agent restore", "restore": 1}, "agent", "session:x")
    # A no-op commit creates no revision; an empty string clears a field.
    assert (
        store.commit(
            {"baseRevision": 1, "summary": "same", "changes": [{"id": "w1", "kind": "work", "fields": {"organization": "ACME"}}]},
            "human",
            "ui",
        )["revision"]
        == 1
    )
    st = store.commit(
        {"baseRevision": 1, "summary": "edit", "changes": [{"id": "w1", "kind": "work", "fields": {"jobTitle": "Lead", "endDate": ""}}]},
        "human",
        "ui",
    )
    assert st["revision"] == 2 and st["entries"][1]["fields"] == {
        "organization": "ACME",
        "startDate": "2024-01-01",
        "endDate": "",
        "jobTitle": "Lead",
    }
    d = store.diff(2)
    assert d["before"]["entries"][1]["fields"]["endDate"] == "present" and d["after"]["entries"][1]["fields"]["jobTitle"] == "Lead"
    assert store.diff(1)["before"]["entries"] == [{"id": "profile", "kind": "profile", "fields": {}}] and store.diff(9) is None
    st = store.commit({"baseRevision": 2, "summary": "restore", "restore": 1}, "human", "ui")
    assert st["revision"] == 3 and st["entries"][1]["fields"]["endDate"] == "present"
    st = store.commit(
        {
            "baseRevision": 3,
            "summary": "import",
            "imported": {"schemaVersion": 1, "entries": [{"id": "profile", "kind": "profile", "fields": {"name": "Pyh"}}]},
        },
        "human",
        "ui",
    )
    assert [e["id"] for e in st["entries"]] == ["profile"] and len(st["history"]) == 4
    assert store.set_agent_tools(False)["agentTools"] is False and store.state()["revision"] == 4
    with pytest.raises(MemoryError, match="disabled"):
        store.commit(
            {"baseRevision": 4, "summary": "x", "changes": [{"id": "w9", "kind": "work", "fields": {"organization": "B"}}]}, "agent", "s"
        )
    st = store.clear(4)
    assert (
        st["revision"] == 5
        and st["history"] == []
        and st["entries"] == [{"id": "profile", "kind": "profile", "fields": {}}]
        and st["agentTools"] is False
    )
    store.close()
    entries = [
        {"id": "a", "kind": "work", "fields": {"startDate": "2020-01-01"}},
        {"id": "b", "kind": "work", "fields": {}},
        {"id": "c", "kind": "work", "fields": {"endDate": "2022-01-01"}},
        {"id": "d", "kind": "work", "fields": {"endDate": "present"}},
    ]
    assert [e["id"] for e in sort_entries(entries)] == ["c", "a", "b", "d"] and [e["id"] for e in sort_entries(entries, "oldest")] == [
        "a",
        "c",
        "b",
        "d",
    ]


async def test_tools_prompt_switch_and_routes(home, tmp_path):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF, {"id": "memory", "config": {"path": str(tmp_path / "mem.sqlite")}, "merge": True}]) as h:
        memory: MemoryService = h.get("memory")
        tools = {t.name: t for t in h.get("tools").list()}
        assert {"memory_get", "memory_save"} <= set(tools) and "Career memory is this agent's own resume." in h.get("prompt").render()
        schema = tools["memory_save"].tool_call_schema.model_json_schema()
        assert "tool_call_id" not in schema["properties"] and schema["required"] == ["stateToken", "summary", "changes"]
        root = run(tools["memory_get"], {})
        assert (
            root["ok"] is True
            and root["stateToken"] == "r:0"
            and root["entry"]["id"] == "profile"
            and root["children"] == {"items": [], "total": 0, "nextOffset": None}
        )
        saved = run(
            tools["memory_save"],
            {
                "stateToken": "r:0",
                "summary": "first job",
                "changes": [
                    {"kind": "work", "ref": "job", "fields": {"organization": "ACME", "startDate": "2024-01-01"}},
                    {"kind": "project", "ref": "proj", "fields": {"title": "Harness", "workId": "@job"}},
                    {"kind": "lesson", "fields": {"parentId": "@proj", "lesson": "Read first."}},
                    {"kind": "profile", "fields": {"name": "Pyh"}},
                ],
            },
        )
        assert saved["ok"] is True and saved["version"] == 1 and saved["stateToken"] == "r:1" and saved["changed"] is True
        assert set(saved["refs"]) == {"job", "proj"} and [r["kind"] for r in saved["records"]] == ["work", "project", "lesson", "profile"]
        stale = run(tools["memory_save"], {"stateToken": "r:0", "summary": "x", "changes": [{"kind": "profile", "fields": {"name": "Z"}}]})
        assert (
            stale["ok"] is False
            and stale["error"]["code"] == "conflict"
            and stale["error"]["retryable"] is True
            and stale["stateToken"] == "r:1"
        )
        node = run(tools["memory_get"], {"id": saved["refs"]["proj"]})
        assert (
            node["ancestors"][0]["title"] == "ACME"
            and node["children"]["items"][0]["title"] == "Read first."
            and node["children"]["total"] == 1
        )
        bad = run(
            tools["memory_save"],
            {"stateToken": "r:1", "summary": "x", "changes": [{"kind": "lesson", "fields": {"parentId": "@nope", "lesson": "x"}}]},
        )
        assert bad["error"]["code"] == "reference" and bad["error"]["detail"] == "@nope"
        removed = run(
            tools["memory_save"], {"stateToken": "r:1", "summary": "drop", "changes": [{"kind": "remove", "id": saved["records"][2]["id"]}]}
        )
        assert removed["ok"] is True and removed["records"] == [{"id": saved["records"][2]["id"], "kind": "remove", "removed": True}]
        assert memory.store.state()["history"][-1]["source"].startswith("session:")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=30) as c:
            st = (await c.get("/api/memory")).json()
            assert st["revision"] == 2 and len(st["entries"]) == 3 and st["agentTools"] is True
            d = (await c.get("/api/memory", params={"diff": "1"})).json()
            assert d["revision"] == 1 and len(d["after"]["entries"]) == 4
            assert (await c.get("/api/memory", params={"diff": "x"})).status_code == 404
            r = await c.post("/api/memory", json={"baseRevision": 1, "summary": "stale", "changes": []})
            assert r.status_code == 409 and r.json()["detail"] == {"error": "conflict", "detail": ""}
            r = await c.post(
                "/api/memory",
                json={
                    "baseRevision": 2,
                    "summary": "ui edit",
                    "changes": [{"id": "profile", "kind": "profile", "fields": {"name": "Pyh", "position": "harness"}}],
                },
            )
            assert r.status_code == 200 and r.json()["history"][-1] == {**r.json()["history"][-1], "actor": "human", "source": "ui"}
            r = await c.patch("/api/memory", json={"agentTools": False})
            assert r.json()["agentTools"] is False
            assert not any(t.name.startswith("memory_") for t in h.get("tools").list()) and "Career memory" not in h.get("prompt").render()
            r = await c.patch("/api/memory", json={"agentTools": True})
            assert r.json()["agentTools"] is True and {t.name for t in h.get("tools").list()} >= {"memory_get", "memory_save"}
            r = await c.request("DELETE", "/api/memory", content=json.dumps({"baseRevision": 3}))
            assert r.status_code == 200 and r.json()["history"] == [] and r.json()["revision"] == 4
            assert (await c.post("/api/memory", content=b"[]")).status_code == 400
        assert any(c["entry"] == "memory" for c in h.get("webui").clients())
