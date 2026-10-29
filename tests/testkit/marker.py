"""Supervisor tests: ``gen-<N>.json`` in ``marker_dir`` per started generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

name = "testkit-marker"


class Config(BaseModel):
    marker_dir: str


def apply(ctx: Any, config: Config) -> None:
    @ctx.on("app/started")
    def started() -> None:
        path = Path(config.marker_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"gen-{ctx.lifecycle.generation}.json").write_text(json.dumps({"handoff": ctx.lifecycle.handoff()}))
