from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import BaseMessage

from pyxis_harness import package_toml

from .common import PermanentRefreshError, headers_with_ua, http_error, jwt_claims
from .grok_tools import make_tools
from .oauth import FlowSpec, LoginAttempt
from .providers import DiscoveredModel, Provider
from .responses import ResponsesChatModel, to_responses_input, to_responses_tools

_CFG = package_toml(__file__)["grok"]
CLIENT_ID: str = _CFG["CLIENT_ID"]
DISCOVERY_URL: str = _CFG["DISCOVERY_URL"]
AUTHORIZE_URL: str = _CFG["AUTHORIZE_URL"]
SCOPE: str = _CFG["SCOPE"]
API: str = _CFG["API"]
PROXY: str = _CFG["PROXY"]
TIERS: dict[int, str] = {int(t["level"]): str(t["name"]) for t in _CFG["TIERS"]}
NON_CHAT = re.compile(r"imagine|image-|video|embed", re.IGNORECASE)


def tier_name(claims: dict[str, Any]) -> str | None:
    tier = claims.get("tier")
    if tier is None:
        return None
    try:
        return TIERS.get(int(tier), str(tier))
    except (TypeError, ValueError):
        return str(tier)


class GrokProvider(Provider):
    id = "grok"
    title = "Grok"
    vendor = "xAI"
    default_context = 256000
    default_max_tokens = 32000
    preempt_ms = 2 * 60 * 1000

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._endpoints: dict[str, str] | None = None

    async def endpoints(self) -> dict[str, str]:
        if self._endpoints:
            return self._endpoints
        res = await self.http.get(DISCOVERY_URL, timeout=10)
        res.raise_for_status()
        cfg = res.json()
        out = {}
        for key in ("authorization_endpoint", "token_endpoint"):
            url = str(cfg.get(key) or "")
            host = urlparse(url).hostname or ""
            if not url.startswith("https://") or not (host == "x.ai" or host.endswith(".x.ai")):
                raise RuntimeError(f"Grok discovery returned an unexpected {key}")
            out[key] = url
        self._endpoints = out
        return out

    def flow_spec(self, account: str | None = None) -> FlowSpec:
        authorize = (self._endpoints or {}).get("authorization_endpoint") or AUTHORIZE_URL
        return FlowSpec(
            provider=self.id,
            authorize_url=authorize,
            host="127.0.0.1",
            ports=(56121,),
            callback_path="/callback",
            timeout=180.0,
            scope=SCOPE,
            client_id=CLIENT_ID,
            extra_params={"plan": "generic", "referrer": "pyxis-harness-subscriptions"},
            use_nonce=True,
        )

    async def login(self, account: str | None = None) -> dict[str, Any]:
        await self.endpoints()
        return await super().login(account)

    async def exchange(self, attempt: LoginAttempt, code: str, query: dict[str, str]) -> tuple[str, dict[str, Any]]:
        token_url = (await self.endpoints())["token_endpoint"]
        res = await self.http.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "redirect_uri": attempt.redirect_uri,
                "code_verifier": attempt.verifier,
                "code_challenge": attempt.challenge,
                "code_challenge_method": "S256",
            },
            timeout=30,
        )
        if res.status_code == 403:
            raise RuntimeError(
                "Grok token endpoint refused the exchange (HTTP 403): the X plan does not include the API OAuth "
                "entitlement; an X Premium or xAI subscription with API access is required"
            )
        if res.status_code >= 400:
            raise RuntimeError(f"Grok token exchange failed (HTTP {res.status_code}): {res.text[:300]}")
        data = res.json()
        claims = jwt_claims(data.get("id_token"))
        account_label = (
            claims.get("email") or claims.get("preferred_username") or claims.get("name") or claims.get("sub")
        )
        session = {
            "accessToken": data["access_token"],
            "refreshToken": data.get("refresh_token"),
            "expiresAt": int(time.time() * 1000) + int(data.get("expires_in") or 3600) * 1000,
            "tokenEndpoint": token_url,
            "scopes": data.get("scope"),
            "account": account_label,
        }
        key = (
            str(account_label).lower()
            if account_label
            else "token-" + hashlib.sha256(str(data.get("refresh_token")).encode()).hexdigest()[:16]
        )
        return key, session

    async def refresh(self, session: dict[str, Any]) -> dict[str, Any]:
        token_url = session.get("tokenEndpoint") or (await self.endpoints())["token_endpoint"]
        res = await self.http.post(
            token_url,
            data={"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": session.get("refreshToken")},
            timeout=30,
        )
        if res.status_code >= 400:
            if "invalid_grant" in res.text:
                raise PermanentRefreshError("invalid_grant")
            raise RuntimeError(f"Grok refresh failed (HTTP {res.status_code})")
        data = res.json()
        return {
            **session,
            "accessToken": data["access_token"],
            "refreshToken": data.get("refresh_token") or session.get("refreshToken"),
            "expiresAt": int(time.time() * 1000) + int(data.get("expires_in") or 3600) * 1000,
            "scopes": data.get("scope") or session.get("scopes"),
        }

    def plan(self, session: dict[str, Any]) -> str | None:
        return tier_name(jwt_claims(session.get("accessToken")))

    def headers(self, session: dict[str, Any], proxy: bool = False, **extra: str) -> dict[str, str]:
        base = {"authorization": f"Bearer {session['accessToken']}", "accept": "application/json", **extra}
        if proxy:
            base["x-xai-token-auth"] = "xai-grok-cli"
        return headers_with_ua(base)

    # ------------------------------------------------------------------ catalog
    async def discover(self, session: dict[str, Any]) -> list[DiscoveredModel]:
        ids_res, meta_res = await asyncio.gather(
            self.http.get(f"{API}/models", headers=self.headers(session), timeout=self.discovery_timeout),
            self.http.get(f"{PROXY}/models", headers=self.headers(session, proxy=True), timeout=self.discovery_timeout),
            return_exceptions=True,
        )
        if isinstance(ids_res, Exception):
            raise ids_res
        ids_res.raise_for_status()
        ids = [
            str(m.get("id"))
            for m in ids_res.json().get("data") or []
            if m.get("id") and not NON_CHAT.search(str(m["id"]))
        ]
        if not ids:
            raise RuntimeError("Grok returned no chat models")
        meta: dict[str, dict[str, Any]] = {}
        if not isinstance(meta_res, Exception) and meta_res.status_code < 400:
            meta = {str(m.get("id")): m for m in meta_res.json().get("data") or [] if m.get("id")}
        out = []
        for mid in ids:
            m = meta.get(mid, {})
            efforts = (
                [
                    {"id": str(e.get("value")), "name": str(e.get("label") or e.get("value"))}
                    for e in m.get("reasoning_efforts") or []
                    if e.get("value")
                ]
                if m.get("supports_reasoning_effort")
                else []
            )
            out.append(
                DiscoveredModel(
                    id=mid,
                    name=str(m.get("name") or mid),
                    description=m.get("description"),
                    context_window=m.get("context_window") or 256000,
                    efforts=efforts,
                    default_effort=m.get("reasoning_effort") if efforts else None,
                    input_modalities=["text"] if re.search(r"code|embed", mid, re.IGNORECASE) else ["text", "image"],
                )
            )
        return out

    def fallback_models(self) -> list[DiscoveredModel]:
        return [
            DiscoveredModel(
                id=i, name=n, context_window=256000, input_modalities=["text"] if "code" in i else ["text", "image"]
            )
            for i, n in (
                ("grok-4", "Grok 4"),
                ("grok-4-fast-reasoning", "Grok 4 Fast Reasoning"),
                ("grok-code-fast-1", "Grok Code Fast 1"),
            )
        ]

    # ------------------------------------------------------------------ usage
    async def usage(self, session: dict[str, Any]) -> dict[str, Any]:
        res = await self.http.get(
            f"{PROXY}/billing",
            params={"format": "credits"},
            headers=self.headers(session, proxy=True),
            timeout=self.discovery_timeout,
        )
        if res.status_code >= 400:
            raise http_error("grok usage", res.status_code, res.text)
        data = res.json()
        cfg = data.get("config") or {}
        windows = []
        period = cfg.get("currentPeriod") or {}
        if period or cfg.get("creditUsagePercent") is not None:
            resets = None
            if period.get("end"):
                with contextlib.suppress(ValueError):
                    resets = int(datetime.fromisoformat(str(period["end"])).timestamp() * 1000)
            windows.append(
                {
                    "kind": "weekly" if period.get("type") == "USAGE_PERIOD_TYPE_WEEKLY" else "other",
                    "usedPercent": float(cfg.get("creditUsagePercent") or 0),
                    "resetsAt": resets,
                }
            )
        elif (cfg.get("monthlyLimit") or {}).get("val"):
            used = float((cfg.get("used") or {}).get("val") or 0)
            limit = float(cfg["monthlyLimit"]["val"])
            windows.append(
                {
                    "kind": "other",
                    "usedPercent": used / limit * 100 if limit else 0,
                    "resetsAt": cfg.get("billingPeriodEnd"),
                }
            )
        return {"supported": True, "plan": data.get("subscriptionTier") or self.plan(session), "windows": windows}

    # ------------------------------------------------------------------ chat
    def chat_model(self, model: str, account: str | None, **options: Any) -> Any:
        return GrokChatModel(
            model_name=model,
            provider_ref=self,
            account_key=account,
            reasoning_effort=options.get("reasoning_effort"),
            max_tokens=options.get("max_tokens"),
            stream_idle_timeout=self.stream_idle_timeout,
        )

    def tools(self, service: Any) -> list[Any]:
        return make_tools(self, service)


class GrokChatModel(ResponsesChatModel):
    label: str = "grok"

    async def build_request(
        self, messages: list[BaseMessage], session: dict[str, Any], session_id: str | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        instructions, items = to_responses_input(messages, repair=False, shorten_ids=False)
        body: dict[str, Any] = {"model": self.model_name, "input": items, "store": False, "stream": True}
        if instructions:
            body["instructions"] = instructions
        if self.bound_tools:
            body["tools"] = to_responses_tools(self.bound_tools, strict=None)
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True
        if self.max_tokens:
            body["max_output_tokens"] = self.max_tokens
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        if session_id:
            body["prompt_cache_key"] = session_id
        provider: GrokProvider = self.provider_ref
        headers = provider.headers(session, accept="text/event-stream", **{"content-type": "application/json"})
        return f"{API}/responses", headers, body
