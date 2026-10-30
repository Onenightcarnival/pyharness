"""Model service settings: profile patch mutation, settings API, probe; live OpenAI-compatible endpoint when configured."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
from pyharness_llm import mask_secret, split_spec, translate_options

from pyharness import Harness, Profile
from pyharness.config import iter_entries


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def base_patch(extra=None):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": [{"content": "hi"}]}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        {"id": "http", "config": {"serve": False}},
        *(extra or []),
    ]


def test_helpers():
    assert split_spec("openai:openai-codex:gpt-6.1-sol") == ("openai", "openai-codex:gpt-6.1-sol")
    assert split_spec("gpt-4o") == ("", "gpt-4o")
    assert split_spec(None) == ("", "")
    assert mask_secret("cs-sk-3078205a-1234") == "••••••••1234"
    assert mask_secret("short") == "••••••••"
    assert mask_secret(None) is None
    assert translate_options("deepseek", {"base_url": "u", "api_key": None, "temperature": 0}) == {"api_base": "u", "temperature": 0}
    assert translate_options("google_genai", {"api_key": "k"}) == {"google_api_key": "k"}
    assert translate_options("openai", {"base_url": "http://127.0.0.1:1/v1"}) == {
        "base_url": "http://127.0.0.1:1/v1",
        "use_responses_api": False,
    }
    assert translate_options("openai", {"base_url": "http://x/v1", "use_responses_api": True})["use_responses_api"] is True
    assert "use_responses_api" not in translate_options("openai", {"api_key": "k"})


def test_set_entry_config_merges_into_the_profile_patch(profile):
    profile.set_entry_config("llm", {"default": "openai:a", "providers": {"openai": {"base_url": "http://x/v1"}}})
    profile.set_entry_config("llm", {"providers": {"openai": {"api_key": "k1"}}})
    ops = profile.patch_ops_raw()
    assert [op["id"] for op in ops] == ["llm"]
    assert ops[0]["merge"] is True
    assert ops[0]["config"] == {"default": "openai:a", "providers": {"openai": {"base_url": "http://x/v1", "api_key": "k1"}}}
    # Composed over the base bundle: default replaced, provider options kept.
    entry = next(e for e, _ in iter_entries(profile.compose().tree) if e.id == "llm")
    assert entry.config["default"] == "openai:a"
    assert entry.config["providers"]["openai"]["api_key"] == "k1"
    # A later disabled op on the same id is reused rather than duplicated.
    profile.set_entry_disabled("llm", False)
    profile.set_entry_config("llm", {"default": "echo:echo"})
    ops = profile.patch_ops_raw()
    assert len(ops) == 1 and ops[0]["config"]["default"] == "echo:echo" and ops[0]["disabled"] is False


async def test_settings_api_describes_masks_and_saves(profile):
    patch = base_patch(
        [{"id": "llm", "config": {"providers": {"echo": {"api_key": "secret-value-9876", "base_url": "http://echo"}}}, "merge": True}]
    )
    async with Harness(profile, patch=patch) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t", timeout=120) as client:
            d = (await client.get("/api/settings/model")).json()
            assert (d["provider"], d["model"]) == ("scripted", "test")
            assert d["providers"]["echo"] == {"base_url": "http://echo", "api_key": "••••••••9876", "has_api_key": True, "other": []}
            assert "secret-value" not in json.dumps(d)
            ids = {c["id"] for c in d["catalog"]}
            assert {"openai", "deepseek", "anthropic", "echo", "scripted"} <= ids
            assert d["registered"]["scripted"] == "scripted"
            assert d["editable"] is True and d["supervised"] is False

            # Probe: the built-in echo provider answers without credentials.
            r = (await client.post("/api/settings/model/test", json={"provider": "echo", "model": "echo"})).json()
            assert r["ok"] is True and r["reply"].startswith("echo: Reply with the single word OK.")
            # Probe: a provider whose package is missing reports the install hint instead of raising.
            r = (await client.post("/api/settings/model/test", json={"provider": "nonexistent_provider", "model": "m"})).json()
            assert r["ok"] is False and "nonexistent_provider" in r["error"]
            # Listing models: unsupported provider → supported false; unreachable endpoint → error, no exception.
            r = (await client.post("/api/settings/model/models", json={"provider": "echo", "model": "echo"})).json()
            assert r == {"ok": True, "supported": False, "models": []}
            r = (
                await client.post(
                    "/api/settings/model/models",
                    json={"provider": "openai", "model": "m", "base_url": "http://127.0.0.1:9", "api_key": "k"},
                )
            ).json()
            assert r["ok"] is False and r["models"] == []

            # Save: preflighted in a separate process; unsupervised → applies on the next start.
            r = (await client.put("/api/settings/model", json={"provider": "echo", "model": "echo", "api_key": "new-key-0001"})).json()
            assert r["application"] == "saved-restart-required", r
            assert r["preflight"]["ok"] is True
            assert r["default"] == "echo:echo"
            assert h.lifecycle.restart_pending is None
    ops = profile.patch_ops_raw()
    llm_op = next(op for op in ops if op["id"] == "llm")
    assert llm_op["config"]["default"] == "echo:echo"
    assert llm_op["config"]["providers"]["echo"] == {"base_url": None, "api_key": "new-key-0001"}

    # Next generation: the saved default is live; the inline patch no longer overrides it.
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}], generation=2) as h2:
        assert h2.get("llm").default == "echo:echo"
        d = h2.get("llm").describe()
        assert d["providers"]["echo"]["api_key"] == "••••••••0001"


async def test_settings_api_rejects_a_configuration_that_fails_preflight(profile):
    before = profile.read_state()
    async with Harness(profile, patch=base_patch()) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t", timeout=120) as client:
            r = (await client.put("/api/settings/model", json={"provider": "no_such_provider", "model": "m"})).json()
            assert r["application"] == "rejected", r
            assert r["stage"] == "preflight"
            assert any("no_such_provider" in str(e.get("error")) for e in r["errors"])
    assert profile.read_state() == before


async def test_supervised_save_schedules_a_restart(profile):
    async with Harness(profile, patch=base_patch(), supervised=True) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t", timeout=120) as client:
            r = (await client.put("/api/settings/model", json={"provider": "echo", "model": "echo"})).json()
            assert r["application"] == "restart-scheduled", r
        for _ in range(20):
            if h.lifecycle.restart_pending is not None:
                break
            await asyncio.sleep(0.1)
        assert h.lifecycle.restart_pending is not None
        assert h.lifecycle.restart_pending["reasons"] == ["model settings: echo:echo"]
        assert h.lifecycle.exit_code == 75


LIVE = {k: os.environ.get(f"PYH_TEST_OPENAI_{k}") for k in ("BASE_URL", "MODEL", "API_KEY")}


@pytest.mark.skipif(not all(LIVE.values()), reason="PYH_TEST_OPENAI_BASE_URL / _MODEL / _API_KEY unset")
async def test_live_openai_compatible_service(profile):
    """Settings page flow against a real OpenAI-compatible endpoint, then a real agent turn with it."""
    pytest.importorskip("langchain_openai")
    body = {"provider": "openai", "model": LIVE["MODEL"], "base_url": LIVE["BASE_URL"], "api_key": LIVE["API_KEY"]}
    async with Harness(profile, patch=base_patch()) as h:
        http = h.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t", timeout=180) as client:
            models = (await client.post("/api/settings/model/models", json=body)).json()
            assert models["ok"] is True and LIVE["MODEL"] in models["models"], models
            probe = (await client.post("/api/settings/model/test", json=body)).json()
            assert probe["ok"] is True and probe["reply"], probe
            bad = (await client.post("/api/settings/model/test", json={**body, "api_key": "wrong-key"})).json()
            assert bad["ok"] is False
            saved = (await client.put("/api/settings/model", json=body)).json()
            assert saved["application"] == "saved-restart-required", saved
    # Generation 2 runs the saved model: the key is not in the request body any more, it comes from the profile.
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}], generation=2) as h2:
        http = h2.get("http")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http.app), base_url="http://t", timeout=180) as client:
            health = (await client.get("/api/health")).json()
            assert health["model"] == f"openai:{LIVE['MODEL']}"
            session = (await client.post("/api/sessions", json={})).json()
            res = await client.post(
                f"/api/sessions/{session['id']}/messages", json={"content": "Reply with exactly the word PONG and nothing else."}
            )
            events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["outcome"] == "completed", events
            text = "".join(e["text"] for e in events if e["type"] == "token")
            assert "PONG" in text.upper(), text
