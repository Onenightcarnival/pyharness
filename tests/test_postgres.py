"""
Persistence on Postgres through one entry patch; history across generations.

Requires ``PYH_TEST_POSTGRES_DSN`` (writable database):
``PYH_TEST_POSTGRES_DSN=postgresql://user@127.0.0.1:5432/pyh_test``.
"""

from __future__ import annotations

import os
import uuid

import pytest

from pyharness import Harness, Profile

DSN = os.environ.get("PYH_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PYH_TEST_POSTGRES_DSN unset")


async def test_postgres_provider_replaces_sqlite(home):
    profile = Profile.init("web", home=str(home))
    title = f"pg-{uuid.uuid4().hex[:8]}"

    def patch(replies):
        return [
            {"id": "checkpoint", "name": "pyxis-harness-checkpoint-postgres", "config": {"dsn": DSN}},
            {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
            {"id": "llm", "config": {"default": "scripted:test"}},
            {"id": "http", "config": {"serve": False}},
        ]

    async with Harness(profile, patch=patch([{"content": "stored in postgres"}])) as h:
        assert h.loader.get("checkpoint").spec.name == "pyxis-harness-checkpoint-postgres"
        agents = h.get("agents")
        session = await agents.create_session(title=title)
        await agents.start_run(session["id"], "hello").wait()

    assert not (profile.data / "checkpoints.sqlite").exists()

    async with Harness(profile, patch=patch([]), generation=2) as h2:
        agents = h2.get("agents")
        assert title in [s["title"] for s in await agents.list_sessions(limit=1000)]
        messages = await agents.messages(session["id"])
        assert [m["content"] for m in messages] == ["hello", "stored in postgres"]
