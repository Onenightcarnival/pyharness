"""Workspace changes: git work-tree snapshots per turn, summaries, diffs; syntax highlighting routes."""

from __future__ import annotations

import json
import os
import subprocess

import httpx

from pyharness import Harness, Profile
from pyharness_workspace_changes import parse_unified

HTTP_OFF = {"id": "http", "config": {"serve": False}}


def patch(replies):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test"}},
        HTTP_OFF,
    ]


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120)


def sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def git(cwd, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


async def test_turn_changes_from_git_snapshots(home, workspace):
    ws = workspace
    (ws / "a.py").write_text("def f():\n    return 1\n")
    (ws / ".gitignore").write_text("ignored.txt\n")
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "init")
    replies = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "edit_file",
                    "args": {"file_path": "/a.py", "old_string": "return 1", "new_string": "return 2"},
                    "id": "e1",
                }
            ],
        },
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/new.txt", "content": "hello\n"}, "id": "w2"}],
        },
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/ignored.txt", "content": "x"}, "id": "w3"}],
        },
        {"content": "done"},
        {"content": "nothing to do"},
    ]
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=patch(replies)) as h, client(h) as c:
        s = (await c.post("/api/sessions", json={})).json()
        events = sse((await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "go"})).text)
        done = events[-1]
        assert done["outcome"] == "completed", done
        changes = done["extras"]["changes"]
        assert [f["display"] for f in changes["files"]] == ["a.py", "new.txt"]  # ignored.txt is gitignored
        a, new = changes["files"]
        assert (a["status"], a["added"], a["deleted"], a["binary"]) == ("M", 1, 1, False)
        assert new["status"] == "A" and (
            changes["added"],
            changes["deleted"],
            changes["total"],
            changes["seq"],
        ) == (2, 1, 2, 1)
        page = (await c.get(f"/api/sessions/{s['id']}")).json()
        assert page["changes"][0]["run_id"] == changes["run_id"] and changes["after"] == len(page["messages"])
        assert (await c.get(f"/api/sessions/{s['id']}/changes")).json()["changes"] == page["changes"]
        d = (await c.get(f"/api/sessions/{s['id']}/changes/{changes['run_id']}/diff", params={"index": 0})).json()
        assert d["available"] is True and d["status"] == "M" and len(d["hunks"]) == 1
        lines = d["hunks"][0]["lines"]
        assert [ln["kind"] for ln in lines] == ["ctx", "del", "add"]
        assert (
            lines[1]["text"] == "    return 1"
            and lines[2]["text"] == "    return 2"
            and lines[1]["old"] == 2
            and lines[2]["new"] == 2
        )
        assert 'class="hl-k"' in lines[2]["html"] and 'class="hl-k"' in lines[1]["html"]
        d = (await c.get(f"/api/sessions/{s['id']}/changes/{changes['run_id']}/diff", params={"index": 1})).json()
        assert d["status"] == "A" and [ln["kind"] for ln in d["hunks"][0]["lines"]] == ["add"]
        assert (
            await c.get(f"/api/sessions/{s['id']}/changes/{changes['run_id']}/diff", params={"index": 5})
        ).status_code == 404
        assert (await c.get(f"/api/sessions/{s['id']}/changes/nope/diff")).status_code == 404
        # A turn that changes nothing records no summary.
        events = sse((await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "again"})).text)
        assert events[-1]["outcome"] == "completed" and "changes" not in events[-1]["extras"]
        assert len((await c.get(f"/api/sessions/{s['id']}/changes")).json()["changes"]) == 1
    # The repository itself was never touched: nothing staged, the edits are plain work-tree changes.
    status = git(ws, "status", "--porcelain")
    assert " M a.py" in status and "?? new.txt" in status and "A " not in status
    assert "pyh-changes" not in git(ws, "count-objects", "-v")


async def test_non_git_workspace_records_nothing(home, workspace):
    plain = workspace
    replies = [
        {
            "content": "",
            "tool_calls": [{"name": "write_file", "args": {"file_path": "/x.txt", "content": "x"}, "id": "w1"}],
        },
        {"content": "ok"},
    ]
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=patch(replies)) as h, client(h) as c:
        s = (await c.post("/api/sessions", json={})).json()
        events = sse((await c.post(f"/api/sessions/{s['id']}/messages", json={"content": "go"})).text)
        assert events[-1]["outcome"] == "completed" and "changes" not in events[-1]["extras"]
        turn = events[-1]["extras"]["turn"]
        assert (
            turn["stats"]["steps"] == 2
            and turn["stats"]["tool_calls"] == 1
            and [r["t"] for r in turn["records"]] == ["user", "step", "tool", "step", "end"]
        )
        assert (
            turn["records"][2]["name"] == "write_file"
            and turn["records"][2]["status"] == "success"
            and turn["records"][2]["dur_ms"] >= 0
        )
        assert (await c.get(f"/api/sessions/{s['id']}/turns")).json()["turns"][0]["seq"] == 1
        assert (await c.get(f"/api/sessions/{s['id']}")).json()["turns"][0]["after"] == 4
        assert (await c.get(f"/api/sessions/{s['id']}")).json()["changes"] == []
        assert (plain / "x.txt").read_text() == "x"


async def test_highlight_routes(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        r = await c.post(
            "/api/highlight",
            json={
                "items": [
                    {"code": "def f():\n    return 1", "lang": "python"},
                    {"code": "x", "lang": "nope"},
                    {"code": "a = 1", "filename": "x.toml"},
                    {"code": "plain", "lang": "text"},
                ]
            },
        )
        items = r.json()["items"]
        assert (
            'class="hl-k">def</span>' in items[0]["html"]
            and items[0]["lang"] == "python"
            and items[0]["html"].count("\n") == 1
        )
        assert items[1]["html"] == "" and items[3]["html"] == ""
        assert "hl-" in items[2]["html"]
        css = await c.get("/api/highlight.css")
        assert (
            css.headers["content-type"].startswith("text/css")
            and ".hl .hl-k" in css.text
            and '[data-theme="dark"] .hl .hl-k' in css.text
        )
        assert "background" not in css.text.split("\n")[0]


def test_parse_unified():
    text = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n\\ No newline at end of file\n"
    (hunk,) = parse_unified(text)
    assert (hunk["old_start"], hunk["new_start"]) == (1, 1)
    assert [(ln["kind"], ln["old"], ln["new"], ln["text"]) for ln in hunk["lines"]] == [
        ("ctx", 1, 1, "a"),
        ("del", 2, None, "b"),
        ("add", None, 2, "B"),
        ("ctx", 3, 3, "c"),
    ]
    assert hunk["lines"][-1]["no_newline"] is True
    assert parse_unified("") == []
