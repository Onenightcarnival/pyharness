"""__TITLE__: a Web UI panel with a sidebar row, fed by a server-side call.

| extension point   | effect                                                        |
|-------------------|---------------------------------------------------------------|
| ``ctx.webui``     | serves ``client.js``; ``calls["stats"]`` answers ``ctx.host.call("stats")`` from the page |
| ``tools/result``  | counts finished tool calls per tool name; the panel shows them |
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

name = "__DIST__"
inject = ["webui"]

BUNDLE = Path(__file__).with_name("bundle.yaml")
CLIENT = Path(__file__).with_name("client.js")


class Config(BaseModel):
    greeting: str = Field("Hello from __TITLE__", description="Text the panel shows under its title.")


def apply(ctx: Any, config: Config) -> None:
    calls: Counter[str] = Counter()

    @ctx.on("tools/result")
    async def count(call: Any, result: Any) -> None:
        calls[call.name] += 1

    def stats(args: dict[str, Any]) -> dict[str, Any]:
        # Called by the page: POST /plugins/__DIST__/call/stats with a JSON object; ValueError -> HTTP 422.
        return {"greeting": config.greeting, "tool_calls": dict(calls), "locale": args.get("locale")}

    # Undone with the plugin: the module and its calls disappear when the entry stops.
    ctx.webui.register_client(CLIENT, calls={"stats": stats})
