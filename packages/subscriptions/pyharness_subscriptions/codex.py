from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.messages import BaseMessage

from pyharness import package_prompts, package_toml

from .codex_tools import make_tools
from .common import PermanentRefreshError, headers_with_ua, http_error, jwt_claims, session_uuid
from .oauth import FlowSpec, LoginAttempt
from .providers import DiscoveredModel, Provider
from .responses import ResponsesChatModel, to_responses_input, to_responses_tools

_CFG = package_toml(__file__)["codex"]
CLIENT_ID: str = _CFG["CLIENT_ID"]
AUTHORIZE_URL: str = _CFG["AUTHORIZE_URL"]
TOKEN_URL: str = _CFG["TOKEN_URL"]
SCOPE: str = _CFG["SCOPE"]
BACKEND: str = _CFG["BACKEND"]
NPM_LATEST_URL: str = _CFG["NPM_LATEST_URL"]
CLIENT_VERSION_FLOOR: str = _CFG["CLIENT_VERSION_FLOOR"]
PERMANENT: set[str] = set(_CFG["PERMANENT"])
EFFORT_NAMES: dict[str, str] = dict(_CFG["EFFORT_NAMES"])
PROMPTS = package_prompts(__file__)
DEFAULT_INSTRUCTIONS: str = PROMPTS["codex"]["DEFAULT_INSTRUCTIONS"]


def effort_name(effort: str) -> str:
    return EFFORT_NAMES.get(effort, effort.capitalize())


class CodexProvider(Provider):
    id = "codex"
    title = "Codex"
    vendor = "OpenAI"
    default_context = 400000
    default_max_tokens = 128000

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client_version: tuple[float, str, str] | None = None  # (checked_at, version, source)
        self.speed: dict[str, str] = {}  # session id -> standard | fast

    # ------------------------------------------------------------------ auth
    def flow_spec(self, account: str | None = None) -> FlowSpec:
        return FlowSpec(
            provider=self.id,
            authorize_url=AUTHORIZE_URL,
            host="localhost",
            ports=(1455, 1457),
            callback_path="/auth/callback",
            manual_redirect_uri="http://localhost:1455/auth/callback",
            timeout=180.0,
            scope=SCOPE,
            client_id=CLIENT_ID,
            extra_params={
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
                "originator": "codex_cli_rs",
            },
        )

    def _session_from(self, data: dict[str, Any], previous: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        access = data.get("access_token")
        if not access:
            raise RuntimeError("codex token response has no access_token")
        expires_in = data.get("expires_in")
        expires_at = (
            int(time.time() * 1000) + int(expires_in) * 1000
            if expires_in
            else int(jwt_claims(access).get("exp", time.time() + 3600)) * 1000
        )
        id_token = data.get("id_token") or (previous or {}).get("idToken")
        claims = jwt_claims(id_token)
        auth_claims = claims.get("https://api.openai.com/auth") or {}
        account_id = auth_claims.get("chatgpt_account_id") or (previous or {}).get("accountId")
        if not account_id:
            raise RuntimeError("codex login did not return a chatgpt account id; cannot use the subscription")
        email = (
            claims.get("email")
            or (claims.get("https://api.openai.com/profile") or {}).get("email")
            or (previous or {}).get("emailAddress")
        )
        session = {
            "accessToken": access,
            "refreshToken": data.get("refresh_token") or (previous or {}).get("refreshToken"),
            "expiresAt": expires_at,
            "accountId": account_id,
            "idToken": id_token,
            "emailAddress": email,
            "planType": auth_claims.get("chatgpt_plan_type") or (previous or {}).get("planType"),
        }
        user_id = auth_claims.get("chatgpt_user_id") or auth_claims.get("user_id")
        key = (
            json.dumps([account_id, "user", user_id])
            if user_id
            else json.dumps([account_id, "email", str(email).lower()])
            if email
            else str(account_id)
        )
        return key, session

    async def exchange(self, attempt: LoginAttempt, code: str, query: dict[str, str]) -> tuple[str, dict[str, Any]]:
        res = await self.http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": attempt.redirect_uri,
                "client_id": CLIENT_ID,
                "code_verifier": attempt.verifier,
            },
            timeout=30,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"codex token exchange failed (HTTP {res.status_code}): {res.text[:300]}")
        return self._session_from(res.json(), None)

    async def refresh(self, session: dict[str, Any]) -> dict[str, Any]:
        res = await self.http.post(
            TOKEN_URL,
            json={"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": session.get("refreshToken")},
            timeout=30,
        )
        if res.status_code >= 400:
            try:
                err = res.json()
                code = err.get("error", {}).get("code") if isinstance(err.get("error"), dict) else err.get("error")
            except ValueError:
                code = None
            if code in PERMANENT:
                raise PermanentRefreshError(str(code))
            raise RuntimeError(f"codex refresh failed (HTTP {res.status_code})")
        return self._session_from(res.json(), session)[1]

    def account_label(self, session: dict[str, Any]) -> str:
        return str(session.get("emailAddress") or session.get("accountId") or self.title)

    # ------------------------------------------------------------------ headers
    def headers(self, session: dict[str, Any], **extra: str) -> dict[str, str]:
        return headers_with_ua(
            {
                "authorization": f"Bearer {session['accessToken']}",
                "chatgpt-account-id": str(session["accountId"]),
                "originator": "codex_cli_rs",
                **extra,
            }
        )

    async def client_version(self, force: bool = False) -> tuple[str, str]:
        configured = self.config.get("codexClientVersion")
        if configured and re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$", str(configured)):
            return str(configured), "config"
        now = time.time()
        if (
            self._client_version
            and not force
            and now - self._client_version[0] < (6 * 3600 if self._client_version[2] == "npm" else 300)
        ):
            return self._client_version[1], self._client_version[2]
        version, source = CLIENT_VERSION_FLOOR, "fallback"
        try:
            res = await self.http.get(NPM_LATEST_URL, timeout=5)
            found = str(res.json().get("version") or "")
            if (
                res.status_code == 200
                and re.match(r"^\d+\.\d+\.\d+$", found)
                and _ver(found) >= _ver(CLIENT_VERSION_FLOOR)
            ):
                version, source = found, "npm"
        except Exception:  # noqa: BLE001
            pass
        self._client_version = (now, version, source)
        return version, source

    # ------------------------------------------------------------------ catalog
    async def discover(self, session: dict[str, Any]) -> list[DiscoveredModel]:
        version, _ = await self.client_version()
        res = await self.http.get(
            f"{BACKEND}/codex/models",
            params={"client_version": version},
            headers=self.headers(session, accept="application/json"),
            timeout=self.discovery_timeout,
        )
        res.raise_for_status()
        out = []
        for m in res.json().get("models") or []:
            if m.get("visibility") in ("hide", "none"):
                continue
            efforts = [
                {"id": lvl.get("effort"), "name": effort_name(str(lvl.get("effort")))}
                for lvl in m.get("supported_reasoning_levels") or []
                if lvl.get("effort")
            ]
            tiers = {t.get("id") for t in m.get("service_tiers") or [] if isinstance(t, dict)}
            fast = "priority" in tiers or "fast" in (m.get("additional_speed_tiers") or [])
            out.append(
                DiscoveredModel(
                    id=str(m["slug"]),
                    name=str(m.get("display_name") or m["slug"]),
                    description=m.get("description"),
                    context_window=m.get("context_window"),
                    max_context_window=m.get("max_context_window"),
                    priority=m.get("priority"),
                    efforts=efforts,
                    default_effort=m.get("default_reasoning_level"),
                    input_modalities=["text", "image"],
                    fast_tier=fast,
                )  # fmt: skip
            )
        out.sort(key=lambda m: (m.priority is None, m.priority or 0))
        return out

    def fallback_models(self) -> list[DiscoveredModel]:
        efforts = [{"id": e, "name": effort_name(e)} for e in ("minimal", "low", "medium", "high", "xhigh")]
        return [
            DiscoveredModel(
                id=i,
                name=n,
                context_window=400000,
                efforts=efforts,
                default_effort="high",
                input_modalities=["text", "image"],
            )
            for i, n in (
                ("gpt-5.1-codex", "GPT-5.1 Codex"),
                ("gpt-5.1-codex-mini", "GPT-5.1 Codex Mini"),
                ("gpt-5.1", "GPT-5.1"),
            )
        ]

    # ------------------------------------------------------------------ usage
    async def usage(self, session: dict[str, Any]) -> dict[str, Any]:
        res = await self.http.get(
            f"{BACKEND}/wham/usage",
            headers=self.headers(session, accept="application/json"),
            timeout=self.discovery_timeout,
        )
        if res.status_code >= 400:
            raise http_error("codex usage", res.status_code, res.text)
        data = res.json()
        windows = []
        limits = data.get("rate_limit") or {}
        for slot, fallback in (("primary_window", "session"), ("secondary_window", "weekly")):
            w = limits.get(slot)
            if not isinstance(w, dict):
                continue
            seconds = w.get("limit_window_seconds")
            kind = (
                fallback
                if seconds is None
                else "session"
                if abs(seconds - 18000) <= 900
                else "weekly"
                if abs(seconds - 604800) <= 30240
                else "other"
            )
            resets = (
                int(w["reset_at"]) * 1000
                if w.get("reset_at")
                else int(time.time() * 1000) + int(w.get("reset_after_seconds") or 0) * 1000
                if w.get("reset_after_seconds")
                else None
            )
            windows.append({"kind": kind, "usedPercent": float(w.get("used_percent") or 0), "resetsAt": resets})
        return {"supported": True, "plan": data.get("plan_type") or session.get("planType"), "windows": windows}

    # ------------------------------------------------------------------ chat
    def chat_model(self, model: str, account: str | None, **options: Any) -> Any:
        return CodexChatModel(
            model_name=model,
            provider_ref=self,
            account_key=account,
            reasoning_effort=options.get("reasoning_effort"),
            max_tokens=options.get("max_tokens"),
            fast_tier=bool(options.get("fast_tier")),
            stream_idle_timeout=self.stream_idle_timeout,
        )

    def tools(self, service: Any) -> list[Any]:
        return make_tools(self, service)


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("-", maxsplit=1)[0].split("."))


class CodexChatModel(ResponsesChatModel):
    label: str = "codex"
    fast_tier: bool = False

    async def build_request(
        self, messages: list[BaseMessage], session: dict[str, Any], session_id: str | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        instructions, items = to_responses_input(messages, repair=True, shorten_ids=True)
        body: dict[str, Any] = {
            "model": self.model_name,
            "instructions": instructions or DEFAULT_INSTRUCTIONS,
            "input": items,
            "store": False,
            "stream": True,
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": session_id or session_uuid(None),
        }
        if self.bound_tools:
            body["tools"] = to_responses_tools(self.bound_tools, strict=False)
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort, "summary": "auto"}
        provider: CodexProvider = self.provider_ref
        if self.fast_tier and provider.speed.get(session_id or "") == "fast":
            body["service_tier"] = "priority"
        headers = provider.headers(
            session,
            **{
                "session-id": session_uuid(session_id),
                "accept": "text/event-stream",
                "content-type": "application/json",
            },
        )
        return f"{BACKEND}/codex/responses", headers, body


# ---------------------------------------------------------------------- image generation
