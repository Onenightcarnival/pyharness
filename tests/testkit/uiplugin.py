"""Test plugin: a Web UI client module with one call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

name = "testkit.uiplugin"
inject = ["webui"]

CLIENT = Path(__file__).with_name("uiplugin_client.js")


class Config(BaseModel):
    greeting: str = "hi"


def apply(ctx: Any, config: Config) -> None:
    def stats(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("fail"):
            raise ValueError("asked to fail")
        return {"greeting": config.greeting, "echo": args.get("echo")}

    async def slow(args: dict[str, Any]) -> str:
        return "async ok"

    ctx.webui.register_client(CLIENT, calls={"stats": stats, "slow": slow})
