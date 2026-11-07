"""Shared pieces: error codes, HTTP error mapping, SSE parsing, JWT claims, the token manager (refresh with shared
in-flight calls, permanent-error detection), request attribution."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from pyharness import package_toml

_CFG = package_toml(__file__)["common"]
USER_AGENT: str = _CFG["USER_AGENT"]
RESET_FIELDS: tuple[str, ...] = tuple(_CFG["RESET_FIELDS"])
PREEMPT_MS = 5 * 60 * 1000
STREAM_IDLE_TIMEOUT = 300.0


class LlmError(RuntimeError):
    def __init__(self, code: str, message: str, *, retry_after_ms: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_ms = retry_after_ms


def not_logged_in(name: str) -> LlmError:
    return LlmError("MISSING_CREDENTIAL", f"not logged in to {name}; log in on the AI subscriptions page")


def http_error(label: str, status: int, body: str) -> LlmError:
    text = body if body and not body.lstrip().startswith("<") else ""
    message = f"{label} error (HTTP {status}): {text[:500] or httpx.codes.get_reason_phrase(status) or status}"
    if status in (401, 403):
        return LlmError("AUTH", message)
    if status == 429:
        return LlmError("RATE_LIMIT", message, retry_after_ms=reset_delay_ms(body))
    if re.search(r"quota|insufficient", body or "", re.I):
        return LlmError("QUOTA_EXCEEDED", message)
    if status == 400 and re.search(r"context[ _-]?(window|length)|too many tokens|maximum context", body or "", re.I):
        return LlmError("CONTEXT_WINDOW_EXCEEDED", message)
    if status in (408, 504):
        return LlmError("TIMEOUT", message)
    if status >= 500:
        return LlmError("SERVER", message)
    return LlmError(f"HTTP_{status}", message)


def reset_delay_ms(body: str | None) -> int | None:
    """Earliest rate-limit reset found in a JSON body (seconds, epoch seconds / ms), as a wait in ms."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    found: list[float] = []

    def walk(value: Any, depth: int) -> None:
        if depth > 4:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if k in RESET_FIELDS and isinstance(v, (int, float)):
                    found.append(float(v))
                walk(v, depth + 1)
        elif isinstance(value, list):
            for v in value:
                walk(v, depth + 1)

    walk(data, 0)
    if not found:
        return None
    now = time.time()
    waits = []
    for v in found:
        if v >= 1e12:
            waits.append(v / 1000 - now)
        elif v >= 1e9:
            waits.append(v - now)
        else:
            waits.append(v)
    return int(max(1.0, min(waits) + 2.0) * 1000)


async def read_error(res: httpx.Response) -> str:
    try:
        return (await res.aread()).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------- SSE
@dataclass
class SseEvent:
    event: str | None
    data: str


async def iter_sse(
    res: httpx.Response, label: str, idle_timeout: float = STREAM_IDLE_TIMEOUT
) -> AsyncIterator[SseEvent]:
    """Parse an SSE body: ``data:`` lines joined with newlines, dispatched on blank lines; comments reset the idle
    timer."""
    event: str | None = None
    data: list[str] = []
    lines = res.aiter_lines()
    while True:
        try:
            line = await asyncio.wait_for(lines.__anext__(), idle_timeout)
        except StopAsyncIteration:
            return
        except TimeoutError:
            raise LlmError("TIMEOUT", f"{label} stream idle timeout") from None
        line = line.rstrip("\r")
        if line == "":
            if data:
                yield SseEvent(event, "\n".join(data))
            event, data = None, []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" ") if line.startswith("data: ") else line[5:])


# ---------------------------------------------------------------------- JWT
def jwt_claims(token: str | None) -> dict[str, Any]:
    """Unverified payload of a JWT (``{}`` when it is not one)."""
    if not token or token.count(".") != 2:
        return {}
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def headers_with_ua(headers: dict[str, str]) -> dict[str, str]:
    return {"user-agent": USER_AGENT, **headers}


# ---------------------------------------------------------------------- token manager
class TokenManager:
    """Valid session for one account; refreshes early (``preempt_ms``), shares one in-flight refresh, deletes the
    account on a permanent refresh error."""

    def __init__(self, provider: Any, key: str, preempt_ms: int = PREEMPT_MS) -> None:
        self.provider = provider
        self.key = key
        self.preempt_ms = preempt_ms
        self._inflight: asyncio.Task[dict[str, Any]] | None = None

    async def session(self, force: bool = False) -> dict[str, Any]:
        stored = self.provider.auth.get(self.provider.id, self.key)
        if stored is None:
            raise not_logged_in(self.provider.title)
        if not force and int(stored.get("expiresAt") or 0) - int(time.time() * 1000) > self.preempt_ms:
            return stored
        if self._inflight is None or self._inflight.done():
            self._inflight = asyncio.create_task(self._refresh(stored))
        return await self._inflight

    async def _refresh(self, stored: dict[str, Any]) -> dict[str, Any]:
        latest = self.provider.auth.get(self.provider.id, self.key)
        if latest is None:
            raise not_logged_in(self.provider.title)
        if (
            latest.get("refreshToken") != stored.get("refreshToken")
            and int(latest.get("expiresAt") or 0) - int(time.time() * 1000) > self.preempt_ms
        ):
            return latest
        try:
            fresh = await self.provider.refresh(latest)
        except PermanentRefreshError as exc:
            again = self.provider.auth.get(self.provider.id, self.key)
            if again is not None and again.get("refreshToken") != latest.get("refreshToken"):
                return again
            self.provider.auth.delete(self.provider.id, self.key)
            raise LlmError(
                "INVALID_CREDENTIAL",
                f"{self.provider.title} login expired or was revoked; log in again on the AI subscriptions page",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            if int(latest.get("expiresAt") or 0) > int(time.time() * 1000):
                return latest
            raise LlmError("AUTH", f"{self.provider.title} token refresh failed: {exc}") from exc
        self.provider.auth.save(self.provider.id, self.key, fresh)
        return fresh


class PermanentRefreshError(RuntimeError):
    pass


def session_uuid(session_id: str | None) -> str:
    """A UUID for a session id: the id itself when it is one, else a UUIDv8 from its hash, else random."""
    if session_id:
        try:
            return str(uuid.UUID(session_id))
        except ValueError:
            digest = bytearray(hashlib.sha256(session_id.encode()).digest()[:16])
            digest[6] = (digest[6] & 0x0F) | 0x80
            digest[8] = (digest[8] & 0x3F) | 0x80
            return str(uuid.UUID(bytes=bytes(digest)))
    return str(uuid.uuid4())
