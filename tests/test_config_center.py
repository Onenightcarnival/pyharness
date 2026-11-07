"""Configuration center: skills store and routes, the MCP page routes (test, timeout), the managed bun runtime."""

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
from pyharness_config_center import ConfigCenterService
from pyharness_config_center.environment import BunManager
from pyharness_config_center.skills import SkillError, SkillStore, normalize_name
from pyharness_mcp import ServerConfig, connection_of

from pyharness import Harness, Profile

HTTP_OFF = {"id": "http", "config": {"serve": False}}
MCP_SERVER = Path(__file__).with_name("testkit") / "mcp_server.py"
SKILL = '---\nname: {name}\ndescription: {desc}\nmetadata:\n  version: "1.0"\n---\n# {name}\n\nDo the thing.\n'


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_skill_store(tmp_path):
    store = SkillStore(tmp_path)
    assert store.list() == [] and normalize_name("My Skill.ZIP") == "my-skill"
    # A multi-skill ZIP: two bundles, a flat markdown file, a README that is skipped.
    bundle = make_zip(
        {
            "web-research/SKILL.md": SKILL.format(name="web-research", desc="Research the web").encode(),
            "web-research/helper.py": b"print(1)\n",
            "web-research/run.sh": b"#!/bin/sh\necho hi\n",
            "Data Clean/SKILL.md": SKILL.format(name="data-clean", desc="Clean data").encode(),
            "notes.md": b"# Notes\n\nFirst line of body.\n",
            "README.md": b"ignored",
        }
    )
    r = store.install_zip(bundle, "skills.zip")
    assert r == {"installed": ["web-research", "data-clean", "notes"], "skipped": [], "conflicts": []}
    assert [s["name"] for s in store.list()] == ["data-clean", "notes", "web-research"]
    notes = next(s for s in store.list() if s["name"] == "notes")
    assert notes["description"] == "First line of body." and notes["enabled"] is True
    assert os.access(store.enabled_dir / "web-research" / "run.sh", os.X_OK)
    d = store.detail("web-research")
    assert (
        d["version"] == "1.0"
        and d["enabled"]
        and [f["path"] for f in d["files"]] == ["SKILL.md", "helper.py", "run.sh"]
        and d["frontmatter"]["name"] == "web-research"
    )
    assert store.read_file("web-research", "helper.py") == {"text": "print(1)\n", "size": 9, "truncated": False}
    with pytest.raises(SkillError, match="invalid path"):
        store.read_file("web-research", "../notes/SKILL.md")
    with pytest.raises(SkillError, match="not a file"):
        store.read_file("web-research", "nope.txt")
    # Disable moves the directory; a second install of the same name conflicts unless replaced.
    store.set_enabled("notes", False)
    assert (store.disabled_dir / "notes" / "SKILL.md").exists() and not (store.enabled_dir / "notes").exists()
    assert next(s for s in store.list() if s["name"] == "notes")["enabled"] is False
    single = make_zip({"SKILL.md": SKILL.format(name="notes", desc="Replaced").encode()})
    assert store.install_zip(single, "notes.zip") == {"installed": [], "skipped": [], "conflicts": ["notes"]}
    assert store.install_zip(single, "notes.zip", "skip") == {"installed": [], "skipped": ["notes"], "conflicts": []}
    assert store.install_zip(single, "notes.zip", "replace") == {"installed": ["notes"], "skipped": [], "conflicts": []}
    assert next(s for s in store.list() if s["name"] == "notes") == {
        "name": "notes",
        "description": "Replaced",
        "version": "1.0",
        "kind": "bundle",
        "enabled": True,
    }
    assert not (store.disabled_dir / "notes").exists()
    store.remove("data-clean")
    with pytest.raises(SkillError, match="not found"):
        store.remove("data-clean")
    with pytest.raises(SkillError, match="no skills"):
        store.install_zip(make_zip({"x.txt": b"x"}), "x.zip")
    with pytest.raises(SkillError, match="not a ZIP"):
        store.install_zip(b"nope", "x.zip")
    with pytest.raises(SkillError, match="invalid path"):
        store.install_zip(make_zip({"../evil/SKILL.md": b"x"}), "x.zip")


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
                make_zip({"SKILL.md": SKILL.format(name="demo-skill", desc="A demo").encode()})
            ).decode()
            r = await c.post(
                "/api/config-center/skills/install", json={"filename": "demo-skill.zip", "data": z, "policy": "ask"}
            )
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
                await c.post(
                    "/api/config-center/skills/install", json={"filename": "x.zip", "data": "!!", "policy": "ask"}
                )
            ).status_code == 400
            assert (await c.delete("/api/config-center/skills", params={"name": "demo-skill"})).json()["skills"] == []
            # environment
            st = (await c.get("/api/config-center/environment")).json()
            assert st["state"] in ("missing", "unsupported") and st["recommendedVersion"] == center.config.bun_version
        assert any(cl["entry"] == "config-center" for cl in h.get("webui").clients())
