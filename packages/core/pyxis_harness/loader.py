from __future__ import annotations

import enum
import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

from .config import Entry, Tree, interpolate
from .context import CORE_OWNER, Context, Root, Scope, _maybe_await
from .plugin import PluginError, PluginSpec, call_apply, load_plugin

log = logging.getLogger("pyxis_harness.loader")


class EntryState(str, enum.Enum):
    PLANNED = "planned"
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class EntryRuntime:
    entry: Entry
    path: tuple[str, ...]
    scope: Scope
    state: EntryState = EntryState.PLANNED
    spec: PluginSpec | None = None
    config: Any = None
    error: str | None = None
    missing: list[str] = field(default_factory=list)
    disabled_reason: str | None = None
    ctx: Context | None = None
    started_at: float | None = None
    order: int | None = None

    def describe(self) -> dict[str, Any]:
        spec = self.spec
        data: dict[str, Any] = {
            "id": self.entry.id,
            "name": self.entry.name,
            "state": self.state.value,
            "group": list(self.path),
            "source": self.entry.source,
        }
        if spec is not None:
            data["kind"] = spec.kind
            data["inject"] = spec.inject
            if spec.service_cls is not None:
                data["provides"] = spec.service_cls.key
            if spec.dist:
                data["dist"] = spec.dist
            if spec.package_dir:
                data["package_dir"] = spec.package_dir
            if spec.docs:
                data["docs"] = spec.docs
            data["has_config_schema"] = spec.config_model is not None
        if self.entry.required:
            data["required"] = True
        if self.missing:
            data["missing"] = list(self.missing)
        if self.error:
            data["error"] = self.error
        if self.disabled_reason:
            data["disabled_reason"] = self.disabled_reason
        return data


class BootError(RuntimeError):
    """A required entry did not start."""


def down_reason(rt: EntryRuntime) -> str:
    if rt.state is EntryState.PENDING:
        return f"required entry is pending: missing service(s) {', '.join(rt.missing) or '?'}"
    return rt.error or "required entry failed"


class Loader:
    def __init__(self, root: Root, tree: Tree) -> None:
        self.root = root
        self.tree = tree
        self.runtimes: list[EntryRuntime] = []
        self._started: list[EntryRuntime] = []
        root.scope.services["loader"] = (self, CORE_OWNER)
        self._plan(tree, (), root.scope, disabled_by=None)

    # ------------------------------------------------------------------ planning
    def _plan(self, tree: Tree, path: tuple[str, ...], scope: Scope, disabled_by: str | None) -> None:
        for entry in tree:
            off = disabled_by or (entry.id if entry.disabled else None)
            if entry.children is not None:
                child_scope = Scope(scope, entry.isolate, label=entry.id) if entry.isolate else scope
                if entry.name:
                    log.warning("group %s: `name` on a group entry is ignored", entry.id)
                self._plan(entry.children, (*path, entry.id), child_scope, off)
                continue
            rt = EntryRuntime(entry=entry, path=path, scope=scope)
            if off is not None:
                rt.state = EntryState.DISABLED
                rt.disabled_reason = "disabled" if off == entry.id else f"group {off!r} is disabled"
            self.runtimes.append(rt)

    def get(self, entry_id: str) -> EntryRuntime | None:
        for rt in self.runtimes:
            if rt.entry.id == entry_id:
                return rt
        return None

    # ------------------------------------------------------------------ resolve
    def resolve(self) -> None:
        """Import each enabled plugin and validate its configuration."""
        for rt in self.runtimes:
            if rt.state is not EntryState.PLANNED:
                continue
            try:
                rt.spec = load_plugin(rt.entry.name or "")
            except PluginError as exc:
                self._fail(rt, str(exc))
                continue
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                self._fail(rt, f"{type(exc).__name__}: {exc}")
                continue
            try:
                raw = interpolate(rt.entry.config or {}, self.root.variables)
                rt.config = rt.spec.validate_config(raw)
            except Exception as exc:  # noqa: BLE001
                self._fail(rt, f"invalid config: {exc}")
                continue
            rt.state = EntryState.PENDING

    # ------------------------------------------------------------------ start / stop
    async def start(self) -> None:
        if any(rt.state is EntryState.PLANNED for rt in self.runtimes):
            self.resolve()
        while True:
            for rt in self.runtimes:
                if rt.state is not EntryState.PENDING:
                    continue
                assert rt.spec is not None
                missing = [key for key in rt.spec.inject if rt.scope.lookup(key) is None]
                rt.missing = missing
                if missing:
                    continue
                await self._start_one(rt)
                break  # rescan: configuration order decides among ready entries
            else:
                break
        for rt in self.runtimes:
            if rt.state is EntryState.PENDING:
                log.warning("%s stays PENDING: missing service(s) %s", rt.entry.id, ", ".join(rt.missing))

    async def _start_one(self, rt: EntryRuntime) -> None:
        assert rt.spec is not None
        ctx = Context(self.root, rt.scope, rt.entry, inject=rt.spec.inject)
        rt.ctx = ctx
        rt.missing = []
        spec = rt.spec
        try:
            if spec.kind == "service":
                assert spec.service_cls is not None
                svc = spec.service_cls(ctx, rt.config)
                await _maybe_await(svc.start())
                # Teardown order: withdraw service → stop() → registrations made in start().
                ctx.on_dispose(svc.stop)
                ctx.provide(spec.service_cls.key, svc)
            else:
                await _maybe_await(call_apply(spec, ctx, rt.config))
        except Exception as exc:  # noqa: BLE001
            await self._dispose(rt)
            self._fail(rt, f"{type(exc).__name__}: {exc}", exc)
            return
        rt.state = EntryState.ACTIVE
        rt.started_at = time.time()
        rt.order = len(self._started)
        self._started.append(rt)
        log.debug("started %s", rt.entry.id)

    async def stop(self) -> None:
        try:
            await self.root.events.parallel("app/stopping")
        except Exception:  # pragma: no cover
            log.exception("app/stopping listeners failed")
        for rt in reversed(self._started):
            await self._dispose(rt)
            rt.state = EntryState.STOPPED
        self._started.clear()
        await self.root.host.aclose()

    async def _dispose(self, rt: EntryRuntime) -> None:
        if rt.ctx is not None:
            await rt.ctx.aclose()

    def _fail(self, rt: EntryRuntime, message: str, exc: BaseException | None = None) -> None:
        rt.state = EntryState.FAILED
        rt.error = message
        if exc is not None and log.isEnabledFor(logging.DEBUG):
            log.debug("%s failed:\n%s", rt.entry.id, "".join(traceback.format_exception(exc)))
        log.error("%s failed: %s", rt.entry.id, message)

    # ------------------------------------------------------------------ reporting
    def down(self) -> list[EntryRuntime]:
        """Required entries that did not start: failed, or pending on a service that never appeared."""
        return [rt for rt in self.runtimes if rt.entry.required and rt.state in (EntryState.FAILED, EntryState.PENDING)]

    def snapshot(self) -> list[dict[str, Any]]:
        return [rt.describe() for rt in self.runtimes]

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rt in self.runtimes:
            counts[rt.state.value] = counts.get(rt.state.value, 0) + 1
        return counts
