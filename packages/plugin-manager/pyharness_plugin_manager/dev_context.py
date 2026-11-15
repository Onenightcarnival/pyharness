from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import pyharness
from pyharness import package_prompts

PROMPTS = package_prompts(__file__)

name = "pyharness-dev-context"
doc = "Prompt section ``dev-context``: where this harness runs."
inject = ["prompt"]

GUIDANCE: str = PROMPTS["dev_context"]["GUIDANCE"]


class Config(BaseModel):
    order: int = Field(60, description="Prompt section order.")


def _values(ctx: Any) -> list[str]:
    rows = [f"- installation: {Path(pyharness.__file__).resolve().parent}"]
    profile = ctx.get("profile", None)
    if profile is not None:
        rows.append(f"- profile: `{profile.name}` at {profile.dir}")
    workspace = ctx.get("workspace", None)
    if workspace is not None and getattr(workspace, "root", None) is not None:
        rows.append(f"- default workspace: {workspace.root} (file tools address the session workspace as `/`)")
    http = ctx.get("http", None)
    config = getattr(http, "config", None)
    if config is not None and getattr(config, "serve", True):
        rows.append(f"- Web UI: http://{config.host}:{config.port}/ ; API: http://{config.host}:{config.port}/api")
    return rows


def apply(ctx: Any, config: Config) -> None:
    ctx.prompt.add("dev-context", lambda: GUIDANCE + "\n" + "\n".join(_values(ctx)), order=config.order)
