"""Test tools; recorder for tools/* events."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

name = "testkit-tools"
inject = ["tools"]

RESULTS: list[tuple[str, str]] = []


class Config(BaseModel):
    gate_danger: bool = True


def apply(ctx: Any, config: Config) -> None:
    def shout(text: str) -> str:
        """Upper-cased text."""
        return text.upper()

    def danger(target: str) -> str:
        """Simulated destructive action."""
        return f"destroyed {target}"

    async def slow(seconds: float) -> str:
        """Report after a delay."""
        import asyncio

        await asyncio.sleep(seconds)
        return "slept"

    ctx.tools.register(shout)
    ctx.tools.register(slow)
    ctx.tools.register(danger, approval={"allowed_decisions": ["approve", "reject"]} if config.gate_danger else False)

    @ctx.on("tools/result")
    async def record(call: Any, result: Any) -> None:
        RESULTS.append((call.name, getattr(result, "content", str(result))))
