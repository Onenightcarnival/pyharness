"""Web UI: one self-contained page at ``config.path`` on ``ctx.http``; data from ``/api``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

name = "pyharness-web-ui"
inject = ["http"]

INDEX = Path(__file__).with_name("index.html")


class Config(BaseModel):
    path: str = "/"


def apply(ctx: Any, config: Config) -> None:
    html = INDEX.read_text(encoding="utf-8")
    router = APIRouter()

    @router.get(config.path, response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        return html

    ctx.http.include_router(router)
