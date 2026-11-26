from __future__ import annotations

import os
from typing import Any

import httpx

# Options with which a route names its own proxy; such a route keeps the clients its provider builds.
PROXY_OPTIONS = ("openai_proxy", "anthropic_proxy", "http_client", "http_async_client", "client")


def client_options(kind: str, options: dict[str, Any]) -> dict[str, Any]:
    """
    Constructor options that give a provider HTTP clients with ``trust_env=False``: the proxy settings of the
    environment and of the system do not apply.

    | ``kind``                | options                                                    |
    |-------------------------|------------------------------------------------------------|
    | ``openai``, ``deepseek``| ``http_client``, ``http_async_client``: the SDK's defaults |
    | ``google_genai``        | ``client_args``: ``trust_env`` beside the route's own      |
    | other                   | none; see :func:`replace_clients`                          |
    """
    if any(options.get(name) for name in PROXY_OPTIONS):
        return {}
    if kind in ("openai", "deepseek"):
        import openai  # noqa: PLC0415 - an optional provider package

        return {
            "http_client": openai.DefaultHttpxClient(trust_env=False),
            "http_async_client": openai.DefaultAsyncHttpxClient(trust_env=False),
        }
    if kind == "google_genai":
        return {"client_args": {"trust_env": False, **(options.get("client_args") or {})}}
    return {}


def replace_clients(kind: str, model: Any, options: dict[str, Any]) -> None:
    """
    The same for providers whose constructor takes no HTTP client: the clients the model built are replaced.

    | ``kind``       | replaced                                                          |
    |----------------|-------------------------------------------------------------------|
    | ``anthropic``  | the SDK clients of the model, built on ``anthropic``'s defaults   |
    | ``openrouter`` | the HTTP clients of the SDK configuration, with the same headers  |
    """
    if any(options.get(name) for name in PROXY_OPTIONS):
        return
    if kind == "anthropic":
        import anthropic  # noqa: PLC0415 - an optional provider package

        params = dict(model._client_params)  # noqa: SLF001 - ChatAnthropic takes no HTTP client
        http: dict[str, Any] = {
            "base_url": params["base_url"] or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
        }
        if "timeout" in params:
            http["timeout"] = params["timeout"]
        model.__dict__["_client"] = anthropic.Client(
            **params, http_client=anthropic.DefaultHttpxClient(**http, trust_env=False)
        )
        model.__dict__["_async_client"] = anthropic.AsyncClient(
            **params, http_client=anthropic.DefaultAsyncHttpxClient(**http, trust_env=False)
        )
    elif kind == "openrouter":
        sdk = model.client.sdk_configuration
        sdk.client = httpx.Client(headers=sdk.client.headers, follow_redirects=True, trust_env=False)
        sdk.async_client = httpx.AsyncClient(headers=sdk.async_client.headers, follow_redirects=True, trust_env=False)
