"""No HTTP client reads the proxy settings of the environment or of the system."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_mcp import ServerConfig, connection_of, http_client
from pyxis_harness_otel.config import Config as OtelConfig
from pyxis_harness_otel.pipeline import Pipeline
from pyxis_harness_s3.engine import make_client

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = {"AsyncClient", "Client", "stream", "request", "get", "post", "put", "patch", "delete", "head", "options"}


@pytest.fixture
def proxied(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")


def test_every_httpx_client_in_the_packages_sets_trust_env_false():
    open_clients = []
    for path in sorted((ROOT / "packages").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx"):
                continue
            if node.func.attr not in CLIENTS:
                continue
            off = [k for k in node.keywords if k.arg == "trust_env" and getattr(k.value, "value", None) is False]
            if not off:
                open_clients.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not open_clients, "httpx clients without trust_env=False: " + ", ".join(open_clients)


async def test_model_providers_get_clients_that_ignore_the_environment(home, proxied):
    routes = {
        "oa": {"type": "openai", "api_key": "k", "models": [{"id": "gpt-x"}]},
        "ds": {"type": "deepseek", "api_key": "k", "models": [{"id": "deepseek-chat"}]},
        "an": {"type": "anthropic", "api_key": "k", "models": [{"id": "claude-x"}]},
        "gg": {"type": "google_genai", "api_key": "k", "models": [{"id": "gemini-x"}]},
        "orr": {"type": "openrouter", "api_key": "k", "models": [{"id": "x/y"}]},
        "own": {"type": "openai", "api_key": "k", "openai_proxy": "http://127.0.0.1:9", "models": [{"id": "gpt-x"}]},
    }
    patch = [
        {"id": "llm", "config": {"default": "echo:echo", "providers": routes}},
        {"id": "http", "config": {"serve": False}},
    ]
    async with Harness(Profile.init("web", home=str(home)), patch=patch) as h:
        llm = h.get("llm")
        for route, model in (("oa", "gpt-x"), ("ds", "deepseek-chat")):
            built = llm.resolve(f"{route}:{model}")
            assert built.root_client._client.trust_env is False, route
            assert built.root_async_client._client.trust_env is False, route
        anthropic = llm.resolve("an:claude-x")
        assert anthropic._client._client.trust_env is False and anthropic._async_client._client.trust_env is False
        assert str(anthropic._client.base_url).startswith("https://api.anthropic.com")
        google = llm.resolve("gg:gemini-x").client._api_client
        assert google._httpx_client.trust_env is False and google._async_httpx_client.trust_env is False
        openrouter = llm.resolve("orr:x/y").client.sdk_configuration
        assert openrouter.client.trust_env is False and openrouter.async_client.trust_env is False
        # A route that names its own proxy keeps the client its provider builds.
        assert llm.resolve("own:gpt-x").openai_proxy == "http://127.0.0.1:9"


async def test_mcp_connections_get_a_client_that_ignores_the_environment(proxied):
    for transport in ("streamable_http", "sse"):
        connection = connection_of(ServerConfig(url="http://127.0.0.1:1/mcp", transport=transport))
        assert connection["httpx_client_factory"] is http_client
    async with http_client(headers={"x": "1"}) as client:
        assert client.trust_env is False and client.headers["x"] == "1"
        assert client.timeout.connect == 30.0 and client.timeout.read == 300.0
    assert "httpx_client_factory" not in connection_of(ServerConfig(command="server"))


def test_telemetry_and_object_storage_ignore_the_environment(proxied):
    pipeline = Pipeline(OtelConfig(enabled=True, endpoint="http://127.0.0.1:1/v1/traces"), "")
    try:
        assert pipeline.exporter.inner._client._transport._session.trust_env is False
    finally:
        pipeline.provider.shutdown()
    client = make_client({"accessKeyId": "a", "endpoint": "http://127.0.0.1:1"}, "s")
    assert client.meta.config.proxies == {}
