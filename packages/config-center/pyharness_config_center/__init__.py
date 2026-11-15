from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, ClassVar

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from pyharness import Service, manage
from pyharness.credentials import REFERENCE
from pyharness_mcp import MASK, ServerConfig, references

from .environment import BUN_VERSION, BunManager
from .skills import SkillError, SkillStore

ZIP_BODY_LIMIT = (32 * 1024 * 1024 * 4) // 3 + 4096


class Config(BaseModel):
    bun_version: str = Field(BUN_VERSION, description="bun release installed by Settings → Environment.")
    skills_presets: list[str] | None = Field(
        None, description="Agent presets that see the user skills; all when unset."
    )


class ConfigCenterService(Service):
    """MCP page, skills and the managed runtime."""

    key = "configCenter"
    name = "pyharness-config-center"
    inject: ClassVar[list[str]] = ["http", "webui", "agentLoop"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.skills: SkillStore | None = None
        self.bun: BunManager | None = None

    def _data(self) -> Path:
        profile = self.ctx.get("profile", None)
        base = (
            Path(profile.data)
            if profile is not None and hasattr(profile, "data")
            else Path.home() / ".pyharness" / "data"
        )
        return base / "toolkit"

    async def start(self) -> None:
        data = self._data()
        self.skills = SkillStore(data)
        self.bun = BunManager(data / "bun", self.config.bun_version)
        self.ctx.agentLoop.add_skills(self.skills.enabled_dir, "user", presets=self.config.skills_presets)
        self.ctx.http.include_router(self._router(), prefix="/api/config-center", tags=["pyharness-config-center"])
        self.ctx.webui.register_client(Path(__file__).with_name("client.js"))

    # ------------------------------------------------------------------ routes
    def _router(self) -> APIRouter:
        router = APIRouter()
        service = self

        async def body(request: Request, limit: int = 64 * 1024) -> dict[str, Any]:
            raw = await request.body()
            if len(raw) > limit:
                raise HTTPException(413, "body too large")
            try:
                data = json.loads(raw) if raw else None
            except ValueError:
                data = None
            if not isinstance(data, dict):
                raise HTTPException(400, "invalid JSON body")
            return data

        def mcp_service() -> Any:
            mcp = service.ctx.get("mcp", None)
            if mcp is None:
                raise HTTPException(503, "mcp plugin not mounted")
            return mcp

        def profile() -> Any:
            p = service.ctx.get("profile", None)
            if p is None:
                raise HTTPException(503, "no profile")
            return p

        # -------------------------------------------------------------- mcp
        @router.get("/mcp")
        async def mcp_list() -> dict[str, Any]:
            mcp = mcp_service()
            return {"servers": mcp.servers(), "connectTimeout": mcp.config.connect_timeout}

        @router.put("/mcp/timeout")
        async def mcp_timeout(request: Request) -> dict[str, Any]:
            data = await body(request)
            seconds = data.get("connectTimeout")
            if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 1 <= seconds <= 86400:
                raise HTTPException(400, "connectTimeout must be a number of seconds from 1 to 86400")
            result = await manage.set_entry_config(
                profile(), "mcp", {"connect_timeout": float(seconds)}, merge=True, preflight=False
            )
            if result.get("application") == "rejected":
                raise HTTPException(422, result.get("error") or "rejected")
            mcp_service().config.connect_timeout = float(seconds)
            return {"connectTimeout": float(seconds), "application": result.get("application")}

        @router.post("/mcp/test")
        async def mcp_test(request: Request) -> dict[str, Any]:
            mcp = mcp_service()
            data = await body(request)
            raw = data.get("server")
            if not isinstance(raw, dict):
                raise HTTPException(400, "server is required")
            previous = mcp.config.servers.get(str(data.get("name") or ""))
            for secret in ("env", "headers"):
                values = dict(raw.get(secret) or {})
                for key, value in list(values.items()):
                    if value == MASK:
                        kept = (getattr(previous, secret, None) or {}).get(key) if previous is not None else None
                        if kept is None:
                            raise HTTPException(422, f"{secret} {key}: value required")
                        values[key] = kept
                raw[secret] = values
            try:
                cfg = ServerConfig.model_validate({k: v for k, v in raw.items() if k in ServerConfig.model_fields})
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, f"invalid server: {exc}") from exc
            if not cfg.command and not cfg.url:
                raise HTTPException(400, "a server needs a command (stdio) or a url")
            timeout = data.get("timeout") if isinstance(data.get("timeout"), (int, float)) else None
            return {"result": await mcp.probe(cfg, timeout)}

        def credential_answer(reference: str, changed: bool) -> dict[str, Any]:
            """The credential's description and ``application``; requests the restart ``application`` names."""
            servers = mcp_service().config.servers.values()
            application = "saved"
            if changed and any(cfg.enabled and reference in references(cfg) for cfg in servers):
                lifecycle = service.ctx.lifecycle
                if lifecycle.supervised:
                    lifecycle.request_restart("MCP credential changed")
                    application = "restart-scheduled"
                else:
                    application = "saved-restart-required"
            return {"credential": profile().credentials.describe(reference), "application": application}

        @router.put("/mcp/credentials")
        async def mcp_credential_set(request: Request) -> dict[str, Any]:
            data = await body(request)
            reference, value = data.get("reference"), data.get("value")
            if not isinstance(reference, str) or not isinstance(value, str):
                raise HTTPException(400, "reference and value are required")
            mcp_service()
            try:
                profile().credentials.set(reference, value)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            return credential_answer(reference, True)

        @router.delete("/mcp/credentials")
        async def mcp_credential_delete(reference: str | None = None) -> dict[str, Any]:
            if not reference or not REFERENCE.match(reference):
                raise HTTPException(400, "reference is required: uppercase letters, digits and underscores")
            mcp_service()
            return credential_answer(reference, profile().credentials.delete(reference))

        # -------------------------------------------------------------- skills
        def skills() -> SkillStore:
            assert service.skills is not None
            return service.skills

        def skill_error(exc: SkillError) -> HTTPException:
            return HTTPException(400, str(exc))

        def listing() -> dict[str, Any]:
            return {"directory": str(skills().enabled_dir), "skills": skills().list()}

        @router.get("/skills")
        async def skills_list() -> dict[str, Any]:
            return listing()

        @router.post("/skills")
        async def skills_toggle(request: Request) -> dict[str, Any]:
            data = await body(request)
            if not isinstance(data.get("name"), str) or not isinstance(data.get("enabled"), bool):
                raise HTTPException(400, "invalid skill parameters")
            try:
                await asyncio.to_thread(skills().set_enabled, data["name"], data["enabled"])
            except SkillError as exc:
                raise skill_error(exc) from exc
            return listing()

        @router.delete("/skills")
        async def skills_delete(name: str | None = None) -> dict[str, Any]:
            try:
                await asyncio.to_thread(skills().remove, name or "")
            except SkillError as exc:
                raise skill_error(exc) from exc
            return listing()

        @router.get("/skills/detail")
        async def skills_detail(name: str | None = None) -> dict[str, Any]:
            try:
                return await asyncio.to_thread(skills().detail, name or "")
            except SkillError as exc:
                raise skill_error(exc) from exc

        @router.get("/skills/file")
        async def skills_file(name: str | None = None, file: str | None = None) -> dict[str, Any]:
            try:
                return await asyncio.to_thread(skills().read_file, name or "", file or "")
            except SkillError as exc:
                raise skill_error(exc) from exc

        @router.post("/skills/install")
        async def skills_install(request: Request) -> dict[str, Any]:
            data = await body(request, ZIP_BODY_LIMIT)
            encoded, policy = data.get("data"), data.get("policy", "ask")
            if not isinstance(encoded, str) or policy not in ("ask", "skip", "replace"):
                raise HTTPException(400, "invalid installation parameters")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, "invalid installation parameters") from exc
            try:
                return await asyncio.to_thread(skills().install_zip, raw, policy)
            except SkillError as exc:
                raise skill_error(exc) from exc

        @router.post("/skills/open")
        async def skills_open(name: str | None = None) -> dict[str, Any]:
            try:
                skills().open_folder(name or None)
            except SkillError as exc:
                raise skill_error(exc) from exc
            except OSError as exc:
                raise HTTPException(500, str(exc)) from exc
            return {"ok": True}

        # -------------------------------------------------------------- environment
        @router.get("/environment")
        async def environment() -> dict[str, Any]:
            assert service.bun is not None
            return await asyncio.to_thread(service.bun.status)

        @router.post("/environment", status_code=202)
        async def environment_install() -> dict[str, Any]:
            assert service.bun is not None
            try:
                return service.bun.install()
            except RuntimeError as exc:
                raise HTTPException(500, str(exc)) from exc

        return router


__all__ = ["BunManager", "ConfigCenterService", "SkillStore"]
