from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

name = "__DIST__"
doc = "__TITLE__."
# Required services; the plugin starts once all exist.
inject = ["tools"]

# Mount position in the configuration tree.
BUNDLE = Path(__file__).with_name("bundle.yaml")


class Config(BaseModel):
    greeting: str = "hello"


def apply(ctx: Any, config: Config) -> None:
    def greet(person: str) -> str:
        """Greeting for a person."""
        return f"{config.greeting}, {person}!"

    # Registrations through ctx are undone when the plugin stops.
    ctx.tools.register(greet)

    # tools/result (parallel): each finished tool call.
    # @ctx.on("tools/result")
    # async def audit(call, result):
    #     ctx.logger.info("tool %s finished", call.name)

    # HTTP routes, with "http" in `inject` and `from fastapi import APIRouter` at the top of the file:
    # router = APIRouter()
    # @router.get("/status")
    # async def status() -> dict:
    #     return {"ok": True}
    # ctx.http.include_router(router, prefix="/__BUNDLE__")
