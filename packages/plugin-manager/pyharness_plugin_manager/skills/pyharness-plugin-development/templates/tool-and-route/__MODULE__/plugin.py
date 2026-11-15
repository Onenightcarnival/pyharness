from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

name = "__DIST__"
doc = "__TITLE__: one tool, one tools/result listener, one HTTP route."
inject = ["tools", "http"]


class Config(BaseModel):
    prefix: str = Field("/__BUNDLE__", description="Route prefix on ctx.http.")
    max_note_chars: int = Field(2000, description="Longest note the tool accepts.")


def apply(ctx: Any, config: Config) -> None:
    notes: list[str] = []
    calls: Counter[str] = Counter()

    def __BUNDLE___note(text: str) -> str:
        """Keep a short note for this harness; returns the note count."""
        if len(text) > config.max_note_chars:
            return f"note rejected: longer than {config.max_note_chars} characters"
        notes.append(text)
        return f"kept; {len(notes)} notes"

    ctx.tools.register(__BUNDLE___note)

    @ctx.on("tools/result")
    async def count(call: Any, result: Any) -> None:
        calls[call.name] += 1

    router = APIRouter()

    @router.get("")
    async def status() -> dict[str, Any]:
        return {"notes": notes, "tool_calls": dict(calls)}

    # Undone with the plugin: the route disappears when the entry stops.
    ctx.http.include_router(router, prefix=config.prefix)
