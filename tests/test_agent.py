"""End-to-end, base bundle: deepagents loop, tool pipeline, approvals, persistence, resume."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import types

import httpx
import pytest
import yaml
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from pyxis_harness import Harness, Profile
from pyxis_harness_agent_loop_deepagents import ContextMeter, RequestScope, context_sizes
from testkit import scripted, tools as testtools


def scripted_patch(replies, *, extra=None):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "testtools", "name": "testkit.tools", "after": "tools"},
        {"id": "http", "config": {"serve": False}},
        *(extra or []),
    ]


def yaml_of(profile) -> dict[str, dict]:
    """Entry id → the config saved in the profile patch."""
    return {o["id"]: o.get("config", {}) for o in yaml.safe_load((profile.dir / "harness.patch.yaml").read_text())}


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


async def test_tool_call_flows_through_pipeline_and_persists(profile):
    scripted.CALLS.clear()
    testtools.RESULTS.clear()
    replies = [
        {"content": "", "tool_calls": [{"name": "shout", "args": {"text": "hi"}, "id": "c1"}]},
        {"content": "done: HI"},
    ]
    async with Harness(profile, patch=scripted_patch(replies)) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t") as client:
            session = (await client.post("/api/sessions", json={})).json()
            res = await client.post(f"/api/sessions/{session['id']}/messages", json={"content": "shout hi"})
            events = sse_events(res.text)
            kinds = [e["type"] for e in events]
            assert kinds == ["context", "tool_call", "tool_result", "context", "token", "done"], kinds
            assert events[2]["content"] == "HI"
            # Each request of the main agent is measured by part before it is sent; the turn keeps the last one.
            first, second = (e for e in events if e["type"] == "context")
            assert first["system"] > 100 and first["tools"] > 100 and 0 < first["messages"] < second["messages"]
            assert (first["system"], first["tools"]) == (second["system"], second["tools"])
            assert events[-1]["extras"]["turn"]["stats"]["context"] == {
                part: second[part] for part in ("system", "tools", "messages")
            }
            assert events[-1]["outcome"] == "completed"
            detail = (await client.get(f"/api/sessions/{session['id']}")).json()
            assert [m["role"] for m in detail["messages"]] == ["human", "ai", "tool", "ai"]
            assert detail["title"] == "shout hi"
        assert testtools.RESULTS == [("shout", "HI")]
        # System prompt: plugin sections (identity, plugin authoring).
        system = next(c for c in scripted.CALLS if "messages" in c)["messages"][0]
        assert system[0] == "system" and "PyxisHarness" in system[1] and "Extending this harness" in system[1]

    # Next generation: same history (SQLite checkpointer, store).
    async with Harness(profile, patch=scripted_patch([]), generation=2) as h2:
        agents = h2.get("agents")
        assert [s["id"] for s in await agents.list_sessions()] == [session["id"]]
        assert len(await agents.messages(session["id"])) == 4


async def test_approval_gate(profile):
    testtools.RESULTS.clear()
    replies = [
        {"content": "", "tool_calls": [{"name": "danger", "args": {"target": "prod"}, "id": "d1"}]},
        {"content": "finished"},
    ]
    async with Harness(profile, patch=scripted_patch(replies)) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t") as client:
            sid = (await client.post("/api/sessions", json={"mode": "workspace-write"})).json()["id"]
            events = sse_events((await client.post(f"/api/sessions/{sid}/messages", json={"content": "go"})).text)
            assert events[-2]["type"] == "interrupt"
            assert events[-1]["outcome"] == "interrupted"
            assert testtools.RESULTS == []
            busy = await client.post(f"/api/sessions/{sid}/messages", json={"content": "again"})
            assert busy.status_code == 409
            events = sse_events(
                (await client.post(f"/api/sessions/{sid}/approvals", json={"decisions": [{"type": "approve"}]})).text
            )
            assert [e["type"] for e in events] == [
                "tool_call",
                "tool_result",
                "context",
                "token",
                "done",
            ]  # approved call is re-announced
            assert testtools.RESULTS == [("danger", "destroyed prod")]


async def test_tools_execute_waterfall_can_short_circuit(profile, tmp_path):
    def apply(ctx):
        @ctx.on("tools/execute")
        async def block(call, next):
            if call.name == "shout":
                return ToolMessage(content="blocked", name=call.name, tool_call_id=call.id, status="error")
            return await next()

    sys.modules["tk_blocker"] = types.SimpleNamespace(apply=apply, inject=["tools"], __name__="tk_blocker")
    testtools.RESULTS.clear()
    replies = [{"content": "", "tool_calls": [{"name": "shout", "args": {"text": "x"}, "id": "c1"}]}, {"content": "ok"}]
    patch = scripted_patch(replies, extra=[{"id": "blocker", "name": "tk_blocker"}])
    async with Harness(profile, patch=patch) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        events = await agents.start_run(session["id"], "go").wait()
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["content"] == "blocked" and result["status"] == "error"
        assert testtools.RESULTS == [("shout", "blocked")]  # tools/result observes the call


async def test_restart_handoff_continues_session(profile):
    scripted.CALLS.clear()
    async with Harness(profile, patch=scripted_patch([{"content": "first"}])) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        await agents.start_run(session["id"], "hello").wait()
        h.lifecycle.request_restart("new plugin installed", resume=[session["id"]])
        assert h.lifecycle.exit_code == 75  # no active run: restart due

    # Unsupervised harness (pyh exec, embedding): hand-off untouched.
    async with Harness(profile, patch=scripted_patch([]), generation=2) as other:
        assert other.get("agents").current_run(session["id"]) is None
    assert (profile.runtime / "resume.json").exists()

    async with Harness(profile, patch=scripted_patch([{"content": "continuing"}]), generation=2, supervised=True) as h2:
        agents = h2.get("agents")
        handle = agents.current_run(session["id"])
        assert handle is not None and handle.kind == "continuation"
        await handle.wait()
        messages = await agents.messages(session["id"])
        assert "Restarted into generation 2" in messages[-2]["content"]
        assert "new plugin installed" in messages[-2]["content"]
        assert messages[-2]["harness"] == {
            "kind": "continuation",
            "generation": 2,
            "reasons": ["new plugin installed"],
            "rollback": False,
            "rollback_error": None,
        }
        assert messages[-1]["content"] == "continuing"


async def test_read_only_mount_serves_one_preset(profile, tmp_path):
    reference = tmp_path / "reference"
    (reference / "inner").mkdir(parents=True)
    (reference / "inner" / "note.md").write_text("mounted text", encoding="utf-8")

    def read(id):
        return {"name": "read_file", "args": {"file_path": "/ref/docs/inner/note.md"}, "id": id}

    replies = [
        {"content": "", "tool_calls": [read("r1")]},
        {"content": "", "tool_calls": [{"name": "ls", "args": {"path": "/ref"}, "id": "l1"}]},
        {"content": "", "tool_calls": [{"name": "grep", "args": {"pattern": "mounted", "path": "/ref"}, "id": "g1"}]},
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/ref/docs/x.md", "content": "x"}, "id": "w1"}],
        },
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/ref/x.md", "content": "x"}, "id": "w2"}],
        },
        {"content": "done"},
        {"content": "", "tool_calls": [read("r2")]},
        {"content": "done"},
    ]
    async with Harness(profile, patch=scripted_patch(replies)) as h:
        loop, agents = h.get("agentLoop"), h.get("agents")
        loop.add_mount("ref/docs", reference, presets=["creator"])
        assert [m for m in loop.mounts() if m["owner"] == "<host>"] == [
            {
                "mount": "/ref/docs/",
                "path": str(reference.resolve()),
                "owner": "<host>",
                "presets": ["creator"],
                "writable": False,
            }
        ]
        assert loop.mounted(reference / "inner" / "note.md") == "/ref/docs/inner/note.md"
        assert loop.mounted(reference / "inner") == "/ref/docs/inner/"
        assert loop.mounted(reference) == "/ref/docs/"
        assert loop.mounted(tmp_path) is None
        for bad in ("/", "/skills/mine", "/ref/../docs", "/ref/docs/"):
            with pytest.raises(ValueError):
                loop.add_mount(bad, reference)
        with pytest.raises(ValueError):
            loop.add_mount("/absent", tmp_path / "absent")

        session = await agents.create_session(preset="creator")
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert results["r1"]["status"] == "success" and "mounted text" in results["r1"]["content"]
        assert results["l1"]["status"] == "success" and "/ref/docs/" in results["l1"]["content"]  # the parent lists
        assert results["g1"]["status"] == "success" and "/ref/docs/inner/note.md" in results["g1"]["content"]
        assert results["w1"]["status"] == "error" and "denied" in results["w1"]["content"]
        assert results["w2"]["status"] == "error" and "denied" in results["w2"]["content"]
        assert not (reference / "x.md").exists()

        session = await agents.create_session(preset="standard")
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert "mounted text" not in results["r2"]["content"]


async def test_writable_mount_takes_writes_outside_read_only_mode(profile, tmp_path):
    out, notes, docs = tmp_path / "out", tmp_path / "notes", tmp_path / "docs"
    for directory in (out, notes, docs):
        directory.mkdir()

    def write(id, path):
        return {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": path, "content": id}, "id": id}],
        }

    replies = [
        write("w1", "/out/a.md"),
        write("w2", "/ref/notes/b.md"),
        write("w3", "/ref/docs/c.md"),  # read-only beside a writable mount of the same route
        {"content": "done"},
        write("w4", "/out/d.md"),
        {"content": "done"},
    ]
    async with Harness(profile, patch=scripted_patch(replies)) as h:
        loop, agents = h.get("agentLoop"), h.get("agents")
        loop.add_mount("/out", out, writable=True)
        loop.add_mount("/ref/notes", notes, writable=True)
        loop.add_mount("/ref/docs", docs)
        assert [m["writable"] for m in loop.mounts() if m["owner"] == "<host>"] == [True, True, False]
        assert loop.mount_target("/out/a.md") == out.resolve() / "a.md"
        assert loop.mount_target("/ref/notes") == notes.resolve()
        assert loop.mount_target("/out/../a.md") is None and loop.mount_target("/elsewhere/a.md") is None

        session = await agents.create_session()
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert results["w1"]["status"] == "success" and (out / "a.md").read_text() == "w1"
        assert results["w2"]["status"] == "success" and (notes / "b.md").read_text() == "w2"
        assert results["w3"]["status"] == "error" and "denied" in results["w3"]["content"]

        session = await agents.create_session(mode="read-only")
        events = await agents.start_run(session["id"], "go").wait()
        results = {e["id"]: e for e in events if e["type"] == "tool_result"}
        assert results["w4"]["status"] == "error" and "denied" in results["w4"]["content"]
    assert not (docs / "c.md").exists() and not (out / "d.md").exists()


async def test_inspect_tool_reports_live_api(profile):
    async with Harness(profile, patch=scripted_patch([])) as h:
        tool = next(t for t in h.get("tools").list() if t.name == "harness_inspect")
        events = json.loads(tool.invoke({"topic": "events"}))
        modes = {e["name"]: e["mode"] for e in events}
        assert modes["tools/execute"] == "waterfall"
        assert modes["agent/model-request"] == "waterfall"
        assert modes["agent/turn-end"] == "parallel"
        config = json.loads(tool.invoke({"topic": "config", "name": "checkpoint"}))
        assert "store_path" in config["schema"]["properties"]
        services = json.loads(tool.invoke({"topic": "services", "name": "tools"}))
        assert any(m["name"] == "register" for m in services["methods"])


async def test_reasoning_cancel_and_delete(profile):
    replies = [
        {"reasoning": "think first", "content": "answer"},
        {"content": "", "tool_calls": [{"name": "slow", "args": {"seconds": 30}, "id": "z1"}]},
    ]
    async with Harness(profile, patch=scripted_patch(replies)) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t") as client:
            health = (await client.get("/api/health")).json()
            assert health["model"] == "scripted:test" and health["workspace"]["path"]
            sid = (await client.post("/api/sessions", json={})).json()["id"]
            events = sse_events((await client.post(f"/api/sessions/{sid}/messages", json={"content": "q"})).text)
            assert [e["type"] for e in events] == ["context", "reasoning", "token", "done"]
            detail = (await client.get(f"/api/sessions/{sid}")).json()
            assert detail["messages"][-1]["reasoning"] == "think first"

            agents = h.get("agents")
            handle = agents.start_run(sid, "slow please")
            for _ in range(100):
                if any(e["type"] == "tool_call" for e in handle.events):
                    break
                await asyncio.sleep(0.02)
            assert (await client.post(f"/api/sessions/{sid}/cancel")).json() == {"cancelled": True}
            assert handle.events[-1]["outcome"] == "cancelled"
            assert (await client.post(f"/api/sessions/{sid}/cancel")).json() == {"cancelled": False}

            assert (await client.delete(f"/api/sessions/{sid}")).json() == {"deleted": True}
            assert (await client.get(f"/api/sessions/{sid}")).status_code == 404
            assert (await client.get("/api/sessions")).json() == []
            assert (await client.delete(f"/api/sessions/{sid}")).status_code == 404


PNG_1PX = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


async def test_images_travel_with_messages_and_replies(profile):
    """Image data URLs reach the model as image_url blocks, are listed in history, and AI images stream as events."""
    scripted.CALLS.clear()
    replies = [{"content": "I see it.", "images": [PNG_1PX]}]
    llm = {
        "id": "llm",
        "config": {
            "default": "vision:v1",
            "providers": {
                "vision": {"type": "scripted", "models": [{"id": "v1", "input": ["text", "image"]}, {"id": "t1"}]}
            },
        },
    }
    patch = [op for op in scripted_patch(replies) if op["id"] != "llm"] + [llm]
    async with Harness(profile, patch=patch) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t") as client:
            sid = (await client.post("/api/sessions", json={})).json()["id"]
            events = sse_events(
                (
                    await client.post(
                        f"/api/sessions/{sid}/messages", json={"content": "what is this?", "images": [PNG_1PX]}
                    )
                ).text
            )
            assert [e["type"] for e in events] == ["context", "token", "image", "done"], events
            assert events[2]["url"] == PNG_1PX
            call = next(c for c in scripted.CALLS if "messages" in c)
            assert call["images"] == 1 and call["messages"][-1] == ("human", "what is this?")
            history = (await client.get(f"/api/sessions/{sid}")).json()["messages"]
            assert (
                history[0]["role"] == "human"
                and history[0]["images"] == [PNG_1PX]
                and history[0]["content"] == "what is this?"
            )
            assert (
                history[1]["role"] == "ai"
                and history[1]["images"] == [PNG_1PX]
                and history[1]["content"] == "I see it."
            )

            # Images only, no text.
            res = await client.post(f"/api/sessions/{sid}/messages", json={"content": "", "images": [PNG_1PX]})
            assert res.status_code == 200
            # Validation: not a data URL; empty message; a model without image input.
            assert (
                await client.post(f"/api/sessions/{sid}/messages", json={"content": "x", "images": ["http://x/y.png"]})
            ).status_code == 422
            assert (await client.post(f"/api/sessions/{sid}/messages", json={"content": "  "})).status_code == 422
            await client.put(f"/api/sessions/{sid}/model", json={"model": "vision:t1"})
            res = await client.post(f"/api/sessions/{sid}/messages", json={"content": "x", "images": [PNG_1PX]})
            assert res.status_code == 422 and "image input" in res.json()["detail"]


def test_context_sizes_by_part():
    schema = {"type": "function", "function": {"name": "t", "description": "d" * 400, "parameters": {"type": "object"}}}
    sizes = context_sizes([SystemMessage("s" * 400), HumanMessage("h" * 80), AIMessage("a" * 80)], [schema])
    assert sizes["system"] == 104  # 400 characters / 4, plus framing
    assert 100 < sizes["tools"] < 140 and 40 <= sizes["messages"] <= 60
    assert context_sizes([HumanMessage("hi")], []) | {"messages": 0} == {"system": 0, "tools": 0, "messages": 0}


async def test_only_the_main_request_is_measured():
    published: list[tuple[str, dict]] = []

    class Agents:
        async def publish(self, session_id, event):
            published.append((session_id, event))
            return True

    agents = Agents()
    meter = ContextMeter(types.SimpleNamespace(get=lambda key, default=None: agents if key == "agents" else default))
    sent = [[SystemMessage("s" * 40), HumanMessage("hi")]]
    # A model call outside the main agent's request (a subagent, a reviewer, a summarizer) is not measured.
    await meter.on_chat_model_start({}, sent, metadata={"thread_id": "s1"})
    assert published == []

    async def handler(request):
        await meter.on_chat_model_start({}, sent, metadata={"thread_id": "s1"})
        return "answer"

    assert await RequestScope().awrap_model_call(types.SimpleNamespace(tools=[]), handler) == "answer"
    ((session_id, event),) = published
    assert session_id == "s1" and event | {"messages": 0} == {
        "type": "context",
        "system": 14,
        "tools": 0,
        "messages": 0,
    }
    await meter.on_chat_model_start({}, sent, metadata={"thread_id": "s1"})  # the scope has ended
    assert len(published) == 1


async def test_a_turn_pauses_at_the_step_limit_and_continues(profile):
    step = lambda i: {"content": "", "tool_calls": [{"name": "shout", "args": {"text": f"n{i}"}, "id": f"c{i}"}]}  # noqa: E731
    replies = [step(0), step(1), step(2), {"content": "done"}]
    limited = scripted_patch(replies, extra=[{"id": "agents", "config": {"max_steps": 2}, "merge": True}])
    async with Harness(profile, patch=limited) as h:
        assert h.get("agentLoop").recursion_limit == 10_000  # the bound behind the step limit
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c:
            assert (await c.get("/api/agent")).json() | {"presets": 0, "modes": 0} == {
                "presets": 0,
                "modes": 0,
                "default_preset": "standard",
                "default_mode": "auto-review",
                "approval_timeout": None,
                "max_steps": 2,
                "max_parallel_tool_calls": 10,
            }
            sid = (await c.post("/api/sessions", json={"mode": "full-access"})).json()["id"]
            events = sse_events((await c.post(f"/api/sessions/{sid}/messages", json={"content": "go"})).text)
            kinds = [e["type"] for e in events]
            # Two model calls and their tools; the third call is not made.
            assert kinds == [
                "context",
                "tool_call",
                "tool_result",
                "context",
                "tool_call",
                "tool_result",
                "error",
                "done",
            ]
            error = events[-2]
            assert (error["code"], error["continuable"]) == ("STEP_LIMIT", True) and "limit of 2 steps" in error[
                "message"
            ]
            failure = (await c.get(f"/api/sessions/{sid}")).json()["failure"]
            assert (failure["code"], failure["continuable"]) == ("STEP_LIMIT", True)
            # Continuing is a new turn with its own two steps: the third tool call, then the answer.
            resumed = sse_events((await c.post(f"/api/sessions/{sid}/retry")).text)
            assert [e["type"] for e in resumed] == ["context", "tool_call", "tool_result", "context", "token", "done"]
            assert (
                resumed[-1]["outcome"] == "completed"
                and (await c.get(f"/api/sessions/{sid}")).json()["failure"] is None
            )
            # The limit is a setting: null removes it; a value below 1 is refused.
            assert (await c.put("/api/settings/agent", json={"max_steps": None})).json()["max_steps"] is None
            assert h.get("agents").config.max_steps is None
            assert (await c.put("/api/settings/agent", json={"max_steps": 0})).status_code == 422
            saved = yaml_of(profile)
            assert saved["agents"] == {"max_steps": None}


async def test_tool_calls_of_a_step_run_within_the_parallel_limit(profile):
    burst = {"content": "", "tool_calls": [{"name": "slow", "args": {"seconds": 0.3}, "id": f"s{i}"} for i in range(4)]}
    replies = [burst, {"content": "one at a time"}, burst, {"content": "together"}]
    async with (
        Harness(profile, patch=scripted_patch(replies)) as h,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c,
    ):
        sid = (await c.post("/api/sessions", json={"mode": "full-access"})).json()["id"]
        limited = (await c.put("/api/settings/agent", json={"max_parallel_tool_calls": 1})).json()
        assert limited["max_parallel_tool_calls"] == 1
        started = time.monotonic()
        await c.post(f"/api/sessions/{sid}/messages", json={"content": "four slow calls"})
        serial = time.monotonic() - started
        await c.put("/api/settings/agent", json={"max_parallel_tool_calls": 4})
        started = time.monotonic()
        await c.post(f"/api/sessions/{sid}/messages", json={"content": "again"})
        together = time.monotonic() - started
        assert serial >= 1.2 > together  # four calls of 0.3 s: in turn, then at once
        assert (await c.put("/api/settings/agent", json={"max_parallel_tool_calls": 0})).status_code == 422
        assert yaml_of(profile)["agent-loop"] == {"max_parallel_tool_calls": 4}
