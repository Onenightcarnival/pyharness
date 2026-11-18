from __future__ import annotations

import pytest

from pyxis_harness.events import EventBus, EventModeError, UndeclaredEventError


async def test_modes():
    bus = EventBus()
    bus.define("e", "emit")
    bus.define("p", "parallel")
    bus.define("s", "serial")
    bus.define("b", "bail")
    bus.define("w", "waterfall")
    seen = []
    bus.on("e", lambda x: seen.append(("e", x)))
    bus.on("p", lambda x: seen.append(("p", x)))
    bus.on("s", lambda x: None)
    bus.on("s", lambda x: x * 2)
    bus.on("s", lambda x: pytest.fail("serial must stop at the first non-None result"))
    bus.on("b", lambda x: "first" if x else None)
    bus.emit("e", 1)
    await bus.parallel("p", 2)
    assert await bus.serial("s", 21) == 42
    assert bus.bail("b", True) == "first"
    assert seen == [("e", 1), ("p", 2)]

    async def outer(x, next):
        return f"<{await next(x + 1)}>"

    async def short(x, next):
        return "short" if x > 100 else await next()

    bus.on("w", outer)
    bus.on("w", short)
    assert await bus.waterfall("w", 1, final=lambda x: f"final{x}") == "<final2>"
    assert await bus.waterfall("w", 100, final=lambda x: "never") == "<short>"


async def test_contract_is_enforced():
    bus = EventBus()
    with pytest.raises(UndeclaredEventError):
        bus.emit("nope")
    bus.define("x", "serial")
    with pytest.raises(EventModeError):
        bus.emit("x")
    with pytest.raises(EventModeError):
        bus.define("x", "emit")
    dispose_a = bus.define("x", "serial", owner="a")
    dispose_a()
    assert bus.declaration("x") is not None  # declaration owner: first plugin


async def test_parallel_isolates_failures():
    bus = EventBus()
    bus.define("p", "parallel")
    hits = []

    async def bad():
        raise RuntimeError("x")

    bus.on("p", bad)
    bus.on("p", lambda: hits.append(1))
    await bus.parallel("p")
    assert hits == [1]
