from __future__ import annotations

import sys
import types

import pytest
from pydantic import BaseModel

from pyxis_harness import Harness, Service, ServiceConflict

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
