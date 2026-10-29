"""In-process harness: compose, start, ready, stop.

| user                | phases run                                             |
|---------------------|--------------------------------------------------------|
| worker              | start → ready → serve → started → stop                 |
| preflight           | start → ready → stop                                   |
| ``pyh exec``, tests | ``async with``: start → ready → serve → started → stop |

::

    async with Harness(Profile("web")) as h:
        agents = h.get("agents")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from .config import Tree, compose, parse_ops
from .lifecycle import Lifecycle
from .loader import EntryState, Loader, Root
from .profile import Profile


class Harness:
    def __init__(
        self,
        profile: Profile | None = None,
        *,
        tree: Tree | None = None,
        patch: list[dict[str, Any]] | None = None,
        extra_patches: Iterable[str | os.PathLike[str]] = (),
        generation: int = 1,
        supervised: bool = False,
        preflight: bool = False,
        variables: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.profile = profile
        self.warnings: list[str] = []
        if tree is None:
            layers = []
            if profile is not None:
                profile.activate_site()
                layers, _ = profile.layers([Path(p) for p in extra_patches])
            if patch:
                layers.append(("inline-patch", parse_ops(patch, "inline-patch")))
            tree, self.warnings = compose(layers)
        vars_: dict[str, str] = {}
        if profile is not None:
            vars_.update(profile.variables(cwd))
        else:
            vars_.update({"cwd": cwd or os.getcwd()})
        vars_.update(variables or {})
        lifecycle = Lifecycle(
            profile.runtime if profile is not None else None,
            generation,
            supervised=supervised,
            preflight=preflight,
        )
        self.root = Root(lifecycle, vars_, profile)
        self.loader = Loader(self.root, tree)
        self.tree = tree

    # ------------------------------------------------------------------ access
    @property
    def ctx(self):
        return self.root.host

    @property
    def lifecycle(self) -> Lifecycle:
        return self.root.lifecycle

    def get(self, key: str, default: Any = ...) -> Any:
        if default is ...:
            return self.root.host.get(key)
        return self.root.host.get(key, default)

    # ------------------------------------------------------------------ phases
    async def start(self) -> None:
        self.loader.resolve()
        await self.loader.start()

    async def ready(self, *, serve: bool = True) -> None:
        await self.root.events.series("app/ready")
        if serve:
            await self.root.events.series("app/serve")

    async def started(self) -> None:
        """Dispatch ``app/started``."""
        await self.root.events.parallel("app/started")

    async def stop(self) -> None:
        await self.loader.stop()

    async def __aenter__(self) -> "Harness":
        await self.start()
        try:
            await self.ready()
        except BaseException:
            await self.stop()
            raise
        await self.started()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    # ------------------------------------------------------------------ reporting
    def failed(self) -> list[dict[str, Any]]:
        return [rt.describe() for rt in self.loader.runtimes if rt.state is EntryState.FAILED]

    def report(self) -> dict[str, Any]:
        return {
            "generation": self.lifecycle.generation,
            "summary": self.loader.summary(),
            "entries": self.loader.snapshot(),
            "warnings": list(self.warnings),
        }
