from __future__ import annotations

import sys
import types

import pytest
from pydantic import BaseModel

from pyxis_harness import BootError, Harness, Service, ServiceConflict

ORDER: list[str] = []


def _module(module_name: str, **attrs):
    mod = types.ModuleType(module_name)
    mod.__dict__.update(attrs)
    sys.modules[module_name] = mod
    return mod


class Counter(Service):
    key = "counter"

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.items: dict[str, str] = {}

    async def start(self):
        ORDER.append("counter:start")

    async def stop(self):
        ORDER.append("counter:stop")

    def add(self, item: str):
        owner = self.caller.entry_id
        self.items[item] = owner
        return self.caller.on_dispose(lambda: self.items.pop(item, None))


class ConsumerConfig(BaseModel):
    item: str


def consumer_apply(ctx, config: ConsumerConfig):
    ORDER.append(f"consumer:{config.item}")
    ctx.counter.add(config.item)
    ctx.on_dispose(lambda: ORDER.append(f"consumer:{config.item}:stop"))


def broken_apply(ctx):
    ctx.counter.add("half-registered")
    raise RuntimeError("nope")


_module("lt_counter", Counter=Counter)
_module("lt_consumer", name="consumer", inject=["counter"], Config=ConsumerConfig, apply=consumer_apply)
_module("lt_broken", inject=["counter"], apply=broken_apply)
_module("lt_waiting", inject=["missing-service"], apply=lambda ctx: ORDER.append("waiting"))
_module("lt_dup", apply=lambda ctx: ctx.provide("counter", object()))


async def test_dependency_order_pending_failure_and_teardown():
    ORDER.clear()
    patch = [
        {"id": "consumer-a", "name": "lt_consumer", "config": {"item": "a"}},
        {"id": "waiting", "name": "lt_waiting"},
        {"id": "broken", "name": "lt_broken"},
        {"id": "counter", "name": "lt_counter:Counter"},
        {"id": "consumer-b", "name": "lt_consumer", "config": {"item": "b"}},
        {"id": "off", "name": "lt_consumer", "disabled": True, "config": {"item": "off"}},
        {"id": "bad-config", "name": "lt_consumer", "config": {}},
    ]
    h = Harness(patch=patch)
    await h.start()
    states = {e["id"]: e["state"] for e in h.loader.snapshot()}
    assert states == {
        "consumer-a": "active",
        "waiting": "pending",
        "broken": "failed",
        "counter": "active",
        "consumer-b": "active",
        "off": "disabled",
        "bad-config": "failed",
    }
    # Start order: provider first (listed later); consumers in config order.
    assert ORDER[:3] == ["counter:start", "consumer:a", "consumer:b"]
    counter = h.get("counter")
    assert counter.unwrapped.items == {"a": "consumer-a", "b": "consumer-b"}  # failed plugin's registration undone
    await h.stop()
    assert ORDER[3:] == ["consumer:b:stop", "consumer:a:stop", "counter:stop"]
    assert counter.unwrapped.items == {}


async def test_isolate_groups_get_their_own_instance():
    patch = [
        {"id": "counter", "name": "lt_counter:Counter"},
        {
            "id": "group",
            "isolate": ["counter"],
            "children": [
                {"id": "inner-counter", "name": "lt_counter:Counter"},
                {"id": "inner-consumer", "name": "lt_consumer", "config": {"item": "inner"}},
            ],
        },
        {"id": "outer-consumer", "name": "lt_consumer", "config": {"item": "outer"}},
    ]
    h = Harness(patch=patch)
    await h.start()
    outer = h.get("counter").unwrapped
    inner = h.loader.get("inner-consumer").ctx.get("counter").unwrapped
    assert outer is not inner
    assert outer.items == {"outer": "outer-consumer"}
    assert inner.items == {"inner": "inner-consumer"}
    await h.stop()


async def test_isolated_group_without_provider_stays_pending():
    patch = [
        {"id": "counter", "name": "lt_counter:Counter"},
        {
            "id": "group",
            "isolate": ["counter"],
            "children": [{"id": "c", "name": "lt_consumer", "config": {"item": "x"}}],
        },
    ]
    h = Harness(patch=patch)
    await h.start()
    assert h.loader.get("c").state.value == "pending"
    await h.stop()


async def test_service_conflict():
    h = Harness(patch=[{"id": "counter", "name": "lt_counter:Counter"}, {"id": "dup", "name": "lt_dup"}])
    await h.start()
    rt = h.loader.get("dup")
    assert rt.state.value == "failed" and "already provided" in rt.error
    await h.stop()
    with pytest.raises(ServiceConflict):
        h2 = Harness(patch=[])
        h2.ctx.provide("loader", object())


class Roster(Service):
    """Service whose methods report the calling plugin, whatever kind of method they are."""

    key = "roster"

    def who(self) -> str:
        return self.caller.entry_id

    async def awho(self) -> str:
        return self.caller.entry_id

    async def stream(self):
        yield self.caller.entry_id
        yield self.caller.entry_id

    def walk(self):
        yield self.caller.entry_id

    def later(self):
        async def run() -> str:
            return self.caller.entry_id

        return run()


SEEN: dict[str, object] = {}


async def reader_apply(ctx):
    roster = ctx.roster
    SEEN["plain"] = roster.who()
    SEEN["coroutine"] = await roster.awho()
    SEEN["async generator"] = [who async for who in roster.stream()]
    SEEN["generator"] = list(roster.walk())
    SEEN["returned coroutine"] = await roster.later()
    SEEN["owner outside a call"] = roster.unwrapped.caller.entry_id
    with pytest.raises(AttributeError, match="not in the `inject` of 'reader'"):
        _ = ctx.counter
    SEEN["optional read"] = ctx.get("counter", None) is not None
    SEEN["core services"] = ctx.lifecycle is not None and ctx.loader is not None


def listener_apply(ctx):
    calls: list[str] = []
    ctx.define_event("lt/ping", "emit")
    stop = ctx.on("lt/ping", lambda: calls.append("first"))

    @ctx.on("lt/ping")
    def second() -> None:
        calls.append("second")

    ctx.emit("lt/ping")
    stop()
    stop()  # a second call does nothing
    ctx.emit("lt/ping")
    SEEN["listeners"] = (calls, second.__name__)


_module("lt_roster", Roster=Roster)
_module("lt_reader", inject=["roster"], apply=reader_apply)
_module("lt_listener", apply=listener_apply)


async def test_services_are_read_through_inject_and_methods_run_as_the_caller():
    SEEN.clear()
    patch = [
        {"id": "counter", "name": "lt_counter:Counter"},
        {"id": "roster", "name": "lt_roster:Roster"},
        {"id": "reader", "name": "lt_reader"},
    ]
    async with Harness(patch=patch) as h:
        assert h.loader.get("reader").state.value == "active", h.loader.get("reader").error
        assert h.ctx.counter is not None  # the host context reads every service
    assert SEEN == {
        "plain": "reader",
        "coroutine": "reader",
        "async generator": ["reader", "reader"],
        "generator": ["reader"],
        "returned coroutine": "reader",
        "owner outside a call": "roster",
        "optional read": True,
        "core services": True,
    }


async def test_on_returns_the_disposer_of_the_listener():
    SEEN.clear()
    async with Harness(patch=[{"id": "listener", "name": "lt_listener"}]):
        pass
    assert SEEN["listeners"] == (["first", "second", "second"], "second")


class Front(Service):
    key = "front"
    inject = ["counter"]  # noqa: RUF012


class Failing(Service):
    key = "counter"

    async def start(self):
        raise RuntimeError("no such port")


_module("lt_failing", Failing=Failing)
_module("lt_front", Front=Front)
_module("lt_page", inject=["front"], apply=lambda ctx: None)


async def test_a_required_entry_that_is_down_fails_the_boot():
    page = {"id": "page", "name": "lt_page", "required": True}
    front = {"id": "front", "name": "lt_front:Front"}
    # The provider two steps away failed: the required entry waits on a service that never appears.
    with pytest.raises(BootError, match=r"page: required entry is pending: missing service\(s\) front"):
        async with Harness(patch=[{"id": "counter", "name": "lt_failing:Failing"}, front, page]):
            pass
    # The required entry itself failed.
    broken = {"id": "broken", "name": "lt_broken", "required": True}
    with pytest.raises(BootError, match="broken: RuntimeError: nope"):
        async with Harness(patch=[{"id": "counter", "name": "lt_counter:Counter"}, broken]):
            pass
    assert ORDER[-1] == "counter:stop"  # what had started is torn down
    # The provider's plugin does not import: its key is unknown, the entry is down all the same.
    with pytest.raises(BootError, match="page: required entry is pending"):
        async with Harness(patch=[{"id": "counter", "name": "lt_no_such_plugin"}, front, page]):
            pass
    # A partial composition (a headless run switches entries off on purpose) leaves the entry pending.
    off = {"id": "counter", "name": "lt_counter:Counter", "disabled": True}
    with pytest.raises(BootError):
        async with Harness(patch=[off, front, page]):
            pass
    async with Harness(patch=[off, front, page], partial=True) as h:
        assert h.loader.get("page").state.value == "pending"
    # Preflight reports the entry instead of raising.
    h = Harness(patch=[{"id": "counter", "name": "lt_failing:Failing"}, front, page], preflight=True)
    await h.start()
    assert [rt.entry.id for rt in h.loader.down()] == ["page"]
    await h.stop()
    # A patch can lift the requirement.
    lifted = [{"id": "counter", "name": "lt_failing:Failing"}, front, page, {"id": "page", "required": False}]
    async with Harness(patch=lifted) as h:
        assert h.loader.get("page").state.value == "pending"
