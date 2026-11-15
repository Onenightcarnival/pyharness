from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .common import STREAM_IDLE_TIMEOUT, TokenManager, not_logged_in
from .oauth import FlowSpec, LoginAttempt
from .store import AuthStore, CatalogCache


@dataclass
class DiscoveredModel:
    id: str
    name: str
    description: str | None = None
    context_window: int | None = None
    max_context_window: int | None = None
    max_output_tokens: int | None = None
    priority: int | None = None
    efforts: list[dict[str, str]] = field(default_factory=list)
    default_effort: str | None = None
    input_modalities: list[str] = field(default_factory=lambda: ["text"])
    fast_tier: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "contextWindow": self.context_window,
            "maxContextWindow": self.max_context_window,
            "maxOutputTokens": self.max_output_tokens,
            "priority": self.priority,
            "efforts": self.efforts,
            "defaultEffort": self.default_effort,
            "inputModalities": self.input_modalities,
            "fastTier": self.fast_tier,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DiscoveredModel:
        return cls(
            id=str(d["id"]),
            name=str(d.get("name") or d["id"]),
            description=d.get("description"),
            context_window=d.get("contextWindow"),
            max_context_window=d.get("maxContextWindow"),
            max_output_tokens=d.get("maxOutputTokens"),
            priority=d.get("priority"),
            efforts=list(d.get("efforts") or []),
            default_effort=d.get("defaultEffort"),
            input_modalities=list(d.get("inputModalities") or ["text"]),
            fast_tier=bool(d.get("fastTier")),
        )


class Provider:
    id = ""
    title = ""
    vendor = ""
    default_context = 128000
    default_max_tokens: int | None = None
    preempt_ms = 5 * 60 * 1000
    discovery_timeout = 10.0
    stream_idle_timeout = STREAM_IDLE_TIMEOUT  # seconds without stream data before a chat model fails

    def __init__(
        self, auth: AuthStore, catalogs: CatalogCache, http: httpx.AsyncClient, config: dict[str, Any] | None = None
    ) -> None:
        self.auth = auth
        self.catalogs = catalogs
        self.http = http
        self.config = config or {}
        self._managers: dict[str, TokenManager] = {}
        self._usage_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.attempt: LoginAttempt | None = None
        self._login: asyncio.Task[None] | None = None  # the running login; referenced until it ends
        self.last_error: str | None = None
        self.busy = False

    # ------------------------------------------------------------------ accounts
    def token_manager(self, key: str | None = None) -> TokenManager:
        key = key or self.auth.default_key(self.id) or ""
        if not key:
            raise not_logged_in(self.title)
        manager = self._managers.get(key)
        if manager is None:
            manager = self._managers[key] = TokenManager(self, key, self.preempt_ms)
        return manager

    def account_label(self, session: dict[str, Any]) -> str:
        return str(session.get("account") or session.get("emailAddress") or session.get("accountId") or self.title)

    def plan(self, session: dict[str, Any]) -> str | None:
        return session.get("planType") or session.get("plan")

    def account_rows(self) -> list[dict[str, Any]]:
        rows = []
        default = self.auth.default_key(self.id)
        for key in self.auth.ordered_keys(self.id):
            session = self.auth.get(self.id, key) or {}
            rows.append(
                {
                    "key": key,
                    "account": self.account_label(session),
                    "plan": self.plan(session),
                    "isDefault": key == default,
                    "expiresAt": session.get("expiresAt"),
                    "connected": True,
                }
            )
        return rows

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "busy": self.busy,
            "manualOnly": bool(self.attempt and self.attempt.manual_only),
            "accounts": self.account_rows(),
        }
        if self.last_error:
            out["detail"] = self.last_error
        return out

    # ------------------------------------------------ login (subclasses: flow_spec, exchange, refresh)
    def flow_spec(self, account: str | None = None) -> FlowSpec:
        raise NotImplementedError

    async def exchange(self, attempt: LoginAttempt, code: str, query: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """``(account_key, session)`` from the authorization code."""
        raise NotImplementedError

    async def refresh(self, session: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def validate_callback(self, query: dict[str, str]) -> None:
        return None

    async def login(self, account: str | None = None) -> dict[str, Any]:
        if self.attempt is not None:
            raise RuntimeError(f"a {self.title} login is already in progress")
        attempt = LoginAttempt(self.flow_spec(account))
        url = await attempt.start(self.validate_callback)
        self.attempt = attempt
        self.busy = True
        self.last_error = None
        self._login = asyncio.create_task(self._finish_login(attempt))
        return {"authorizeUrl": url, "manualOnly": attempt.manual_only}

    async def _finish_login(self, attempt: LoginAttempt) -> None:
        try:
            callback = await attempt.wait()
            key, session = await self.exchange(attempt, callback.code, callback.query)
            self.auth.save(self.id, key, session)
            self._managers.pop(key, None)
            self.catalogs.clear(self.id)
        except Exception as exc:  # noqa: BLE001
            if "cancelled" not in str(exc):
                self.last_error = str(exc)
        finally:
            if self.attempt is attempt:
                self.attempt = None
                self.busy = False

    def manual(self, text: str) -> None:
        if self.attempt is None:
            raise RuntimeError("no login in progress")
        self.attempt.manual(text)

    def cancel(self) -> None:
        if self.attempt is not None:
            self.attempt.cancel()

    async def logout(self, key: str) -> None:
        self.auth.delete(self.id, key)
        self._managers.pop(key, None)
        self.catalogs.clear(self.id)

    # ------------------------------------------------------------------ catalog and usage
    async def discover(self, session: dict[str, Any]) -> list[DiscoveredModel]:
        raise NotImplementedError

    def fallback_models(self) -> list[DiscoveredModel]:
        return []

    async def models(self, key: str | None = None, force: bool = False) -> tuple[list[DiscoveredModel], bool]:
        """``(models, available)``: fresh discovery, else the last-known catalog, else the static fallback."""
        configured = self.config.get("models")
        if configured:
            return [
                DiscoveredModel(
                    id=m["id"],
                    name=m.get("name") or m["id"],
                    context_window=m.get("contextWindow"),
                    max_output_tokens=m.get("maxTokens"),
                    input_modalities=m.get("inputModalities") or ["text"],
                )
                for m in configured
            ], True
        key = key or self.auth.default_key(self.id)
        if not key:
            return self.fallback_models(), False
        cached = self.catalogs.get(self.id, key)
        if cached and not force and self.catalogs.fresh(self.id, key):
            return [DiscoveredModel.from_dict(m) for m in cached["models"]], True
        try:
            manager = self.token_manager(key)
            session = await manager.session(force=False)
            try:
                models = await asyncio.wait_for(self.discover(session), self.discovery_timeout)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 401:
                    raise
                session = await manager.session(force=True)
                models = await asyncio.wait_for(self.discover(session), self.discovery_timeout)
            self.catalogs.set(self.id, [m.describe() for m in models], key)
            return models, True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{self.title}: {exc}"
            if cached:
                return [DiscoveredModel.from_dict(m) for m in cached["models"]], False
            return self.fallback_models(), False

    async def usage(self, session: dict[str, Any]) -> dict[str, Any]:
        return {"supported": False}

    async def usage_cached(self, key: str | None = None, force: bool = False) -> dict[str, Any]:
        key = key or self.auth.default_key(self.id) or ""
        hit = self._usage_cache.get(key)
        if hit and not force and time.time() - hit[0] < 300:
            return hit[1]
        try:
            session = await self.token_manager(key).session()
            data = await asyncio.wait_for(self.usage(session), self.discovery_timeout)
        except Exception as exc:
            if hit:
                return {**hit[1], "stale": True, "error": str(exc)}
            raise
        self._usage_cache[key] = (time.time(), data)
        return data

    # ------------------------------------------------------------------ chat models
    def chat_model(self, model: str, account: str | None, **options: Any) -> Any:
        raise NotImplementedError

    def tools(self, service: Any) -> list[Any]:
        return []
