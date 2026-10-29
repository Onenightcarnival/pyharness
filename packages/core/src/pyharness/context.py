"""Context: the service container each plugin receives.

| concept      | contract                                                                          |
|--------------|-----------------------------------------------------------------------------------|
| service      | object under a stable key (``ctx.tools``); consumers look it up by key            |
| registration | ``provide``, ``on``, ``effect``, ``enter``, ``on_dispose``; owned by the plugin   |
| teardown     | the plugin's registrations are undone in reverse order                            |
| caller       | inside a :class:`Service` method, ``self.caller`` is the calling plugin's context |
"""

from __future__ import annotations

import inspect
import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Iterable

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover
    from .events import EventBus
    from .loader import EntryRuntime, Root

Disposer = Callable[[], Any]

_MISSING: Any = object()
_caller: ContextVar["Context | None"] = ContextVar("pyharness_caller", default=None)


class ServiceError(RuntimeError):
    """Service lookup or registration failure."""


class ServiceNotFound(ServiceError, LookupError):
    """No service under the key is visible from the scope."""


class ServiceConflict(ServiceError):
    """The key is already provided in the target scope."""


class Scope:
    """Service namespace. A group with ``isolate`` has its own scope for the listed keys."""

    def __init__(self, parent: "Scope | None" = None, isolate: Iterable[str] = (), label: str = "root") -> None:
        self.parent = parent
        self.isolate = set(isolate)
        self.label = label
        self.services: dict[str, tuple[Any, str]] = {}

    def owner_scope(self, key: str) -> "Scope":
        scope = self
        while scope.parent is not None and key not in scope.isolate:
            scope = scope.parent
        return scope

    def lookup(self, key: str) -> tuple[Any, str] | None:
        scope: Scope | None = self
        while scope is not None:
            if key in scope.services:
                return scope.services[key]
            if key in scope.isolate:
                return None  # an isolated key never resolves to an outer provider
            scope = scope.parent
        return None

    def all_services(self) -> dict[str, tuple[Any, str, str]]:
        """Services visible from this scope: ``key -> (value, owner, scope label)``."""
        seen: dict[str, tuple[Any, str, str]] = {}
        blocked: set[str] = set()
        scope: Scope | None = self
        while scope is not None:
            for key, (value, owner) in scope.services.items():
                if key not in seen and key not in blocked:
                    seen[key] = (value, owner, scope.label)
            blocked |= scope.isolate
            scope = scope.parent
        return seen


class Context:
    """Per-plugin view of the harness. Unknown attributes resolve to services (``ctx.tools``)."""

    def __init__(self, root: "Root", runtime: "EntryRuntime | None", scope: Scope) -> None:
        self._root = root
        self._runtime = runtime
        self._scope = scope
        self._host_disposers: list[Disposer] = []
        name = runtime.entry.id if runtime else "<host>"
        self.logger = logging.getLogger(f"pyharness.plugin.{name}")

    # ------------------------------------------------------------------ identity
    @property
    def entry_id(self) -> str:
        return self._runtime.entry.id if self._runtime else "<host>"

    @property
    def plugin_name(self) -> str:
        if self._runtime is None:
            return "<host>"
        return self._runtime.entry.name or self._runtime.entry.id

    @property
    def root(self) -> "Root":
        return self._root

    @property
    def events(self) -> "EventBus":
        return self._root.events

    @property
    def scope(self) -> Scope:
        return self._scope

    # ------------------------------------------------------------------ services
    def provide(self, key: str, value: Any) -> Disposer:
        target = self._scope.owner_scope(key)
        if key in target.services:
            owner = target.services[key][1]
            raise ServiceConflict(f"service {key!r} is already provided by {owner!r} in scope {target.label!r}")
        target.services[key] = (value, self.entry_id)

        def dispose() -> None:
            current = target.services.get(key)
            if current is not None and current[0] is value:
                del target.services[key]

        return self.on_dispose(dispose)

    def get(self, key: str, default: Any = _MISSING, *, bind: bool = True) -> Any:
        hit = self._scope.lookup(key)
        if hit is None:
            if default is _MISSING:
                raise ServiceNotFound(
                    f"service {key!r} is not available to {self.entry_id!r} (add it to `inject`, or check that its provider is active)"
                )
            return default
        value = hit[0]
        if bind and isinstance(value, Service):
            return _Bound(value, self)
        return value

    def has(self, key: str) -> bool:
        return self._scope.lookup(key) is not None

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self.get(key)
        except ServiceNotFound as exc:
            raise AttributeError(str(exc)) from None

    # ------------------------------------------------------------------ events
    def define_event(self, name: str, mode: str, doc: str = "") -> Disposer:
        return self.on_dispose(self._root.events.define(name, mode, doc, owner=self.entry_id))

    def on(self, name: str, fn: Callable[..., Any] | None = None, *, prepend: bool = False) -> Any:
        """Register a listener; also a decorator (``@ctx.on("tools/result")``)."""

        def register(listener: Callable[..., Any]) -> Callable[..., Any]:
            self.on_dispose(self._root.events.on(name, listener, owner=self.entry_id, prepend=prepend))
            return listener

        if fn is None:
            return register
        register(fn)
        return fn

    def emit(self, name: str, *args: Any) -> None:
        self._root.events.emit(name, *args)

    async def parallel(self, name: str, *args: Any) -> None:
        await self._root.events.parallel(name, *args)

    async def serial(self, name: str, *args: Any) -> Any:
        return await self._root.events.serial(name, *args)

    async def series(self, name: str, *args: Any) -> None:
        await self._root.events.series(name, *args)

    def bail(self, name: str, *args: Any) -> Any:
        return self._root.events.bail(name, *args)

    async def waterfall(self, name: str, *args: Any, final: Callable[..., Any]) -> Any:
        return await self._root.events.waterfall(name, *args, final=final)

    # ------------------------------------------------------------------ effects
    def on_dispose(self, fn: Callable[[], Any]) -> Disposer:
        """Register a sync or async disposer; it runs when this plugin stops."""
        bucket = self._runtime.disposers if self._runtime is not None else self._host_disposers
        bucket.append(fn)

        def dispose() -> Any:
            try:
                bucket.remove(fn)
            except ValueError:
                return None
            return fn()

        return dispose

    def effect(self, setup: Callable[[], Any]) -> Disposer:
        """Run ``setup()``; a callable it returns is the disposer."""
        result = setup()
        if inspect.isawaitable(result):
            raise TypeError("ctx.effect(): synchronous setup only; async resources: `await ctx.enter(...)`")
        if callable(result):
            return self.on_dispose(result)
        return lambda: None

    async def enter(self, cm: Any) -> Any:
        """Enter a sync or async context manager; it exits when this plugin stops."""
        if hasattr(cm, "__aenter__"):
            value = await cm.__aenter__()
            self.on_dispose(lambda: cm.__aexit__(None, None, None))
            return value
        if hasattr(cm, "__enter__"):
            value = cm.__enter__()
            self.on_dispose(lambda: cm.__exit__(None, None, None))
            return value
        raise TypeError(f"{cm!r} is not a context manager")

    async def aclose_host(self) -> None:
        """Dispose registrations made through the host context. Disposer errors are logged."""
        while self._host_disposers:
            try:
                await _maybe_await(self._host_disposers.pop()())
            except Exception:
                self.logger.exception("host disposer failed")

    def __repr__(self) -> str:
        return f"<Context {self.entry_id}>"


class Service:
    """Plugin that provides one service under ``key``.

    | phase    | loader action                                                |
    |----------|--------------------------------------------------------------|
    | start    | ``cls(ctx, config)`` → ``await start()`` → provide           |
    | teardown | withdraw → ``await stop()`` → undo ``start()`` registrations |
    """

    key: ClassVar[str]
    name: ClassVar[str | None] = None
    inject: ClassVar[list[str]] = []
    Config: ClassVar[type[BaseModel] | None] = None

    def __init__(self, ctx: Context, config: Any = None) -> None:
        self.ctx = ctx
        self.config = config

    async def start(self) -> None:  # pragma: no cover
        return None

    async def stop(self) -> None:  # pragma: no cover
        return None

    @property
    def caller(self) -> Context:
        """Context of the calling plugin; the owner's context outside a bound call."""
        return _caller.get() or self.ctx


class _Bound:
    """Proxy that ``ctx.get()`` returns for a :class:`Service`; binds ``Service.caller``."""

    __slots__ = ("_svc", "_ctx")

    def __init__(self, svc: Service, ctx: Context) -> None:
        object.__setattr__(self, "_svc", svc)
        object.__setattr__(self, "_ctx", ctx)

    @property
    def unwrapped(self) -> Service:
        return self._svc

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._svc, name)
        if name.startswith("_") or not callable(attr) or inspect.isclass(attr):
            return attr
        ctx = self._ctx
        if inspect.iscoroutinefunction(attr):

            async def acall(*args: Any, **kwargs: Any) -> Any:
                token = _caller.set(ctx)
                try:
                    return await attr(*args, **kwargs)
                finally:
                    _caller.reset(token)

            return acall

        def call(*args: Any, **kwargs: Any) -> Any:
            token = _caller.set(ctx)
            try:
                return attr(*args, **kwargs)
            finally:
                _caller.reset(token)

        return call

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._svc, name, value)

    def __repr__(self) -> str:
        return f"<bound {self._svc!r} for {self._ctx.entry_id}>"


def unwrap(value: Any) -> Any:
    return value.unwrapped if isinstance(value, _Bound) else value


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "Context",
    "Disposer",
    "Scope",
    "Service",
    "ServiceConflict",
    "ServiceError",
    "ServiceNotFound",
    "unwrap",
]

