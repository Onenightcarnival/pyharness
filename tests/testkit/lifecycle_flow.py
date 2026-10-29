"""Supervisor test driver: restart into a broken configuration, then rollback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

name = "testkit-flow"
inject: list[str] = []


class Config(BaseModel):
    marker_dir: str


def apply(ctx: Any, config: Config) -> None:
    markers = Path(config.marker_dir)
    markers.mkdir(parents=True, exist_ok=True)
    lifecycle = ctx.lifecycle
    profile = ctx.profile

    @ctx.on("app/started")
    def started() -> None:
        state = lifecycle.handoff()
        (markers / f"gen-{lifecycle.generation}.json").write_text(json.dumps({"state": state}), encoding="utf-8")
        if lifecycle.generation == 1:
            ops = profile.patch_ops_raw()
            ops.append({"id": "boom", "name": "testkit.boom"})
            profile.save_patch(ops)
            lifecycle.request_restart("install a broken plugin", resume=["s-1"])
        else:
            lifecycle.stop(0)
