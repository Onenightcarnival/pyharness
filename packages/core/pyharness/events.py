from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

EventMode = Literal["emit", "parallel", "serial", "series", "bail", "waterfall"]
EVENT_MODES: tuple[str, ...] = ("emit", "parallel", "serial", "series", "bail", "waterfall")

log = logging.getLogger("pyharness.events")


class EventError(RuntimeError):
    """Violation of an event declaration."""


class UndeclaredEventError(EventError):
    """Dispatch of an event without a declaration."""


class EventModeError(EventError):
    """Declaration or dispatch that contradicts the declared mode."""


@dataclass
class EventDecl:
    name: str
    mode: str
    doc: str = ""
    owners: list[str] = field(default_factory=list)


@dataclass
class Listener:
    fn: Callable[..., Any]
    owner: str | None
    seq: int


class EventBus:
    def __init__(self) -> None:
        self._decls: dict[str, EventDecl] = {}
        self._listeners: dict[str, list[Listener]] = {}
        self._seq = 0
        self._tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ contract
    def define(self, name: str, mode: str, doc: str = "", owner: str | None = None) -> Callable[[], None]:
        """
        Declare ``name`` with ``mode``; returns the disposer.

        One event has one mode and any number of declaring owners.
        """
        if mode not in EVENT_MODES:
            raise EventModeError(f"unknown dispatch mode {mode!r} for event {name!r}")
        decl = self._decls.get(name)
        if decl is None:
            decl = self._decls[name] = EventDecl(name=name, mode=mode, doc=doc)
        elif decl.mode != mode:
            raise EventModeError(
                f"event {name!r} is already declared as {decl.mode!r} by {decl.owners}; cannot redeclare as {mode!r}"
            )
        elif doc and not decl.doc:
            decl.doc = doc
        token = owner or "<anonymous>"
        decl.owners.append(token)

        def dispose() -> None:
            current = self._decls.get(name)
            if current is not decl:
                return
            if token in current.owners:
                current.owners.remove(token)
            if not current.owners:
                del self._decls[name]

        return dispose

    def declaration(self, name: str) -> EventDecl | None:
        return self._decls.get(name)

    def declarations(self) -> list[EventDecl]:
        return sorted(self._decls.values(), key=lambda d: d.name)

    def listeners(self, name: str) -> list[Listener]:
        return list(self._listeners.get(name, ()))

    # ------------------------------------------------------------------ listening
    def on(
        self, name: str, fn: Callable[..., Any], *, owner: str | None = None, prepend: bool = False
    ) -> Callable[[], None]:
        self._seq += 1
        listener = Listener(fn=fn, owner=owner, seq=self._seq)
        bucket = self._listeners.setdefault(name, [])
        if prepend:
            bucket.insert(0, listener)
        else:
            bucket.append(listener)

        def dispose() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.get(name, []).remove(listener)

        return dispose

    # ------------------------------------------------------------------ dispatch
    def _check(self, name: str, mode: str) -> list[Listener]:
        decl = self._decls.get(name)
        if decl is None:
            raise UndeclaredEventError(f"undeclared event {name!r} (dispatch: {mode})")
        if decl.mode != mode:
            raise EventModeError(f"event {name!r}: declared {decl.mode!r}, dispatched {mode!r}")
        return list(self._listeners.get(name, ()))

    def emit(self, name: str, *args: Any) -> None:
        for listener in self._check(name, "emit"):
            try:
                result = listener.fn(*args)
            except Exception:
                log.exception("listener of %s (owner %s) failed", name, listener.owner)
                continue
            if inspect.isawaitable(result):
                self._spawn(result, name, listener)

    async def parallel(self, name: str, *args: Any) -> None:
        listeners = self._check(name, "parallel")
        if not listeners:
            return
        results = await asyncio.gather(*(_call(listener.fn, args) for listener in listeners), return_exceptions=True)
        for listener, result in zip(listeners, results, strict=True):
            if isinstance(result, BaseException):
                log.error("listener of %s (owner %s) failed: %r", name, listener.owner, result, exc_info=result)

    async def serial(self, name: str, *args: Any) -> Any:
        for listener in self._check(name, "serial"):
            result = await _call(listener.fn, args)
            if result is not None:
                return result
        return None

    async def series(self, name: str, *args: Any) -> None:
        """Await every listener in order. Return values are ignored; the first error propagates."""
        for listener in self._check(name, "series"):
            await _call(listener.fn, args)

    def bail(self, name: str, *args: Any) -> Any:
        for listener in self._check(name, "bail"):
            result = listener.fn(*args)
            if inspect.isawaitable(result):
                raise EventModeError(f"bail listener of {name!r} (owner {listener.owner}) must be synchronous")
            if result is not None:
                return result
        return None

    async def waterfall(self, name: str, *args: Any, final: Callable[..., Any]) -> Any:
        listeners = self._check(name, "waterfall")

        async def run(index: int, current: tuple[Any, ...]) -> Any:
            if index == len(listeners):
                return await _call(final, current)
            listener = listeners[index]

            async def next_(*replacement: Any) -> Any:
                return await run(index + 1, replacement or current)

            return await _call(listener.fn, current, {"next": next_})

        return await run(0, tuple(args))

    # ------------------------------------------------------------------ helpers
    def _spawn(self, awaitable: Awaitable[Any], name: str, listener: Listener) -> None:
        async def runner() -> None:
            try:
                await awaitable
            except Exception:
                log.exception("async listener of %s (owner %s) failed", name, listener.owner)

        try:
            task = asyncio.get_running_loop().create_task(runner())
        except RuntimeError:
            asyncio.run(runner())
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def _call(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any] | None = None) -> Any:
    result = fn(*args, **(kwargs or {}))
    if inspect.isawaitable(result):
        result = await result
    return result
