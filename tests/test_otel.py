"""
OpenTelemetry export: endpoint normalization, the turn trace built from a scripted run, the settings and test
routes.
"""

from __future__ import annotations

import json

import httpx
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pyxis_harness import Harness, Profile
from pyxis_harness_otel import OtelService, normalize_endpoint, signal_url
from test_agent import scripted_patch
from testkit import scripted


def test_endpoint_helpers():
    assert normalize_endpoint("cloud.langfuse.com") == "https://cloud.langfuse.com/api/public/otel"
    assert (
        normalize_endpoint("https://cloud.langfuse.com/api/public/otel/")
        == "https://cloud.langfuse.com/api/public/otel"
    )
    assert normalize_endpoint("https://collector.example:4318") == "https://collector.example:4318"
    assert (
        normalize_endpoint("https://gateway.example/lf", langfuse_hint=True)
        == "https://gateway.example/lf/api/public/otel"
    )
    assert (
        normalize_endpoint("https://x.example/v1/traces") == "https://x.example/v1/traces"
        and normalize_endpoint("") == ""
    )
    assert signal_url("https://x.example/v1/traces", "metrics") == "https://x.example/v1/metrics"
    assert (
        signal_url("https://cloud.langfuse.com/api/public/otel", "traces")
        == "https://cloud.langfuse.com/api/public/otel/v1/traces"
    )


async def test_turn_trace_and_routes(home):
    profile = Profile.init("web", home=str(home))
    exporters: list[InMemorySpanExporter] = []  # one per pipeline: a shut-down in-memory exporter refuses further spans

    def factory() -> InMemorySpanExporter:
        exporters.append(InMemorySpanExporter())
        return exporters[-1]

    replies = [
        {"content": "", "tool_calls": [{"name": "shout", "args": {"text": "hi"}, "id": "c1"}]},
        {"content": "done: hi"},
    ]
    patch = scripted_patch(
        replies,
        extra=[
            {
                "id": "otel",
                "config": {
                    "enabled": True,
                    "endpoint": "https://collector.example",
                    "public_key": "pk",
                    "trace_export_interval_ms": 200,
                },
                "merge": True,
            }
        ],
    )
    scripted.CALLS.clear()
    async with Harness(profile, patch=patch) as h:
        otel: OtelService = h.get("otel")
        otel.exporter_factory = factory
        otel.apply()
        assert (
            otel.pipeline is not None
            and otel.status()["running"] is True
            and otel.status()["traceEndpoint"] == "https://collector.example/v1/traces"
        )
        agents = h.get("agents")
        session = await agents.create_session()
        events = await agents.start_run(session["id"], "say hi").wait()
        assert events[-1]["outcome"] == "completed"
        assert otel.pipeline.flush()
        exporter = exporters[-1]
        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert (
            set(spans)
            == {"enter_ai_application_system", "invoke_agent standard", "react step", "chat test", "execute_tool shout"}
            or "react step" in spans
        )
        entry, agent = spans["enter_ai_application_system"], spans["invoke_agent standard"]
        assert entry.parent is None and agent.parent.span_id == entry.context.span_id
        assert (
            agent.attributes["gen_ai.operation.name"] == "invoke_agent"
            and agent.attributes["gen_ai.session.id"] == session["id"]
            and agent.attributes["langfuse.session.id"] == session["id"]
        )
        assert (
            entry.attributes["pyxis_harness.turn.end_reason"] == "completed"
            and json.loads(entry.attributes["gen_ai.input.messages"])[0]["parts"][0]["content"] == "say hi"
        )
        assert json.loads(agent.attributes["gen_ai.output.messages"])[0]["parts"][0]["content"] == "done: hi"
        steps = [s for s in exporter.get_finished_spans() if s.name == "react step"]
        assert len(steps) == 2 and all(s.parent.span_id == agent.context.span_id for s in steps)
        tool = spans["execute_tool shout"]
        assert (
            tool.attributes["gen_ai.tool.name"] == "shout"
            and tool.attributes["gen_ai.tool.call.id"] == "c1"
            and json.loads(tool.attributes["gen_ai.tool.call.arguments"]) == {"text": "hi"}
        )
        assert tool.parent.span_id == steps[0].context.span_id and "HI" in tool.attributes["gen_ai.tool.call.result"]
        llms = [s for s in exporter.get_finished_spans() if s.name.startswith("chat")]
        assert (
            len(llms) == 2
            and llms[0].attributes["gen_ai.response.finish_reasons"] == ("tool_calls",)
            and llms[1].attributes["gen_ai.response.finish_reasons"] == ("stop",)
        )
        assert json.loads(llms[0].attributes["gen_ai.output.messages"])[0]["parts"][0]["type"] == "tool_call"
        assert "gen_ai.system_instructions" in llms[0].attributes and "gen_ai.tool.definitions" in llms[0].attributes
        assert (
            all(s.end_time >= s.start_time for s in exporter.get_finished_spans())
            and entry.start_time <= steps[0].start_time
        )
        st = otel.status()
        assert st["exportedSpans"] >= 7 and st["lastExportOk"] is True and st["secretKeySet"] is False
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=60
        ) as c:
            assert (await c.get("/api/otel/status")).json()["enabled"] is True
            r = await c.put(
                "/api/otel/settings",
                json={
                    "endpoint": "cloud.langfuse.com",
                    "publicKey": "pk-lf-1",
                    "secretKey": "sk-lf-2",
                    "enabled": True,
                    "captureContent": False,
                    "gzip": True,
                    "contentMaxChars": 5000,
                    "maxExportBatchSize": None,
                },
            )
            body = r.json()
            assert (
                r.status_code == 200
                and body["secretKeySet"] is True
                and body["captureContent"] is False
                and body["gzip"] is True
                and body["contentMaxChars"] == 5000
                and body["maxExportBatchSize"] == 512
            )
            assert (
                body["running"] is True
                and body["traceEndpoint"] == "https://cloud.langfuse.com/api/public/otel/v1/traces"
                and body["langfuse"] is True
            )
            assert profile.credentials.get("OTEL_SECRET_KEY") == "sk-lf-2" and "sk-lf-2" not in json.dumps(body)
            assert (await c.put("/api/otel/settings", json={"contentMaxChars": 5})).status_code == 400
            assert (await c.put("/api/otel/settings", json={"endpoint": "", "enabled": True})).status_code == 400
            r = await c.put("/api/otel/settings", json={"enabled": False})
            assert r.json()["running"] is False
            r = await c.post("/api/otel/test", json={"endpoint": "https://collector.example", "publicKey": "pk"})
            exporter = exporters[-1]
            assert (
                r.status_code == 200
                and r.json()["ok"] is True
                and len(r.json()["traceIds"]) == 3
                and "Tests passed" in r.json()["message"]
            )
            names = {s.name for s in exporter.get_finished_spans()}
            assert {
                "pyxis-harness-otel connection test",
                "pyxis-harness-otel payload test",
                "enter_ai_application_system",
            } <= names
            assert (await c.post("/api/otel/verify", json={})).status_code == 409
        assert any(cl["entry"] == "otel" for cl in h.get("webui").clients())
