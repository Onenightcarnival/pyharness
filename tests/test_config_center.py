"""
Configuration center: skills store and routes, the MCP page routes (test, timeout, credentials), the managed bun
runtime.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from pyharness import Harness, Profile
from pyharness_config_center import ConfigCenterService
from pyharness_config_center.environment import BunManager
from pyharness_config_center.skills import SkillError, SkillStore
from pyharness_mcp import ServerConfig, connection_of

HTTP_OFF = {"id": "http", "config": {"serve": False}}
MCP_SERVER = Path(__file__).with_name("testkit") / "mcp_server.py"
SKILL = '---\nname: {name}\ndescription: {desc}\nmetadata:\n  version: "1.0"\n---\n# {name}\n\nDo the thing.\n'


def make_zip(files: dict[str, bytes], modes: dict[str, int] | None = None) -> bytes:
    """A ZIP of ``files``; ``modes`` are Unix modes recorded for entries; a name ending in ``/`` is a directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (modes or {}).get(name, 0o755 if name.endswith("/") else 0o644) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def test_skill_store(tmp_path):
    store = SkillStore(tmp_path)
    assert store.list() == []
    # Plain extraction: two bundles, a top-level markdown file, an entry without SKILL.md, macOS resource forks.
    bundle = make_zip(
        {
            "web-research/SKILL.md": SKILL.format(name="web-research", desc="Research the web").encode(),
            "web-research/helper.py": b"#!/usr/bin/env python\nprint(1)\n",
            "web-research/bin/run.sh": b"echo hi\n",
            "web-research/empty/": b"",
            "Data Clean/SKILL.md": SKILL.format(name="data-clean", desc="Clean data").encode(),
            "notes.md": b"# Notes\n\nFirst line of body.\n",
            "README.txt": b"kept as it is",
            "__MACOSX/web-research/._SKILL.md": b"fork",
        },
        modes={"web-research/bin/run.sh": 0o755},
    )
    r = store.install_zip(bundle)
    assert r == {"installed": ["web-research", "Data Clean", "notes", "README.txt"], "skipped": [], "conflicts": []}
    # The list shows the directories that hold a SKILL.md; names stay as the archive wrote them.
    assert [s["name"] for s in store.list()] == ["Data Clean", "notes", "web-research"]
    assert (store.enabled_dir / "README.txt").read_bytes() == b"kept as it is"
    assert (store.enabled_dir / "web-research" / "empty").is_dir() and not (store.enabled_dir / "__MACOSX").exists()
    notes = next(s for s in store.list() if s["name"] == "notes")
    assert notes["description"] == "First line of body." and notes["enabled"] is True
    # The executable bit follows the archive's mode, not a shebang in the file.
    assert os.access(store.enabled_dir / "web-research" / "bin" / "run.sh", os.X_OK)
    assert not os.access(store.enabled_dir / "web-research" / "helper.py", os.X_OK)
    d = store.detail("web-research")
    assert (
        d["version"] == "1.0"
        and d["enabled"]
        and [f["path"] for f in d["files"]] == ["SKILL.md", "helper.py", "bin/run.sh"]
        and d["frontmatter"]["name"] == "web-research"
    )
    assert store.detail("Data Clean")["frontmatter"]["name"] == "data-clean"
    assert store.read_file("web-research", "bin/run.sh") == {"text": "echo hi\n", "size": 8, "truncated": False}
    with pytest.raises(SkillError, match="invalid path"):
        store.read_file("web-research", "../notes/SKILL.md")
    with pytest.raises(SkillError, match="not a file"):
        store.read_file("web-research", "nope.txt")
    # Disable moves the directory; a second install of the same name conflicts unless replaced, wherever it lives.
    store.set_enabled("notes", False)
    assert (store.disabled_dir / "notes" / "SKILL.md").exists() and not (store.enabled_dir / "notes").exists()
    assert next(s for s in store.list() if s["name"] == "notes")["enabled"] is False
    again = make_zip(
        {"notes/SKILL.md": SKILL.format(name="notes", desc="Replaced").encode(), "extra/SKILL.md": b"# x\n"}
    )
    assert store.install_zip(again) == {"installed": [], "skipped": [], "conflicts": ["notes"]}
    assert not (store.enabled_dir / "extra").exists()
    assert store.install_zip(again, "skip") == {"installed": ["extra"], "skipped": ["notes"], "conflicts": []}
    assert next(s for s in store.list() if s["name"] == "notes")["description"] == "First line of body."
    assert store.install_zip(again, "replace") == {"installed": ["notes", "extra"], "skipped": [], "conflicts": []}
    assert next(s for s in store.list() if s["name"] == "notes") == {
        "name": "notes",
        "description": "Replaced",
        "version": "1.0",
        "kind": "bundle",
        "enabled": True,
    }
    assert not (store.disabled_dir / "notes").exists() and not list(store.disabled_dir.glob(".install-*"))
    # A UTF-8 name stored without the ZIP UTF-8 flag is decoded.
    unflagged = make_zip({"AAAAAA/SKILL.md": b"# s\n\nbody\n"}).replace(b"AAAAAA", "技能".encode())
    assert store.install_zip(unflagged)["installed"] == ["技能"] and (store.enabled_dir / "技能" / "SKILL.md").exists()
    store.remove("Data Clean")
    with pytest.raises(SkillError, match="not found"):
        store.remove("Data Clean")
    for archive, message in (
        (make_zip({"__MACOSX/x": b"x"}), "no files to extract"),
        (b"nope", "not a ZIP"),
        (make_zip({"../evil/SKILL.md": b"x"}), "invalid path"),
        (make_zip({"a/SKILL.md": b"x", "A.md": b"y"}), "duplicate skill name in ZIP: A"),
        (make_zip({".hidden/SKILL.md": b"x"}), "invalid skill name"),
    ):
        with pytest.raises(SkillError, match=message):
            store.install_zip(archive)


def test_bun_manager_install_with_mocked_release(tmp_path, monkeypatch):
    bun = BunManager(tmp_path / "bun", "9.9.9")
    assert bun.status()["state"] in ("missing", "unsupported")
    if bun.target is None or sys.platform == "win32":
        pytest.skip("no bun target on this platform")
    script = b"#!/bin/sh\necho 9.9.9\n"
    archive = make_zip({f"bun-{bun.target}/bun": script})
    sums = f"{hashlib.sha256(archive).hexdigest()}  bun-{bun.target}.zip\n"
    fetched: list[str] = []

    def fake_fetch(url, on_progress=None):
        fetched.append(url)
        if url.endswith("SHASUMS256.txt"):
            return sums.encode()
        if on_progress:
            on_progress(100)
        return archive

    monkeypatch.setattr(bun, "fetch", fake_fetch)
    bun.install()
    bun.wait()
    st = bun.status()
    assert st["state"] == "ready" and st["version"] == "9.9.9" and st["ready"] is True and "error" not in st, st
    assert fetched == [
        f"https://github.com/oven-sh/bun/releases/download/bun-v9.9.9/bun-{bun.target}.zip",
        "https://github.com/oven-sh/bun/releases/download/bun-v9.9.9/SHASUMS256.txt",
    ]
    assert (tmp_path / "bun" / "bin" / "bunx").is_symlink() and (tmp_path / "bun" / "installed.json").exists()
    # The MCP connection rewrites a bare bun / bunx to the managed one.
    data_dir = tmp_path / "data"
    (data_dir / "toolkit").mkdir(parents=True)
    (data_dir / "toolkit" / "bun").symlink_to(tmp_path / "bun")
    conn = connection_of(ServerConfig(command="bunx", args=["-y", "server"], env={"A": "1"}), data_dir)
    managed = data_dir / "toolkit" / "bun"
    assert (
        conn["command"] == str(managed / "bin" / "bunx")
        and conn["env"]["A"] == "1"
        and conn["env"]["BUN_INSTALL"] == str(managed)
    )
    assert connection_of(ServerConfig(command="bun", args=[]), data_dir)["command"] == str(managed / "bin" / "bun")
    assert connection_of(ServerConfig(command="npx", args=[]), data_dir)[
        "command"
    ] == "npx" and "env" not in connection_of(ServerConfig(command="npx"), data_dir)
    assert connection_of(ServerConfig(command="bun"), None)["command"] == "bun"
    # A checksum mismatch leaves the installed version alone.
    monkeypatch.setattr(bun, "fetch", lambda url, on_progress=None: b"garbage")
    bun.install()
    bun.wait()
    assert (
        bun.status()["error"] == "bun checksum verification failed. Try again." and bun.status()["version"] == "9.9.9"
    )


async def test_routes(home, tmp_path):
    profile = Profile.init("web", home=str(home))
    mcp_patch = {
        "id": "mcp",
        "config": {"servers": {"demo": {"command": sys.executable, "args": [str(MCP_SERVER)]}}, "connect_timeout": 60},
        "merge": True,
    }
    async with Harness(profile, patch=[HTTP_OFF, mcp_patch]) as h:
        center: ConfigCenterService = h.get("configCenter")
        assert center.skills is not None and any(s["label"] == "user" for s in h.get("agentLoop").skills())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=90
        ) as c:
            d = (await c.get("/api/config-center/mcp")).json()
            assert d["servers"]["demo"]["state"] == "connected" and d["connectTimeout"] == 60
            r = await c.post(
                "/api/config-center/mcp/test", json={"server": {"command": sys.executable, "args": [str(MCP_SERVER)]}}
            )
            assert r.json()["result"] == {"ok": True, "tools": ["add"]}
            r = await c.post(
                "/api/config-center/mcp/test", json={"server": {"command": "/nonexistent/mcp"}, "timeout": 10}
            )
            assert r.json()["result"]["ok"] is False and r.json()["result"]["error"]
            assert (await c.post("/api/config-center/mcp/test", json={"server": {}})).status_code == 400
            assert (await c.put("/api/config-center/mcp/timeout", json={"connectTimeout": 0})).status_code == 400
            r = await c.put("/api/config-center/mcp/timeout", json={"connectTimeout": 45})
            assert (
                r.json()["connectTimeout"] == 45
                and (await c.get("/api/config-center/mcp")).json()["connectTimeout"] == 45
            )
            # skills
            assert (await c.get("/api/config-center/skills")).json() == {
                "directory": str(center.skills.enabled_dir),
                "skills": [],
            }
            z = base64.b64encode(
                make_zip({"demo-skill/SKILL.md": SKILL.format(name="demo-skill", desc="A demo").encode()})
            ).decode()
            r = await c.post("/api/config-center/skills/install", json={"data": z, "policy": "ask"})
            assert r.json() == {"installed": ["demo-skill"], "skipped": [], "conflicts": []}
            d = (await c.get("/api/config-center/skills/detail", params={"name": "demo-skill"})).json()
            assert d["enabled"] is True and d["files"] == [
                {"path": "SKILL.md", "size": len(SKILL.format(name="demo-skill", desc="A demo").encode())}
            ]
            assert (
                (await c.get("/api/config-center/skills/file", params={"name": "demo-skill", "file": "SKILL.md"}))
                .json()["text"]
                .startswith("---")
            )
            r = await c.post("/api/config-center/skills", json={"name": "demo-skill", "enabled": False})
            assert r.json()["skills"][0]["enabled"] is False
            assert (await c.post("/api/config-center/skills", json={"name": "demo-skill"})).status_code == 400
            assert (await c.get("/api/config-center/skills/detail", params={"name": "nope"})).status_code == 400
            assert (
                await c.post("/api/config-center/skills/install", json={"data": "!!", "policy": "ask"})
            ).status_code == 400
            assert (await c.delete("/api/config-center/skills", params={"name": "demo-skill"})).json()["skills"] == []
            # environment
            st = (await c.get("/api/config-center/environment")).json()
            assert st["state"] in ("missing", "unsupported") and st["recommendedVersion"] == center.config.bun_version
        assert any(cl["entry"] == "config-center" for cl in h.get("webui").clients())


async def test_mcp_credential_routes(home, monkeypatch):
    for name in ("PYH_T_CC_TOKEN", "PYH_T_CC_IDLE", "PYH_T_CC_SPARE"):
        monkeypatch.delenv(name, raising=False)
    profile = Profile.init("web", home=str(home))
    server = {
        "command": sys.executable,
        "args": [str(MCP_SERVER)],
        "env": {"MCP_TEST_TOKEN": "${credential:PYH_T_CC_TOKEN}", "PLAIN": "plain"},
    }
    idle = {**server, "env": {"MCP_TEST_TOKEN": "${credential:PYH_T_CC_IDLE}"}, "enabled": False}
    mcp_patch = {"id": "mcp", "config": {"servers": {"demo": server, "idle": idle}, "connect_timeout": 60}}
    url = "/api/config-center/mcp/credentials"
    missing = {"reference": "PYH_T_CC_TOKEN", "configured": False, "source": None}
    stored = {"reference": "PYH_T_CC_TOKEN", "configured": True, "source": "store"}
    async with (
        Harness(profile, patch=[HTTP_OFF, mcp_patch]) as h,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=90) as c,
    ):
        shown = (await c.get("/api/config-center/mcp")).json()["servers"]["demo"]
        assert shown["state"] == "waiting-credentials" and shown["missing"] == ["PYH_T_CC_TOKEN"]
        assert shown["env"] == {"MCP_TEST_TOKEN": "${credential:PYH_T_CC_TOKEN}", "PLAIN": "••••"}
        assert shown["credentials"] == [missing]
        # The test route takes the template as written and the masked value from the stored server.
        draft = {"name": "demo", "server": {**server, "env": shown["env"]}}
        assert (await c.post("/api/config-center/mcp/test", json=draft)).json()["result"] == {
            "ok": False,
            "code": "waiting-credentials",
            "error": "missing credentials: PYH_T_CC_TOKEN",
        }
        for bad in (
            {"reference": "lower", "value": "x"},
            {"reference": "PYH_T_CC_TOKEN", "value": "has space"},
            {"reference": "PYH_T_CC_TOKEN", "value": ""},
            {"reference": "PYH_T_CC_TOKEN"},
        ):
            assert (await c.put(url, json=bad)).status_code == 400
        assert profile.credentials.names() == []
        # A credential of an enabled server asks for a restart; any other is stored without one.
        r = await c.put(url, json={"reference": "PYH_T_CC_TOKEN", "value": "cc-secret"})
        assert r.json() == {"credential": stored, "application": "saved-restart-required"}
        assert profile.credentials.get("PYH_T_CC_TOKEN") == "cc-secret"
        for reference in ("PYH_T_CC_IDLE", "PYH_T_CC_SPARE"):
            r = await c.put(url, json={"reference": reference, "value": "other"})
            assert r.json() == {
                "credential": {"reference": reference, "configured": True, "source": "store"},
                "application": "saved",
            }
        assert profile.credentials.names() == ["PYH_T_CC_IDLE", "PYH_T_CC_SPARE", "PYH_T_CC_TOKEN"]
        assert (await c.post("/api/config-center/mcp/test", json=draft)).json()["result"] == {
            "ok": True,
            "tools": ["add", "token"],
        }
        r = await c.get("/api/config-center/mcp")
        assert r.json()["servers"]["demo"]["credentials"] == [stored] and "cc-secret" not in r.text
        r = await c.delete(url, params={"reference": "PYH_T_CC_TOKEN"})
        assert r.json() == {"credential": missing, "application": "saved-restart-required"}
        r = await c.delete(url, params={"reference": "PYH_T_CC_TOKEN"})
        assert r.json() == {"credential": missing, "application": "saved"}
        assert (await c.delete(url, params={"reference": "bad name"})).status_code == 400
        assert (await c.delete(url)).status_code == 400
        assert h.lifecycle.restart_pending is None
    # A supervised harness schedules the restart.
    async with (
        Harness(profile, patch=[HTTP_OFF, mcp_patch], generation=2, supervised=True) as h2,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h2.get("http").app), base_url="http://t") as c,
    ):
        r = await c.put(url, json={"reference": "PYH_T_CC_TOKEN", "value": "cc-secret"})
        assert r.json() == {"credential": stored, "application": "restart-scheduled"}
        assert h2.lifecycle.restart_pending["reasons"] == ["MCP credential changed"]
