"""
Model routes: configuration model, credential store, settings API, per-session selection; live endpoint when
configured.
"""

from __future__ import annotations

import json
import os
import stat

import httpx
import pytest
import yaml

from pyharness import CredentialStore, Harness, Profile
from pyharness.credentials import reference_for
from pyharness_llm import (
    LLMConfig,
    LLMConfigError,
    ProviderConfig,
    mask_secret,
    split_spec,
    translate_options,
    type_info,
)
from testkit import scripted


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def base_patch(llm: dict | None = None, replies=None):
    return [
        {
            "id": "scripted",
            "name": "testkit.scripted",
            "after": "llm",
            "config": {"replies": replies or [{"content": "hi"}]},
        },
        {"id": "llm", "config": {"default": "scripted:test", **(llm or {})}},
        {"id": "http", "config": {"serve": False}},
    ]


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120)


def sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


# ---------------------------------------------------------------------- units
def test_helpers():
    assert split_spec("local:openai-codex:gpt-6.1-sol") == ("local", "openai-codex:gpt-6.1-sol")
    assert split_spec("gpt-4o") == ("", "gpt-4o")
    assert mask_secret("cs-sk-3078205a-1234") == "••••••••1234"
    assert mask_secret(None) is None
    assert translate_options("deepseek", {"base_url": "u", "api_key": None, "temperature": 0}) == {
        "base_url": "u",
        "temperature": 0,
    }
    assert translate_options("google_genai", {"api_key": "k"}) == {"google_api_key": "k"}
    assert translate_options("openai", {"base_url": "http://127.0.0.1:1/v1"}) == {
        "base_url": "http://127.0.0.1:1/v1",
        "use_responses_api": False,
    }
    assert "use_responses_api" not in translate_options("openai", {"api_key": "k"})
    assert reference_for("openai-codex") == "OPENAI_CODEX_API_KEY"
    assert reference_for("1x") == "P_1X_API_KEY"
    openai = type_info("openai")
    assert openai["installed"] and openai["env"] == "OPENAI_API_KEY" and openai["models_api"] == "openai"
    assert (
        type_info("deepseek")["installed"]
        and type_info("openrouter")["installed"]
        and type_info("google_genai")["installed"]
    )
    assert type_info("ollama")["credentials"] is False and type_info("ollama")["preset"] is False
    assert type_info("nonexistent")["package"] is None


def test_config_model():
    cfg = LLMConfig.model_validate(
        {"default": "a:b", "providers": {"openai": {"base_url": "u", "api_key": "k", "temperature": 0}}}
    )
    assert cfg.providers["openai"].kwargs() == {"temperature": 0}  # legacy extra keys are keyword arguments
    with pytest.raises(ValueError):
        LLMConfig.model_validate({"providers": {"Bad Id": {}}})
    with pytest.raises(ValueError):
        ProviderConfig.model_validate({"protocol": "grpc"})
    custom = ProviderConfig.model_validate(
        {"protocol": "openai-responses", "base_url": "http://x/v1", "models": [{"id": "m", "max_tokens": 10}]}
    )
    assert custom.models[0].max_tokens == 10 and custom.models[0].input == ["text"]
    vision = ProviderConfig.model_validate({"models": [{"id": "v", "input": ["image", "text"]}]})
    assert vision.models[0].input == ["text", "image"]
    with pytest.raises(ValueError):
        ProviderConfig.model_validate({"models": [{"id": "v", "input": []}]})


def test_credential_store(tmp_path, monkeypatch):
    store = CredentialStore(tmp_path / "credentials.yaml")
    assert store.get("X_API_KEY") is None and store.describe("X_API_KEY") == {
        "reference": "X_API_KEY",
        "configured": False,
        "source": None,
    }
    store.set("X_API_KEY", "secret-1")
    assert store.get("X_API_KEY") == "secret-1" and store.describe("X_API_KEY")["source"] == "store"
    assert stat.S_IMODE((tmp_path / "credentials.yaml").stat().st_mode) == 0o600
    monkeypatch.setenv("X_API_KEY", "from-env")
    assert store.get("X_API_KEY") == "from-env" and store.describe("X_API_KEY")["source"] == "env"
    monkeypatch.delenv("X_API_KEY")
    assert store.delete("X_API_KEY") is True and store.delete("X_API_KEY") is False
    with pytest.raises(ValueError):
        store.set("lower", "x")
    with pytest.raises(ValueError):
        store.set("Y_API_KEY", "has space")


# ---------------------------------------------------------------------- API
async def test_route_lifecycle_through_the_api(profile):
    replies = [{"content": "one"}, {"content": "two"}]
    scripted.CALLS.clear()
    async with Harness(profile, patch=base_patch(replies=replies)) as h, client(h) as c:
        d = (await c.get("/api/settings/models")).json()
        assert d["default"] == "scripted:test" and d["routes"] == [] and d["editable"] is True
        assert [
            c_["id"] for c_ in d["catalog"] if c_["id"] != "subscription"
        ] == [  # the toolkit registers `subscription`
            "openai",
            "anthropic",
            "deepseek",
            "google_genai",
            "openrouter",
            "echo",
            "scripted",
        ]
        assert all(c_["installed"] for c_ in d["catalog"])
        assert [p["id"] for p in d["protocols"]] == ["openai-chat", "openai-responses", "anthropic-messages", "gemini"]

        # Create a route on the registered test provider; the key goes to the store, not the configuration.
        r = await c.put(
            "/api/settings/models/alt",
            json={
                "type": "scripted",
                "title": "Alt",
                "api_key": "sk-alt-0001",
                "models": [{"id": "m1", "name": "Model one", "input": ["text", "image"]}, {"id": "m2"}],
            },
        )
        assert r.status_code == 200, r.text
        route = r.json()["route"]
        assert route["api_key"] == {
            "reference": "ALT_API_KEY",
            "configured": True,
            "source": "store",
            "masked": "••••••••0001",
            "required": True,
        }
        assert "sk-alt" not in r.text
        assert yaml.safe_load(profile.credentials_path.read_text())["ALT_API_KEY"] == "sk-alt-0001"
        patch = yaml.safe_load(profile.patch_path.read_text())
        llm_op = next(op for op in patch if op["id"] == "llm")
        assert llm_op["merge"] is False
        assert llm_op["config"]["providers"]["alt"] == {
            "type": "scripted",
            "title": "Alt",
            "api_key_env": "ALT_API_KEY",
            "models": [{"id": "m1", "name": "Model one", "input": ["text", "image"]}, {"id": "m2"}],
        }
        assert '"api_key":' not in json.dumps(llm_op)

        # Default model and the selector directory.
        d = (await c.put("/api/settings/models", json={"default": "alt:m1"})).json()
        assert d["default"] == "alt:m1"
        directory = (await c.get("/api/models")).json()
        assert directory == {
            "default": "alt:m1",
            "groups": [
                {
                    "id": "alt",
                    "title": "Alt",
                    "type": "scripted",
                    "models": [
                        {
                            "id": "m1",
                            "name": "Model one",
                            "spec": "alt:m1",
                            "input": ["text", "image"],
                            "context_window": None,
                        },
                        {"id": "m2", "name": "m2", "spec": "alt:m2", "input": ["text"], "context_window": None},
                    ],
                }
            ],
        }

        # Per-session selection reaches the model factory; changing it applies to the next request.
        s = (await c.post("/api/sessions", json={"model": "alt:m2"})).json()
        assert s["model"] == "alt:m2"
        events = sse((await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "go"})).text)
        assert events[-1]["outcome"] == "completed"
        assert [x["via"] for x in scripted.CALLS if "via" in x][-1] == "m2"
        assert (await c.put(f"/api/sessions/{s['id']}/model", json={"model": "alt:m1"})).json()["model"] == "alt:m1"
        await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "again"})
        assert [x["via"] for x in scripted.CALLS if "via" in x][-1] == "m1"
        assert (await c.get(f"/api/sessions/{s['id']}")).json()["model"] == "alt:m1"

        # Edit keeps the stored key; '' removes it; delete removes the route, its key, and moves the default.
        r = (await c.put("/api/settings/models/alt", json={"base_url": "http://alt.local"})).json()["route"]
        assert r["api_key"]["configured"] is True and r["base_url"] == "http://alt.local"
        r = (await c.put("/api/settings/models/alt", json={"api_key": ""})).json()["route"]
        assert r["api_key"]["configured"] is False
        assert (await c.put("/api/settings/models/Bad", json={"type": "scripted"})).status_code == 422
        assert (await c.put("/api/settings/models/nope", json={"type": "no_such_type"})).status_code == 422
        d = (await c.delete("/api/settings/models/alt")).json()
        assert d["routes"] == [] and d["default"] == "echo:echo"
        assert (await c.delete("/api/settings/models/alt")).status_code == 404
        r = (await c.post("/api/settings/models/echo/discover", json={})).json()
        assert r == {"ok": True, "supported": False, "models": []}
        r = (await c.post("/api/settings/models/echo/test", json={"model": "echo"})).json()
        assert r["ok"] is True and r["reply"].startswith("echo: Reply")

    # The saved configuration is what the next generation boots with.
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}], generation=2) as h2:
        assert h2.get("llm").default == "echo:echo" and h2.get("llm").config.providers == {}


async def test_published_routes_resolve_but_are_not_configuration(profile):
    """A plugin's published routes: usable and selectable, absent from the settings routes and from the saved file."""
    scripted.CALLS.clear()
    async with Harness(profile, patch=base_patch()) as h, client(h) as c:
        llm = h.get("llm")
        dispose = llm.publish({"pub": {"type": "scripted", "title": "Published", "models": [{"id": "p1"}]}})
        assert llm.published() == {"pub": "<host>"} and "pub" in llm.routes() and "pub" not in llm.config.providers
        assert llm.resolve("pub:p1").model_name == "p1" and llm.context_window("pub:p1") is None
        assert any(g["id"] == "pub" for g in llm.directory()["groups"])

        d = (await c.get("/api/settings/models")).json()
        assert [r["id"] for r in d["routes"]] == []  # not a settings route
        assert any(g["id"] == "pub" and g["models"][0]["spec"] == "pub:p1" for g in d["groups"])  # still selectable
        r = await c.put("/api/settings/models/pub", json={"type": "scripted", "models": [{"id": "x"}]})
        assert r.status_code == 409 and "published" in r.json()["detail"]
        assert (await c.delete("/api/settings/models/pub")).status_code == 404

        # A published model is a valid default; saving another route keeps it and does not write the published one.
        d = (await c.put("/api/settings/models", json={"default": "pub:p1"})).json()
        assert d["default"] == "pub:p1"
        d = (await c.put("/api/settings/models/alt", json={"type": "scripted", "models": [{"id": "m1"}]})).json()
        assert d["default"] == "pub:p1" and [r["id"] for r in d["routes"]] == ["alt"]
        saved = next(e for e in yaml.safe_load(profile.patch_path.read_text()) if e["id"] == "llm")["config"]
        assert list(saved["providers"]) == ["alt"] and saved["default"] == "pub:p1"

        # A published route takes the place of a configured one of the same id; publishing again replaces the set.
        llm.update(providers={"pub": {"type": "echo"}, "alt": {"type": "scripted", "models": [{"id": "m1"}]}})
        assert llm.route("pub").type == "scripted" and [r["id"] for r in llm.describe()["routes"]] == ["alt"]
        llm.publish({"other": {"type": "scripted", "models": [{"id": "o1"}]}})
        assert llm.published() == {"other": "<host>"} and llm.route("pub").type == "echo"
        dispose()
        assert llm.published() == {} and "other" not in llm.routes()


async def test_plain_key_in_the_configuration_moves_to_the_store_on_save(profile, monkeypatch):
    monkeypatch.delenv("ALT_API_KEY", raising=False)
    patch = base_patch({"providers": {"alt": {"type": "scripted", "api_key": "plain-9999", "models": [{"id": "m1"}]}}})
    async with Harness(profile, patch=patch) as h, client(h) as c:
        route = next(r for r in (await c.get("/api/settings/models")).json()["routes"] if r["id"] == "alt")
        assert route["api_key"]["source"] == "config" and route["api_key"]["masked"] == "••••••••9999"
        r = (await c.put("/api/settings/models/alt", json={"title": "Alt"})).json()["route"]
        assert r["api_key"] == {
            "reference": "ALT_API_KEY",
            "configured": True,
            "source": "store",
            "masked": "••••••••9999",
            "required": True,
        }
        assert h.get("llm").options_for("alt")["api_key"] == "plain-9999"
    assert "plain-9999" not in profile.patch_path.read_text()
    assert yaml.safe_load(profile.credentials_path.read_text()) == {"ALT_API_KEY": "plain-9999"}


async def test_unusable_default_model_boots_and_reports_in_the_session(profile, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    patch = base_patch({"default": "openai:gpt-test"})
    async with Harness(profile, patch=patch) as h:
        agents = h.get("agents")
        session = await agents.create_session()
        events = await agents.start_run(session["id"], "hello").wait()
        error = next(e for e in events if e["type"] == "error")
        assert "LLMConfigError" in error["message"] and "openai:gpt-test" in error["message"]
        async with client(h) as c:
            assert (await c.get("/api/settings/models")).status_code == 200
            # A session can still run on another route.
            s = (await c.post("/api/sessions", json={"model": "scripted:test"})).json()
            events = sse((await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "go"})).text)
            assert events[-1]["outcome"] == "completed"
    # Preflight stays strict: the configuration is rejected before a restart.
    harness = Harness(profile, patch=patch, preflight=True)
    await harness.start()
    with pytest.raises(LLMConfigError):
        await harness.ready(serve=False)
    await harness.stop()


LIVE = {k: os.environ.get(f"PYH_TEST_OPENAI_{k}") for k in ("BASE_URL", "MODEL", "API_KEY")}


@pytest.mark.skipif(not all(LIVE.values()), reason="PYH_TEST_OPENAI_BASE_URL / _MODEL / _API_KEY unset")
async def test_live_openai_compatible_service(profile, monkeypatch):
    """
    Settings flow against a real OpenAI-compatible endpoint: discover, test, save, run with the model selected per
    session.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = {"type": "openai", "base_url": LIVE["BASE_URL"], "api_key": LIVE["API_KEY"]}
    async with Harness(profile, patch=base_patch()) as h, client(h) as c:
        found = (await c.post("/api/settings/models/local/discover", json=body)).json()
        assert found["ok"] is True and any(m["id"] == LIVE["MODEL"] for m in found["models"]), found
        probe = (await c.post("/api/settings/models/local/test", json={**body, "model": LIVE["MODEL"]})).json()
        assert probe["ok"] is True and probe["reply"], probe
        bad = (
            await c.post(
                "/api/settings/models/local/test", json={**body, "api_key": "wrong-key", "model": LIVE["MODEL"]}
            )
        ).json()
        assert bad["ok"] is False
        saved = (
            await c.put(
                "/api/settings/models/local", json={**body, "title": "Local", "models": [{"id": LIVE["MODEL"]}]}
            )
        ).json()
        assert saved["route"]["api_key"]["source"] == "store" and saved["default"] == f"local:{LIVE['MODEL']}"
        # No restart: a session on the new route answers at once.
        s = (await c.post("/api/sessions", json={"model": f"local:{LIVE['MODEL']}"})).json()
        res = await c.post(
            f"/api/sessions/{s['id']}/messages",
            json={"content": "Reply with exactly the word PONG and nothing else."},
        )
        events = sse(res.text)
        assert events[-1]["outcome"] == "completed", events
        assert "PONG" in "".join(e["text"] for e in events if e["type"] == "token").upper()
    assert LIVE["API_KEY"] not in profile.patch_path.read_text()
