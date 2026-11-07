"""Example third-party plugin: tool-call audit.

| extension point   | mode      | effect                                                  |
|-------------------|-----------|---------------------------------------------------------|
| ``tools/execute`` | waterfall | tools in ``deny`` return an error without running       |
| ``tools/result``  | parallel  | one JSONL line per finished call                        |
| ``app/serve``     | series    | ``GET /audit`` on ``ctx.http``, when the service exists |

``inject`` lists only ``tools``; the plugin also runs headless.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

name = "pyharness-audit"
inject = ["tools"]
BUNDLE = Path(__file__).with_name("bundle.yaml")


class Config(BaseModel):
    path: str = Field(..., description="JSONL log; one line per tool call.")
    deny: list[str] = Field(default_factory=list, description="Blocked tool names.")
    tail: int = Field(50, description="Line count of GET /audit.")


def apply(ctx: Any, config: Config) -> None:
    log_path = Path(config.path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    @ctx.on("tools/execute")
    async def deny(call: Any, next: Any) -> Any:
        if call.name in config.deny:
            return ToolMessage(
                content=f"Tool `{call.name}`: blocked by the audit denylist.",
                name=call.name,
                tool_call_id=call.id or "",
                status="error",
            )
        return await next()

    @ctx.on("tools/result")
    async def record(call: Any, result: Any) -> None:
        line = {
            "at": time.time(),
            "session": call.session_id,
            "tool": call.name,
            "owner": call.owner,
            "args": call.args,
            "status": getattr(result, "status", None),
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    @ctx.on("app/serve")
    def mount_route() -> None:
        http = ctx.get("http", None)
        if http is None:
            return
        router = APIRouter()

        @router.get("/audit")
        async def audit() -> list[dict[str, Any]]:
            if not log_path.exists():
                return []
            lines = log_path.read_text(encoding="utf-8").splitlines()[-config.tail :]
            return [json.loads(x) for x in lines if x.strip()]

        http.include_router(router)
