from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .routes_harness import build_harness_router
from .routes_sessions import build_sessions_router
from .routes_settings import build_settings_router
from .routes_workspaces import build_workspaces_router

name = "pyxis-harness-api"
doc = "REST and SSE API over ``ctx.agents``, under ``/api`` on ``ctx.http``."
inject = ["http", "agents", "llm"]


class Config(BaseModel):
    prefix: str = "/api"
    llm_entry: str = Field("llm", description="Entry id of the model registry the settings page edits.")


def build_router(ctx: Any) -> APIRouter:
    router = APIRouter()
    router.include_router(build_harness_router(ctx))
    router.include_router(build_sessions_router(ctx))
    router.include_router(build_workspaces_router(ctx))
    return router


def apply(ctx: Any, config: Config) -> None:
    ctx.http.include_router(build_router(ctx), prefix=config.prefix, tags=["pyxis-harness"])
    ctx.http.include_router(build_settings_router(ctx, config.llm_entry), prefix=config.prefix, tags=["pyxis-harness"])
