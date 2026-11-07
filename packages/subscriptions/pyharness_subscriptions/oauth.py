"""OAuth loopback flow: one temporary HTTP server per login attempt (PKCE S256, state, nonce), manual callback
input when the browser cannot reach the harness, timeout and cancel."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

SUCCESS_HTML = (
    "<!doctype html><meta charset=utf-8><title>Login successful</title>"
    "<body style='font-family:system-ui;padding:40px'><h1>Login successful</h1>"
    "<p>You can close this tab and return to pyharness.</p></body>"
)
FAILED_HTML = (
    "<!doctype html><meta charset=utf-8><title>Login failed</title>"
    "<body style='font-family:system-ui;padding:40px'><h1>Login failed</h1><p>{detail}</p></body>"
)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


class LoginError(RuntimeError):
    pass


@dataclass
class FlowSpec:
    """How a provider's login works: where to listen and what the authorize URL looks like."""

    provider: str
    authorize_url: str
    host: str = "localhost"
    ports: tuple[int, ...] = (0,)
    callback_path: str = "/auth/callback"
    manual_redirect_uri: str | None = None
    timeout: float = 180.0
    require_complete_callback: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)
    scope: str = ""
    client_id: str = ""
    use_nonce: bool = False


@dataclass
class Callback:
    code: str
    query: dict[str, str]


class LoginAttempt:
    """One login: ``start()`` binds the callback server and returns the authorize URL; ``wait()`` yields the code."""

    def __init__(self, spec: FlowSpec) -> None:
        self.spec = spec
        self.state = b64url(secrets.token_bytes(32))
        self.verifier, self.challenge = pkce_pair()
        self.nonce = secrets.token_hex(32)
        self.redirect_uri = ""
        self.manual_only = False
        self.authorize_url = ""
        self._server: asyncio.AbstractServer | None = None
        self._result: asyncio.Future[Callback] = asyncio.get_event_loop().create_future()
        self._validate: Any = None

    # ------------------------------------------------------------------ server
    async def start(self, validate: Any = None) -> str:
        self._validate = validate
        bound = False
        last_error: Exception | None = None
        for port in self.spec.ports:
            tries = 3 if port == 0 else 1
            for _ in range(tries):
                try:
                    self._server = await asyncio.start_server(
                        self._handle, host=self.spec.host if self.spec.host != "localhost" else None, port=port
                    )
                    bound = True
                    break
                except OSError as exc:
                    last_error = exc
            if bound:
                break
        if bound and self._server is not None:
            actual = self._server.sockets[0].getsockname()[1]
            self.redirect_uri = f"http://{self.spec.host}:{actual}{self.spec.callback_path}"
        elif self.spec.manual_redirect_uri:
            self.manual_only = True
            self.redirect_uri = self.spec.manual_redirect_uri
        else:
            raise LoginError(f"cannot listen for the callback: {last_error}")
        params = {
            "response_type": "code",
            "client_id": self.spec.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.spec.scope,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "state": self.state,
            **self.spec.extra_params,
        }
        if self.spec.use_nonce:
            params["nonce"] = self.nonce
        self.authorize_url = f"{self.spec.authorize_url}?{urlencode(params)}"
        return self.authorize_url

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), 10)
            while True:
                line = await asyncio.wait_for(reader.readline(), 10)
                if not line or line in (b"\r\n", b"\n"):
                    break
            parts = request_line.decode("latin-1").split()
            target = parts[1] if len(parts) > 1 else "/"
            status, body = self._respond(target)
            payload = body.encode("utf-8")
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\ncontent-type: text/html; charset=utf-8\r\n"
                    f"content-length: {len(payload)}\r\nconnection: close\r\n\r\n"
                ).encode()
                + payload
            )
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    def _respond(self, target: str) -> tuple[str, str]:
        parsed = urlparse(target)
        if parsed.path != self.spec.callback_path:
            return "404 Not Found", "not found"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            self._accept(query)
        except LoginError as exc:
            if "authorization failed" in str(exc):
                return "200 OK", FAILED_HTML.format(detail=str(exc))
            return "400 Bad Request", str(exc)
        return "200 OK", SUCCESS_HTML

    def _accept(self, query: dict[str, str]) -> None:
        if query.get("state") != self.state:
            raise LoginError("state mismatch")
        if query.get("error") or query.get("error_description"):
            detail = query.get("error_description") or query.get("error") or ""
            self._fail(LoginError(f"authorization failed: {detail}"))
            raise LoginError(f"authorization failed: {detail}")
        code = query.get("code")
        if not code:
            raise LoginError("missing authorization code")
        if self._validate is not None:
            self._validate(query)
        if not self._result.done():
            self._result.set_result(Callback(code=code, query=query))

    def _fail(self, exc: Exception) -> None:
        if not self._result.done():
            self._result.set_exception(exc)

    # ------------------------------------------------------------------ manual input
    def manual(self, text: str) -> None:
        """Accept a pasted callback URL, a query string with ``code=``, or a bare code."""
        value = (text or "").strip()
        if not value:
            raise LoginError("empty input")
        if value.startswith(("http://", "https://")):
            parsed = urlparse(value)
            expected = urlparse(self.redirect_uri)
            if (parsed.scheme, parsed.hostname, parsed.port or 80, parsed.path) != (
                expected.scheme,
                expected.hostname,
                expected.port or 80,
                expected.path,
            ):
                raise LoginError("the URL does not match the expected callback address")
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        elif "code=" in value and not (self.manual_only or self.spec.require_complete_callback):
            query = {k: v[0] for k, v in parse_qs(value.lstrip("?")).items()}
        elif " " not in value and not (self.manual_only or self.spec.require_complete_callback):
            query = {"code": value, "state": self.state}
        else:
            raise LoginError("paste the full callback URL from the browser address bar")
        if "state" not in query and not (self.manual_only or self.spec.require_complete_callback):
            query["state"] = self.state
        self._accept(query)

    # ------------------------------------------------------------------ outcome
    async def wait(self) -> Callback:
        try:
            return await asyncio.wait_for(asyncio.shield(self._result), self.spec.timeout)
        except TimeoutError:
            raise LoginError(f"login timed out after {int(self.spec.timeout)}s") from None
        finally:
            await self.close()

    def cancel(self) -> None:
        self._fail(LoginError("login cancelled"))

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._server = None
