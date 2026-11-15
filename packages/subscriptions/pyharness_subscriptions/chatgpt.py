from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from langchain_core.messages import BaseMessage

from pyharness import package_toml

from .common import LlmError, PermanentRefreshError, jwt_claims
from .oauth import FlowSpec, LoginAttempt, LoginError
from .providers import DiscoveredModel, Provider
from .responses import ResponsesChatModel, to_responses_input, to_responses_tools
from .store import JsonFile

_CFG = package_toml(__file__)["chatgpt"]
ISSUER: str = _CFG["ISSUER"]
AUTHORIZE_URL: str = _CFG["AUTHORIZE_URL"]
TOKEN_URL: str = _CFG["TOKEN_URL"]
JWKS_URL: str = _CFG["JWKS_URL"]
SCOPE: str = _CFG["SCOPE"]
RESOURCE: str = _CFG["RESOURCE"]
API: str = _CFG["API"]
DYNAMIC_CLIENT: str = _CFG["DYNAMIC_CLIENT"]
AGENT_NAME: str = _CFG["AGENT_NAME"]
NAMESPACE: str = _CFG["NAMESPACE"]
PERMANENT: set[str] = set(_CFG["PERMANENT"])
CLIENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.~-]+$")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class ChatGPTProvider(Provider):
    id = "chatgpt"
    title = "ChatGPT"
    vendor = "OpenAI"
    default_context = 128000

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        base = self.auth.file.path.parent
        self.registrations = JsonFile(base / "chatgpt-registrations.json", {"hostId": None, "accounts": {}})
        self._jwks: tuple[float, dict[str, Any]] | None = None
        self.verify_id_tokens = True

    # ------------------------------------------------------------------ registration
    def host_id(self) -> str:
        data = self.registrations.read()
        if not data.get("hostId"):
            data["hostId"] = f"urn:uuid:{uuid.uuid4()}"
            self.registrations.write(data)
        return str(data["hostId"])

    def registration(self, client_id: str) -> dict[str, Any] | None:
        return (self.registrations.read().get("accounts") or {}).get(client_id)

    def _save_registration(self, client_id: str, fields: dict[str, Any]) -> None:
        def go(data: dict[str, Any]) -> None:
            data.setdefault("accounts", {})[client_id] = {
                **(data["accounts"].get(client_id) or {}),
                "clientId": client_id,
                "hostId": data.get("hostId"),
                **fields,
            }

        self.registrations.update(go)

    # ------------------------------------------------------------------ flow
    def flow_spec(self, account: str | None = None) -> FlowSpec:
        registration = self.registration(account) if account else None
        client_id = registration["clientId"] if registration else DYNAMIC_CLIENT
        extra = {"ext_agent_host_id": self.host_id(), "resource": RESOURCE}
        if registration:
            previous = self.auth.get(self.id, account) or {}
            if previous.get("idToken"):
                extra["id_token_hint"] = previous["idToken"]
            if registration.get("emailAddress"):
                extra["login_hint"] = registration["emailAddress"]
            if registration.get("planEnabled") is False:
                extra["prompt"] = "consent"
        else:
            extra["agent_name_hint"] = AGENT_NAME
        spec = FlowSpec(
            provider=self.id,
            authorize_url=AUTHORIZE_URL,
            host="127.0.0.1",
            ports=(1455, 1457, 0),
            callback_path="/auth/callback",
            manual_redirect_uri="http://127.0.0.1:1455/auth/callback",
            timeout=180.0,
            require_complete_callback=True,
            scope=SCOPE,
            client_id=client_id,
            extra_params=extra,
            use_nonce=True,
        )
        self._pending_account = account
        return spec

    def validate_callback(self, query: dict[str, str]) -> None:
        client_id = query.get("client_id")
        if getattr(self, "_pending_account", None):
            if client_id and client_id != self._pending_account:
                raise LoginError("callback client_id differs from the signed-in registration")
            return
        if (
            not client_id
            or not CLIENT_ID_RE.match(client_id)
            or len(client_id) > 2048
            or client_id == DYNAMIC_CLIENT
            or client_id in dir(object)
        ):
            raise LoginError("callback did not carry a valid client_id")

    # ------------------------------------------------------------------ token validation
    async def _jwks_keys(self) -> dict[str, Any]:
        if self._jwks and time.time() - self._jwks[0] < 3600:
            return self._jwks[1]
        res = await self.http.get(JWKS_URL, timeout=15)
        res.raise_for_status()
        self._jwks = (time.time(), res.json())
        return self._jwks[1]

    async def validate_id_token(self, token: str, client_id: str, nonce: str | None) -> dict[str, Any]:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        if self.verify_id_tokens:
            if header.get("alg") != "RS256":
                raise LoginError("id_token is not RS256")
            keys = await self._jwks_keys()
            jwk = next(
                (k for k in keys.get("keys", []) if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None
            )
            if jwk is None:
                raise LoginError("id_token key not found in the issuer JWKS")
            n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
            e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
            public = rsa.RSAPublicNumbers(e, n).public_key()
            try:
                public.verify(
                    _b64url_decode(signature_b64),
                    f"{header_b64}.{payload_b64}".encode(),
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
            except Exception as exc:  # noqa: BLE001
                raise LoginError("id_token signature is invalid") from exc
        if claims.get("iss") != ISSUER:
            raise LoginError("id_token issuer mismatch")
        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if client_id not in auds or (claims.get("azp") and claims["azp"] != client_id):
            raise LoginError("id_token audience mismatch")
        now = time.time()
        if float(claims.get("exp", 0)) <= now or float(claims.get("nbf", 0)) > now:
            raise LoginError("id_token is expired or not yet valid")
        if nonce is not None and claims.get("nonce") != nonce:
            raise LoginError("id_token nonce mismatch")
        if not claims.get("sub"):
            raise LoginError("id_token has no subject")
        return claims

    # ------------------------------------------------------------------ exchange / refresh
    async def exchange(self, attempt: LoginAttempt, code: str, query: dict[str, str]) -> tuple[str, dict[str, Any]]:
        client_id = query.get("client_id") or attempt.spec.client_id
        res = await self.http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": attempt.verifier,
                "redirect_uri": attempt.redirect_uri,
                "resource": RESOURCE,
            },
            timeout=30,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"ChatGPT token exchange failed (HTTP {res.status_code}): {res.text[:300]}")
        data = res.json()
        if (
            not data.get("access_token")
            or not (data.get("expires_in") or 0) > 0
            or str(data.get("token_type", "")).lower() != "bearer"
        ):
            raise RuntimeError("ChatGPT token response is incomplete")
        if not data.get("id_token"):
            raise RuntimeError("ChatGPT did not return an id_token")
        claims = await self.validate_id_token(data["id_token"], client_id, attempt.nonce)
        scopes = str(data.get("scope") or "").split()
        plan_enabled = "chatgpt.tokens.use.direct" in scopes
        self._save_registration(
            client_id, {"subject": claims["sub"], "emailAddress": claims.get("email"), "planEnabled": plan_enabled}
        )
        if not plan_enabled:
            raise RuntimeError("ChatGPT plan usage was not enabled. Continue with ChatGPT to grant access.")
        if not data.get("refresh_token"):
            raise RuntimeError("ChatGPT did not grant offline access. Sign in again.")
        session = {
            "accessToken": data["access_token"],
            "refreshToken": data["refresh_token"],
            "expiresAt": int(time.time() * 1000) + int(data["expires_in"]) * 1000,
            "clientId": client_id,
            "subject": claims["sub"],
            "hostId": self.host_id(),
            "idToken": data["id_token"],
            "emailAddress": claims.get("email"),
            "scopes": scopes,
        }
        return client_id, session

    async def refresh(self, session: dict[str, Any]) -> dict[str, Any]:
        res = await self.http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": session["clientId"],
                "refresh_token": session["refreshToken"],
                "resource": RESOURCE,
            },
            timeout=30,
        )
        if res.status_code >= 400:
            try:
                code = res.json().get("error")
            except ValueError:
                code = None
            if code in PERMANENT:
                raise PermanentRefreshError(str(code))
            raise RuntimeError(f"ChatGPT refresh failed (HTTP {res.status_code})")
        data = res.json()
        if not data.get("refresh_token"):
            raise RuntimeError("ChatGPT refresh returned no refresh token")
        fresh = {
            **session,
            "accessToken": data["access_token"],
            "refreshToken": data["refresh_token"],
            "expiresAt": int(time.time() * 1000) + int(data.get("expires_in") or 3600) * 1000,
        }
        if data.get("id_token"):
            claims = await self.validate_id_token(data["id_token"], session["clientId"], None)
            if claims["sub"] != session.get("subject"):
                raise RuntimeError("ChatGPT subject changed during refresh")
            fresh["idToken"] = data["id_token"]
        if data.get("scope"):
            fresh["scopes"] = str(data["scope"]).split()
        return fresh

    async def logout(self, key: str) -> None:
        session = self.auth.get(self.id, key)
        detail = None
        if session and session.get("refreshToken"):
            try:
                cfg = (await self.http.get(f"{ISSUER}/.well-known/openid-configuration", timeout=10)).json()
                endpoint = cfg.get("revocation_endpoint") or ""
                if cfg.get("issuer") != ISSUER or not endpoint.startswith(ISSUER):
                    raise RuntimeError("unexpected revocation endpoint")
                res = await self.http.post(
                    endpoint,
                    data={
                        "token": session["refreshToken"],
                        "token_type_hint": "refresh_token",
                        "client_id": session["clientId"],
                    },
                    timeout=5,
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"HTTP {res.status_code}")
            except Exception:  # noqa: BLE001
                detail = (
                    "Signed out locally. Remote revocation was not confirmed; disconnect the app in ChatGPT settings."
                )
        await super().logout(key)
        if detail:
            self.last_error = detail

    def account_label(self, session: dict[str, Any]) -> str:
        email = session.get("emailAddress")
        return (
            f"{email} · {str(session.get('clientId', ''))[-6:]}"
            if email
            else str(session.get("clientId") or self.title)
        )

    def account_rows(self) -> list[dict[str, Any]]:
        rows = super().account_rows()
        for row in rows:
            session = self.auth.get(self.id, row["key"]) or {}
            row["planEnabled"] = "chatgpt.tokens.use.direct" in (session.get("scopes") or [])
        known = {r["key"] for r in rows}
        for client_id, reg in (self.registrations.read().get("accounts") or {}).items():
            if client_id not in known:
                rows.append(
                    {
                        "key": client_id,
                        "account": reg.get("emailAddress") or client_id,
                        "isDefault": False,
                        "connected": False,
                        "planEnabled": bool(reg.get("planEnabled")),
                    }
                )
        return rows

    # ------------------------------------------------------------------ catalog
    async def discover(self, session: dict[str, Any]) -> list[DiscoveredModel]:
        if "chatgpt.tokens.use.direct" not in (session.get("scopes") or []):
            raise LlmError("INVALID_CREDENTIAL", "ChatGPT plan usage is disabled. Sign in again and allow plan usage.")
        res = await self.http.get(
            f"{API}/models",
            headers={"authorization": f"Bearer {session['accessToken']}", "accept": "application/json"},
            timeout=self.discovery_timeout,
        )
        res.raise_for_status()
        data = res.json()
        entries = data.get("models") if isinstance(data.get("models"), list) else data.get("data") or []
        out = []
        for m in entries:
            if m.get("visibility") not in (None, "list"):
                continue
            mid = str(m.get("slug") or m.get("id"))
            efforts = [
                {"id": lvl.get("effort"), "name": str(lvl.get("effort")).capitalize()}
                for lvl in m.get("supported_reasoning_levels") or []
                if lvl.get("effort")
            ]
            modalities = ["text", "image"] if "image" in (m.get("input_modalities") or []) else ["text"]
            out.append(
                DiscoveredModel(
                    id=mid,
                    name=str(m.get("display_name") or mid),
                    description=m.get("description"),
                    context_window=m.get("context_window"),
                    max_context_window=m.get("max_context_window"),
                    efforts=efforts,
                    default_effort=m.get("default_reasoning_level"),
                    input_modalities=modalities,
                )
            )
        return out

    def chat_model(self, model: str, account: str | None, **options: Any) -> Any:
        return ChatGPTChatModel(
            model_name=model,
            provider_ref=self,
            account_key=account,
            reasoning_effort=options.get("reasoning_effort"),
            max_tokens=options.get("max_tokens"),
            stream_idle_timeout=self.stream_idle_timeout,
        )


class ChatGPTChatModel(ResponsesChatModel):
    label: str = "chatgpt"

    async def build_request(
        self, messages: list[BaseMessage], session: dict[str, Any], session_id: str | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        instructions, items = to_responses_input(messages, repair=True, shorten_ids=False, namespace=NAMESPACE)
        body: dict[str, Any] = {"model": self.model_name, "input": items, "store": False, "stream": True}
        if instructions:
            body["instructions"] = instructions
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort, "summary": "auto"}
        if self.bound_tools:
            body["tools"] = [
                {
                    "type": "namespace",
                    "name": NAMESPACE,
                    "description": "pyharness tools",
                    "tools": to_responses_tools(self.bound_tools, strict=False),
                }
            ]
        headers = {
            "authorization": f"Bearer {session['accessToken']}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        return f"{API}/responses", headers, body


__all__ = ["ChatGPTChatModel", "ChatGPTProvider", "jwt_claims"]
