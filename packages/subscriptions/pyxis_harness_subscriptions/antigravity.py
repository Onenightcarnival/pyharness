from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

from pyxis_harness import package_toml

from .antigravity_client import CliVersion, build_user_agent
from .antigravity_tools import make_tools
from .antigravity_wire import (
    DEFAULT_ORIGIN,
    FALLBACK_ORIGIN,
    FALLBACK_STATUSES,
    AntigravityTranslator,
    build_request,
    efforts_for,
)
from .common import LlmError, PermanentRefreshError, SseEvent, http_error, read_error
from .oauth import FlowSpec, LoginAttempt
from .providers import DiscoveredModel, Provider
from .responses import ResponsesChatModel
from .store import JsonFile

_CFG = package_toml(__file__)["antigravity"]
AUTHORIZE_URL: str = _CFG["AUTHORIZE_URL"]
TOKEN_URL: str = _CFG["TOKEN_URL"]
USERINFO_URL: str = _CFG["USERINFO_URL"]
SCOPE: str = _CFG["SCOPE"]
DEFAULT_CLIENT_ID: str = _CFG["DEFAULT_CLIENT_ID"]
DEFAULT_CLIENT_SECRET: str = _CFG["DEFAULT_CLIENT_SECRET"]
PROJECT_KEYS: tuple[str, ...] = tuple(_CFG["PROJECT_KEYS"])
PROJECT_LISTS: tuple[str, ...] = tuple(_CFG["PROJECT_LISTS"])
PLATFORM = {"darwin": "MACOS", "win32": "WINDOWS"}.get(sys.platform, "LINUX")


def _find_project(value: Any, depth: int = 0) -> str | None:
    if depth > 4 or not isinstance(value, dict):
        return None
    for key in PROJECT_KEYS:
        v = value.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            found = _find_project(v, depth + 1)
            if found:
                return found
    for key in PROJECT_LISTS:
        items = value.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item:
                    return item
                found = _find_project(item, depth + 1)
                if found:
                    return found
    for v in value.values():
        if isinstance(v, dict):
            found = _find_project(v, depth + 1)
            if found:
                return found
    return None


class AntigravityProvider(Provider):
    id = "antigravity"
    title = "Antigravity"
    vendor = "Google"
    default_context = 1048576

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.client_file = JsonFile(self.auth.file.path.parent / "antigravity-oauth-client.json", {})
        self.cli = CliVersion()

    # ------------------------------------------------------------------ oauth client
    def oauth_client(self) -> tuple[str, str | None]:
        cfg = self.config.get("antigravity") or {}
        if cfg.get("clientId"):
            return str(cfg["clientId"]), cfg.get("clientSecret")
        for id_var, secret_var in (
            ("ANTIGRAVITY_CLIENT_ID", "ANTIGRAVITY_CLIENT_SECRET"),
            ("NOAGY_CLIENT_ID", "NOAGY_CLIENT_SECRET"),
        ):
            if os.environ.get(id_var):
                return os.environ[id_var], os.environ.get(secret_var)
        stored = self.client_file.read()
        if stored.get("clientId"):
            return str(stored["clientId"]), stored.get("clientSecret")
        return DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET

    def origins(self) -> list[str]:
        base = (self.config.get("antigravity") or {}).get("baseURL")
        return [str(base).rstrip("/")] if base else [DEFAULT_ORIGIN, FALLBACK_ORIGIN]

    def user_agent(self) -> str:
        """``antigravity.userAgent`` when configured, else the CLI signature with the version in use."""
        custom = (self.config.get("antigravity") or {}).get("userAgent")
        return str(custom) if custom else build_user_agent(self.cli.current)

    async def signed(self) -> None:
        """Read the stable CLI version before the first signed request; a configured User-Agent needs none."""
        if not (self.config.get("antigravity") or {}).get("userAgent"):
            await self.cli.prime(self.http)

    def headers(self, session: dict[str, Any], stream: bool = False) -> dict[str, str]:
        return {
            "authorization": f"Bearer {session['accessToken']}",
            "content-type": "application/json",
            "accept": "text/event-stream" if stream else "application/json",
            "user-agent": self.user_agent(),
            "x-goog-api-client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
            "client-metadata": json.dumps({"ideType": "ANTIGRAVITY", "platform": PLATFORM, "pluginType": "GEMINI"}),
        }

    async def call(
        self,
        session: dict[str, Any],
        method: str,
        body: dict[str, Any],
        *,
        tolerate_404: bool = False,
        single_origin: bool = False,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """``POST {origin}/v1internal:{method}`` with the origin fallback rule."""
        await self.signed()
        last: Exception | None = None
        for origin in self.origins()[: 1 if single_origin else None]:
            try:
                res = await self.http.post(
                    f"{origin}/v1internal:{method}", headers=self.headers(session), json=body, timeout=timeout
                )
            except httpx.HTTPError as exc:
                last = exc
                continue
            if res.status_code == 404 and tolerate_404:
                return {}
            if res.status_code in FALLBACK_STATUSES and not (
                res.status_code == 429 and "Individual quota reached" in res.text
            ):
                last = http_error(f"antigravity {method}", res.status_code, res.text)
                continue
            if res.status_code >= 400:
                raise http_error(f"antigravity {method}", res.status_code, res.text)
            return res.json() if res.content else {}
        raise last or LlmError("TRANSPORT", f"antigravity {method}: no origin reachable")

    # ------------------------------------------------------------------ login
    def flow_spec(self, account: str | None = None) -> FlowSpec:
        client_id, _ = self.oauth_client()
        return FlowSpec(
            provider=self.id,
            authorize_url=AUTHORIZE_URL,
            host="localhost",
            ports=(51121,),
            callback_path="/oauth-callback",
            manual_redirect_uri="http://localhost:51121/oauth-callback",
            timeout=300.0,
            scope=SCOPE,
            client_id=client_id,
            extra_params={"access_type": "offline", "include_granted_scopes": "true", "prompt": "consent"},
        )  # fmt: skip

    async def exchange(self, attempt: LoginAttempt, code: str, query: dict[str, str]) -> tuple[str, dict[str, Any]]:
        client_id, client_secret = self.oauth_client()
        self.client_file.write({"clientId": client_id, **({"clientSecret": client_secret} if client_secret else {})})
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": attempt.redirect_uri,
            "client_id": client_id,
            "code_verifier": attempt.verifier,
        }
        if client_secret:
            form["client_secret"] = client_secret
        res = await self.http.post(TOKEN_URL, data=form, timeout=10)
        if res.status_code >= 400:
            raise RuntimeError(f"Google token exchange failed (HTTP {res.status_code}): {res.text[:300]}")
        data = res.json()
        session: dict[str, Any] = {
            "accessToken": data["access_token"],
            "refreshToken": data.get("refresh_token"),
            "expiresAt": int(time.time() * 1000) + int(data.get("expires_in") or 3600) * 1000,
            "scopes": data.get("scope"),
        }
        info = await self.call(
            session,
            "loadCodeAssist",
            {"metadata": {"ideType": "ANTIGRAVITY", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}},
            tolerate_404=True,
        )
        project = (self.config.get("antigravity") or {}).get("projectId") or _find_project(info)
        if not project:
            listed = await self.call(session, "listCloudAICompanionProjects", {}, tolerate_404=True)
            project = _find_project(listed)
        if not project and (self.config.get("antigravity") or {}).get("onboard"):
            tier = next(
                (t.get("id") for t in info.get("allowedTiers") or [] if isinstance(t, dict) and t.get("isDefault")),
                "LEGACY",
            )
            for _ in range(10):
                op = await self.call(
                    session,
                    "onboardUser",
                    {
                        "tierId": tier,
                        "metadata": {
                            "ideType": "ANTIGRAVITY",
                            "platform": "PLATFORM_UNSPECIFIED",
                            "pluginType": "GEMINI",
                        },
                    },
                    single_origin=True,
                )
                if op.get("done"):
                    project = _find_project(op.get("response") or {})
                    break
                await asyncio.sleep(1)
        email = user_id = None
        try:
            who = await self.http.get(
                USERINFO_URL, headers={"authorization": f"Bearer {session['accessToken']}"}, timeout=10
            )
            if who.status_code == 200:
                email, user_id = who.json().get("email"), who.json().get("id")
        except httpx.HTTPError:
            pass
        if not project:
            digest = bytearray(hashlib.sha1(f"antigravity:{email or user_id or uuid.uuid4()}".encode()).digest()[:16])
            digest[6] = (digest[6] & 0x0F) | 0x50
            digest[8] = (digest[8] & 0x3F) | 0x80
            project = str(uuid.UUID(bytes=bytes(digest)))
        paid = info.get("paidTier") or {}
        current = info.get("currentTier") or {}
        session.update(
            {
                "projectId": project,
                "account": email,
                "plan": paid.get("name") or paid.get("id") or current.get("name") or current.get("id"),
            }
        )
        key = str(email).lower() if email else str(project)
        return key, session

    async def refresh(self, session: dict[str, Any]) -> dict[str, Any]:
        client_id, client_secret = self.oauth_client()
        form = {"grant_type": "refresh_token", "refresh_token": session.get("refreshToken"), "client_id": client_id}
        if client_secret:
            form["client_secret"] = client_secret
        res = await self.http.post(TOKEN_URL, data=form, timeout=10)
        if res.status_code in (401, 403) or (res.status_code == 400 and "invalid_grant" in res.text):
            raise PermanentRefreshError(res.text[:200])
        if res.status_code >= 400:
            raise RuntimeError(f"Google refresh failed (HTTP {res.status_code})")
        data = res.json()
        return {
            **session,
            "accessToken": data["access_token"],
            "expiresAt": int(time.time() * 1000) + int(data.get("expires_in") or 3600) * 1000,
        }

    def plan(self, session: dict[str, Any]) -> str | None:
        return session.get("plan")

    # ------------------------------------------------------------------ catalog
    async def discover(self, session: dict[str, Any]) -> list[DiscoveredModel]:
        project = (self.config.get("antigravity") or {}).get("projectId") or session.get("projectId")
        merged: dict[str, Any] = {}
        origins = self.origins()
        await self.signed()

        async def one(origin: str) -> dict[str, Any]:
            res = await self.http.post(
                f"{origin}/v1internal:fetchAvailableModels",
                headers=self.headers(session),
                json={"project": project},
                timeout=self.discovery_timeout,
            )
            if res.status_code == 401:
                res.raise_for_status()
            return res.json().get("models") or {} if res.status_code < 400 else {}

        for result in await asyncio.gather(*(one(o) for o in origins), return_exceptions=True):
            if isinstance(result, httpx.HTTPStatusError):
                raise result
            if isinstance(result, dict):
                merged.update(result)
        out = []
        max_cfg = (self.config.get("antigravity") or {}).get("maxTokens")
        for mid, m in merged.items():
            if not isinstance(m, dict) or m.get("isInternal") or mid.startswith(("chat_", "tab_")):
                continue
            lower = mid.lower()
            context = (
                m.get("inputTokenLimit")
                or m.get("maxInputTokens")
                or (
                    200000
                    if lower.startswith("claude-")
                    else 131072
                    if lower.startswith("gpt-oss-") or "-image" in lower
                    else 1048576
                )
            )
            modalities = (
                ["text"] if m.get("supportsImages") is False or lower.startswith("gpt-oss-") else ["text", "image"]
            )
            max_out = m.get("maxOutputTokens")
            default_max = min(int(max_cfg or max_out or 32768), int(max_out)) if max_out else int(max_cfg or 32768)
            efforts = [{"id": e, "name": e.capitalize()} for e in efforts_for(mid)]
            out.append(
                DiscoveredModel(
                    id=mid,
                    name=str(m.get("displayName") or " ".join(p.capitalize() for p in mid.split("-"))),
                    description=m.get("description"),
                    context_window=int(context),
                    max_output_tokens=default_max,
                    efforts=efforts,
                    default_effort=efforts[-1]["id"] if efforts else None,
                    input_modalities=modalities,
                )
            )
        return out

    # ------------------------------------------------------------------ usage
    async def usage(self, session: dict[str, Any]) -> dict[str, Any]:
        info_task = self.call(
            session,
            "loadCodeAssist",
            {"metadata": {"ideType": "ANTIGRAVITY", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}},
            tolerate_404=True,
        )
        quota_task = self.call(session, "retrieveUserQuotaSummary", {}, tolerate_404=True)
        info, quota = await asyncio.gather(info_task, quota_task, return_exceptions=True)
        windows = []
        if isinstance(quota, dict):
            for group in quota.get("groups") or []:
                for bucket in group.get("buckets") or []:
                    text = f"{bucket.get('displayName', '')} {bucket.get('window', '')} {bucket.get('bucketId', '')}"
                    kind = (
                        "weekly"
                        if re.search(r"week|7.day|604800", text, re.IGNORECASE)
                        else "session"
                        if re.search(r"5.hour|5h|18000|session", text, re.IGNORECASE)
                        else "other"
                    )
                    resets = None
                    if bucket.get("resetTime"):
                        try:
                            resets = int(datetime.fromisoformat(str(bucket["resetTime"])).timestamp() * 1000)
                        except ValueError:
                            resets = None
                    windows.append(
                        {
                            "kind": kind,
                            "scope": (
                                f"{group.get('displayName', '')} · "
                                f"{bucket.get('displayName') or bucket.get('bucketId', '')}"
                            ),
                            "usedPercent": round((1 - float(bucket.get("remainingFraction") or 0)) * 100, 1),
                            "resetsAt": resets,
                        }
                    )
        plan = session.get("plan")
        if isinstance(info, dict):
            paid = info.get("paidTier") or {}
            current = info.get("currentTier") or {}
            plan = paid.get("name") or paid.get("id") or current.get("name") or current.get("id") or plan
            credit_amount = (
                (info.get("availableCredits") or [{}])[0].get("creditAmount")
                if isinstance(info.get("availableCredits"), list) and info["availableCredits"]
                else None
            )
            if credit_amount is not None:
                plan = f"{plan} · {credit_amount} credits"
        return {"supported": True, "plan": plan, "windows": windows}

    # ------------------------------------------------------------------ chat
    def chat_model(self, model: str, account: str | None, **options: Any) -> Any:
        return AntigravityChatModel(
            model_name=model,
            provider_ref=self,
            account_key=account,
            reasoning_effort=options.get("reasoning_effort"),
            max_tokens=options.get("max_tokens"),
            temperature=options.get("temperature"),
            stream_idle_timeout=self.stream_idle_timeout,
        )

    def tools(self, service: Any) -> list[Any]:
        return make_tools(self, service)


class AntigravityChatModel(ResponsesChatModel):
    label: str = "antigravity"
    temperature: float | None = None

    def _chunks(self, translator: Any, event: SseEvent) -> Iterable[AIMessageChunk]:
        return translator.feed(event.data)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        provider: AntigravityProvider = self.provider_ref
        manager = provider.token_manager(self.account_key)
        session = await manager.session()
        await provider.signed()
        session_id = self._session_id(kwargs)
        for attempt in (1, 2):
            project = (provider.config.get("antigravity") or {}).get("projectId") or session.get("projectId")
            body = build_request(
                project=str(project),
                model=self.model_name,
                session_id=session_id or str(uuid.uuid4()),
                messages=messages,
                tools=self.bound_tools,
                max_tokens=self.max_tokens,
                effort=self.reasoning_effort,
                temperature=self.temperature,
            )
            last: Exception | None = None
            done = False
            for origin in provider.origins():
                translator = AntigravityTranslator(self.label, self.model_name)
                try:
                    async with provider.http.stream(
                        "POST",
                        f"{origin}/v1internal:streamGenerateContent",
                        params={"alt": "sse"},
                        headers=provider.headers(session, stream=True),
                        json=body,
                        timeout=httpx.Timeout(60.0, read=self.stream_idle_timeout),
                    ) as res:
                        if res.status_code == 401 and attempt == 1:
                            session = await manager.session(force=True)
                            provider.catalogs.clear(provider.id)
                            break
                        if res.status_code in FALLBACK_STATUSES and not (
                            res.status_code == 429 and "Individual quota reached" in (await read_error(res))
                        ):
                            last = http_error(self.label, res.status_code, "")
                            continue
                        if res.status_code >= 400:
                            raise http_error(self.label, res.status_code, await read_error(res))
                        async for gen in self._generations(res, translator, run_manager):
                            yield gen
                        done = True
                        if not translator.finished:
                            raise LlmError("STREAM_CLOSED", f"{self.label} stream ended before completion")
                        return
                except httpx.HTTPError as exc:
                    last = LlmError("TRANSPORT", f"{self.label}: {exc}")
                    continue
            if done:
                return
            if attempt == 2 or last is None:
                raise last or LlmError("TRANSPORT", f"{self.label}: no origin reachable")
            if not isinstance(last, LlmError) or last.code != "AUTH":
                raise last
