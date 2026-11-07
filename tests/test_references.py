"""@path references: expansion into attachment blocks, workspace search, the message route."""

from __future__ import annotations

from textwrap import dedent

import httpx

from pyharness import Harness, Profile
from pyharness_api.references import expand, search, strip_attachments, tokens
from pyharness_workspace import Workspace
from test_agent import scripted_patch, sse_events
from testkit import scripted


def test_tokens_and_expand(tmp_path):
    (tmp_path / "README.md").write_text("# Hello\nbody\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a b.py").write_text("print(1)\n")
    (tmp_path / "src" / "img.png").write_bytes(b"\x89PNG\x00\x00binary")
    ws = Workspace(tmp_path.resolve(), True)
    assert tokens('see @README.md and @"src/a b.py", mail me@example.com @src/ @nope.txt.') == [
        ("@README.md", "README.md"),
        ('@"src/a b.py"', "src/a b.py"),
        ("@src/", "src/"),
        ("@nope.txt.", "nope.txt"),
    ]
    content, refs = expand('see @README.md and @"src/a b.py" plus @src/ and @nope.txt and @src/img.png', ws)
    assert [r["path"] for r in refs] == ["/README.md", "/src/a b.py", "/src", "/src/img.png"]
    assert content.startswith(
        dedent(
            """
            see @README.md and @"src/a b.py" plus @src/ and @nope.txt and @src/img.png

            <attached-file path="/README.md">
            # Hello
            """
        ).strip()
    )
    assert '<attached-directory path="/src">\na b.py\nimg.png\n</attached-directory>' in content
    assert '<attached-file path="/src/img.png" binary="true"' in content
    assert strip_attachments(content) == 'see @README.md and @"src/a b.py" plus @src/ and @nope.txt and @src/img.png'
    assert expand("nothing here @unknown", ws) == ("nothing here @unknown", [])
    found = search(tmp_path, "read")
    assert found[0]["path"] == "/README.md"
    assert [e["path"] for e in search(tmp_path, "ab")] == ["/src/a b.py"]  # subsequence
    assert {e["path"] for e in search(tmp_path, "")} >= {"/README.md", "/src/"}


async def test_message_route_expands_references(home, tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "notes.md").write_text("remember the milk\n")
    profile = Profile.init("web", home=str(home))
    scripted.CALLS.clear()
    async with (
        Harness(profile, patch=scripted_patch([{"content": "noted"}])) as h,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=60) as c,
    ):
        found = (await c.get("/api/workspaces/search", params={"q": "note"})).json()["entries"]
        assert found and found[0]["path"] == "/notes.md"
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        events = sse_events(
            (await c.post(f"/api/sessions/{sid}/messages", json={"content": "summarize @notes.md"})).text
        )
        assert events[-1]["outcome"] == "completed"
        refs_event = next(e for e in events if e["type"] == "references")
        assert refs_event["refs"] == [
            {"token": "@notes.md", "path": "/notes.md", "kind": "file", "chars": 18, "truncated": False}
        ]
        human = next(m for call in scripted.CALLS if "messages" in call for m in call["messages"] if m[0] == "human")
        assert human[1].startswith('summarize @notes.md\n\n<attached-file path="/notes.md">\nremember the milk')
        turn = events[-1]["extras"]["turn"]
        assert turn["records"][0]["preview"] == "summarize @notes.md"
        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert "<attached-file" in detail["messages"][0]["content"]
