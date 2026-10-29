"""Plugin: apply succeeds; app/ready fails the boot."""

from typing import Any

name = "testkit-boom"


def apply(ctx: Any) -> None:
    @ctx.on("app/ready")
    def explode() -> None:
        raise RuntimeError("boom during app/ready")
