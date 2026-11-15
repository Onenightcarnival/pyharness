"""
Web UI: boot manifest, client modules, plugin calls, page preferences, vendored scripts, workspace file
browsing, the inspect ``ui`` topic.
"""

from __future__ import annotations

import json

import httpx

from pyharness import Harness, Profile
from pyharness_web_ui import VENDOR, PrefsStore

HTTP_OFF = {"id": "http", "config": {"serve": False}}
UI_PLUGIN = {"id": "uiplugin", "name": "testkit.uiplugin", "after": "web-ui", "config": {"greeting": "hello"}}


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=30)


async def test_page_carries_the_boot_manifest_and_serves_client_modules(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF, UI_PLUGIN]) as h:
        webui = h.get("webui")
        assert "uiplugin" in [c["entry"] for c in webui.clients()]  # beside built-in modules such as the terminal tab
        assert {s["name"] for s in webui.slots()} >= {"main", "sidebar.panellist", "rightbar.tabs", "settings.sections"}
        async with client(h) as c:
            page = (await c.get("/")).text
            boot = page.split("window.__PYH_BOOT__ = ", 1)[1].split(";</script>", 1)[0]
            manifest = json.loads(boot)
            plugin = next(p for p in manifest["plugins"] if p["id"] == "uiplugin")
            assert (
                plugin["id"] == "uiplugin"
                and plugin["url"].startswith("/plugins/uiplugin/client.js?rev=")
                and plugin["calls"] == ["slow", "stats"]
            )
            assert (await c.get("/plugins/boot.json")).json() == manifest
            js = await c.get(plugin["url"])
            assert (
                js.status_code == 200
                and js.headers["content-type"].startswith("application/javascript")
                and "__PyhModules__" in js.text
            )
            assert (await c.get("/plugins/nope/client.js")).status_code == 404
            r = await c.post("/plugins/uiplugin/call/stats", json={"echo": 1})
            assert r.json() == {"result": {"greeting": "hello", "echo": 1}}
            assert (await c.post("/plugins/uiplugin/call/slow", json={})).json() == {"result": "async ok"}
            assert (await c.post("/plugins/uiplugin/call/stats", json={"fail": True})).status_code == 422
            assert (await c.post("/plugins/uiplugin/call/stats", json=[1])).status_code == 422
            assert (await c.post("/plugins/uiplugin/call/missing", json={})).status_code == 404
        # The inspect topic lists slots and clients.
        tool = next(t for t in h.get("tools").list() if t.name == "harness_inspect")
        ui = json.loads(tool.invoke({"topic": "ui"}))
        assert ui["clients"][0]["entry"] == "uiplugin" and any(s["name"] == "rightbar.tabs" for s in ui["slots"])
    # Without the plugin its module leaves the manifest and the page still renders.
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        page = (await c.get("/")).text
        assert "window.__PYH_BOOT__ = " in page and '"id": "uiplugin"' not in page


async def test_page_preferences_are_validated_and_persist_per_profile(home):
    profile = Profile.init("web", home=str(home))
    stored = profile.data / "web-ui" / "prefs.json"
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        assert (await c.get("/api/webui/prefs")).json() == {"unpinnedPanels": []}
        assert not stored.exists()
        r = await c.put("/api/webui/prefs", json={"unpinnedPanels": ["memory", "gone-panel", "memory"]})
        assert r.status_code == 200 and r.json() == {"unpinnedPanels": ["memory", "gone-panel"]}
        assert json.loads(stored.read_text()) == {"unpinnedPanels": ["memory", "gone-panel"]}
        assert [f.name for f in stored.parent.iterdir()] == ["prefs.json"]
        invalid = [
            {"unpinnedPanels": "memory"},
            {"unpinnedPanels": ["memory", 1]},
            {"unpinnedPanels": ["x" * 201]},
            {"unpinnedPanels": [str(i) for i in range(201)]},
            {"unpinnedPanels": [], "other": 1},
            {},
            ["memory"],
        ]
        for body in invalid:
            assert (await c.put("/api/webui/prefs", json=body)).status_code == 400, body
        r = await c.put("/api/webui/prefs", content=b"{not json", headers={"content-type": "application/json"})
        assert r.status_code == 400
        assert (await c.get("/api/webui/prefs")).json() == {"unpinnedPanels": ["memory", "gone-panel"]}
        limits = {"unpinnedPanels": ["x" * 200, *[str(i) for i in range(199)]]}
        assert (await c.put("/api/webui/prefs", json=limits)).json() == limits
        assert (await c.put("/api/webui/prefs", json={"unpinnedPanels": ["rdb"]})).json() == {"unpinnedPanels": ["rdb"]}
    # A second harness on the same profile reads the stored set.
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        assert (await c.get("/api/webui/prefs")).json() == {"unpinnedPanels": ["rdb"]}
        assert (await c.put("/api/webui/prefs", json={"unpinnedPanels": []})).json() == {"unpinnedPanels": []}
        stored.write_text("{broken")
        assert (await c.get("/api/webui/prefs")).json() == {"unpinnedPanels": []}
        stored.write_text('{"unpinnedPanels": [1]}')
        assert (await c.get("/api/webui/prefs")).json() == {"unpinnedPanels": []}


def test_preferences_without_a_profile_stay_in_memory():
    store = PrefsStore(None)
    assert store.read() == {"unpinnedPanels": []}
    assert store.write({"unpinnedPanels": ["memory"]}) == {"unpinnedPanels": ["memory"]}
    assert store.read() == {"unpinnedPanels": ["memory"]}
    assert PrefsStore(None).read() == {"unpinnedPanels": []}


async def test_vendored_scripts_are_served_with_a_long_cache(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        r = await c.get("/vendor/katex.min.js")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert r.content == (VENDOR / "katex.min.js").read_bytes() and b"renderToString" in r.content
        assert "Khan Academy" in (VENDOR / "katex.LICENSE").read_text()
        assert (await c.get("/vendor/katex.LICENSE")).status_code == 404
        assert (await c.get("/vendor/nope.js")).status_code == 404
        page = (await c.get("/")).text
        assert "/vendor/katex.min.js" in page


async def test_workspace_files_api(home, workspace, tmp_path):
    profile = Profile.init("web", home=str(home))
    ws = workspace
    (ws / "src").mkdir()
    (ws / "src" / "a.py").write_text("print(1)\n")
    (ws / ".hidden").write_text("x")
    (ws / "blob.bin").write_bytes(b"\x00\x01\x02")
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        d = (await c.get("/api/workspaces/files")).json()
        assert d["path"] == "/" and d["root"] == str(ws.resolve())
        assert [e["name"] for e in d["entries"]] == ["src", ".hidden", "blob.bin"]
        assert d["entries"][0]["dir"] is True and d["entries"][1]["hidden"] is True
        d = (await c.get("/api/workspaces/files", params={"path": "/src"})).json()
        assert d["path"] == "/src" and d["entries"][0]["path"] == "/src/a.py" and d["entries"][0]["size"] == 9
        f = (await c.get("/api/workspaces/file", params={"path": "/src/a.py"})).json()
        assert f["text"] == "print(1)\n" and f["binary"] is False and f["truncated"] is False
        f = (await c.get("/api/workspaces/file", params={"path": "/blob.bin"})).json()
        assert f["binary"] is True and f["text"] == ""
        f = (await c.get("/api/workspaces/file", params={"path": "/src/a.py", "limit": 3})).json()
        assert f["text"] == "pri" and f["truncated"] is True
        assert (await c.get("/api/workspaces/file", params={"path": "/src"})).status_code == 404
        raw = await c.get("/api/workspaces/file/raw", params={"path": "/blob.bin"})
        assert (
            raw.status_code == 200
            and raw.content == b"\x00\x01\x02"
            and raw.headers["content-type"] == "application/octet-stream"
        )
        (ws / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        raw = await c.get("/api/workspaces/file/raw", params={"path": "/pic.png"})
        assert raw.headers["content-type"] == "image/png" and raw.headers["cache-control"] == "no-store"
        assert (await c.get("/api/workspaces/file/raw", params={"path": "/src"})).status_code == 404
        assert (await c.get("/api/workspaces/files", params={"path": "/../"})).status_code in (404, 422)
        # Another workspace root: the session's own directory.
        other = tmp_path / "other"
        other.mkdir()
        (other / "note.md").write_text("n")
        d = (await c.get("/api/workspaces/files", params={"root": str(other)})).json()
        assert [e["name"] for e in d["entries"]] == ["note.md"]


async def test_plugin_management_routes(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        r = await c.post("/api/plugins/install", json={"path": str(home / "missing")})
        assert r.status_code == 422 and "does not exist" in r.json()["detail"]
        assert (await c.post("/api/restart")).status_code == 409  # unsupervised test harness
        assert (await c.post("/api/plugins/install", json={"path": "/x", "package": "y"})).status_code == 422
        assert (await c.post("/api/plugins/install", json={})).status_code == 422
        r = await c.post("/api/plugins/install", json={"package": "not a requirement"})
        assert r.status_code == 422 and "not a package requirement" in r.json()["detail"]
        r = await c.put("/api/plugins/entries/nope", json={"enabled": False})
        assert r.status_code == 409  # unknown entries are not user plugins either
        # Built-in bundles and their entries are read-only through the Web API.
        assert (await c.put("/api/plugins/bundles/base", json={"enabled": False})).status_code == 409
        assert (await c.delete("/api/plugins/bundles/base")).status_code == 409
        r = await c.put("/api/plugins/entries/llm", json={"enabled": False})
        assert r.status_code == 409 and "built in" in r.json()["detail"]
        assert (await c.put("/api/plugins/bundles/nope", json={"enabled": True})).status_code == 409
        assert (await c.delete("/api/plugins/bundles/nope")).status_code == 409
