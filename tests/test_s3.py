"""S3 browser: profile store, bucket operations against an in-memory client, tools and routes."""

from __future__ import annotations

import datetime as dt
import io

import httpx
import pytest

from pyharness import Harness, Profile
from pyharness_s3 import S3Service
from pyharness_s3 import engine as eng
from pyharness_s3.store import ProfileStore, StoreError

HTTP_OFF = {"id": "http", "config": {"serve": False}}


class FakeS3:
    """The subset of the boto3 S3 client the engine uses, over a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_batch = False

    def _err(self, code: str, message: str) -> Exception:
        exc = Exception(message)
        exc.response = {"Error": {"Code": code, "Message": message}}  # type: ignore[attr-defined]
        return exc

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=1000, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken) if ContinuationToken else 0
        contents, prefixes, seen = [], [], set()
        i = start
        while i < len(keys) and len(contents) + len(prefixes) < MaxKeys:
            k = keys[i]
            rest = k[len(Prefix) :]
            if Delimiter and Delimiter in rest:
                p = Prefix + rest.split(Delimiter)[0] + Delimiter
                if p not in seen:
                    seen.add(p)
                    prefixes.append({"Prefix": p})
            else:
                body = self.objects[k][0]
                contents.append(
                    {
                        "Key": k,
                        "Size": len(body),
                        "LastModified": dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC),
                        "ETag": '"e"',
                    }
                )
            i += 1
        out = {"Contents": contents, "CommonPrefixes": prefixes, "IsTruncated": i < len(keys)}
        if out["IsTruncated"]:
            out["NextContinuationToken"] = str(i)
        return out

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self._err("NoSuchKey", "The specified key does not exist.")
        body, ctype = self.objects[Key]
        return {
            "ContentLength": len(body),
            "ContentType": ctype,
            "ETag": '"e"',
            "Metadata": {"owner": "ann"},
            "LastModified": dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        }

    def get_object(self, Bucket, Key, Range=None):
        if Key not in self.objects:
            raise self._err("NoSuchKey", "The specified key does not exist.")
        body, ctype = self.objects[Key]
        out = {"ContentType": ctype, "ContentLength": len(body), "LastModified": dt.datetime(2026, 1, 2, tzinfo=dt.UTC)}
        if Range:
            end = int(Range.split("-")[1])
            out["Body"] = _Body(body[: end + 1])
            out["ContentRange"] = f"bytes 0-{min(end, len(body) - 1)}/{len(body)}"
        else:
            out["Body"] = _Body(body)
        return out

    def put_object(self, Bucket, Key, Body=b"", ContentType="application/octet-stream", ContentLength=None):
        self.objects[Key] = (bytes(Body), ContentType)
        return {"ETag": '"new"'}

    def upload_fileobj(self, fileobj, Bucket, Key, ExtraArgs=None, Config=None):
        self.objects[Key] = (fileobj.read(), (ExtraArgs or {}).get("ContentType", "application/octet-stream"))

    def delete_objects(self, Bucket, Delete):
        if self.fail_batch:
            raise self._err("NotImplemented", "no batch delete")
        errors = []
        for o in Delete["Objects"]:
            if o["Key"].endswith("locked.txt"):
                errors.append({"Key": o["Key"], "Code": "AccessDenied", "Message": "locked"})
            else:
                self.objects.pop(o["Key"], None)
        return {"Errors": errors}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)
        return {}

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective=None):
        src = CopySource["Key"]
        if src not in self.objects:
            raise self._err("NoSuchKey", "The specified key does not exist.")
        self.objects[Key] = self.objects[src]
        return {}

    def generate_presigned_url(self, method, Params, ExpiresIn):
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?m={method}&exp={ExpiresIn}"


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, n: int | None = None) -> bytes:
        return self.data if n is None else self.data[:n]

    def iter_chunks(self, size: int = 65536):
        for i in range(0, len(self.data), size):
            yield self.data[i : i + size]


def test_store(tmp_path):
    class Creds:
        def __init__(self):
            self.d = {}

        def get(self, r):
            return self.d.get(r)

        def set(self, r, v):
            self.d[r] = v

        def delete(self, r):
            return self.d.pop(r, None) is not None

    creds = Creds()
    store = ProfileStore(tmp_path / "s3.json", creds)
    a = store.create(
        {
            "bucket": "my-bucket",
            "endpoint": "https://s3.example.com/",
            "accessKeyId": "AKIAEXAMPLE",
            "secretAccessKey": "s3cr3t",
            "prefix": "/team-a",
        }
    )
    assert (
        a["name"] == "my-bucket"
        and a["endpoint"] == "https://s3.example.com"
        and a["prefix"] == "team-a/"
        and a["pathStyle"] is True
        and a["accessKeyHint"] == "AKIA…LE"
    )
    assert "secretAccessKey" not in a and "accessKeyId" not in a and creds.get(f"S3_{a['id'].upper()}") == "s3cr3t"
    b = store.create({"bucket": "my-bucket", "accessKeyId": "k", "secretAccessKey": "s"})
    assert b["name"] == "my-bucket 2" and b["pathStyle"] is False and b["region"] == "us-east-1"
    for payload, msg in [
        ({"bucket": "", "accessKeyId": "k", "secretAccessKey": "s"}, "bucket is required"),
        ({"bucket": "Bad_Bucket", "accessKeyId": "k", "secretAccessKey": "s"}, "bucket name looks invalid"),
        ({"bucket": "ok-bucket", "accessKeyId": "", "secretAccessKey": "s"}, "accessKeyId is required"),
        ({"bucket": "ok-bucket", "accessKeyId": "k", "secretAccessKey": ""}, "secretAccessKey is required"),
        ({"bucket": "ok-bucket", "accessKeyId": "k", "secretAccessKey": "s", "endpoint": "nope"}, "full URL"),
        ({"bucket": "ok-bucket", "accessKeyId": "k", "secretAccessKey": "s", "endpoint": "ftp://x"}, "http(s)"),
        ({"bucket": "ok-bucket", "accessKeyId": "k", "secretAccessKey": "s", "pathStyle": "yes"}, "pathStyle must be"),
        ({"bucket": "ok-bucket", "accessKeyId": "k", "secretAccessKey": "s", "name": "a/b"}, "name may contain"),
    ]:
        with pytest.raises(StoreError, match=msg.replace("(", "\\(").replace(")", "\\)")):
            store.create(payload)
    a2 = store.update(a["id"], {"name": "prod", "secretAccessKey": ""})
    assert (
        a2["name"] == "prod" and creds.get(f"S3_{a['id'].upper()}") == "s3cr3t" and store.find("PROD")["id"] == a["id"]
    )
    store.delete(a["id"])
    assert creds.get(f"S3_{a['id'].upper()}") is None and len(store.profiles()) == 1


def test_bucket_operations(tmp_path):
    fake = FakeS3()
    fake.objects = {
        "team/a.txt": (b"hello", "text/plain"),
        "team/docs/b.md": (b"# b", "text/markdown"),
        "team/docs/img.png": (b"\x89PNG\x00\x01", "image/png"),
        "other/x": (b"x", "text/plain"),
    }
    b = eng.Bucket(fake, {"bucket": "bk", "prefix": "team/"})
    assert b.test()["ok"] is True
    page = b.list("")
    assert (
        page["folders"] == ["docs/"] and [o["key"] for o in page["objects"]] == ["a.txt"] and page["truncated"] is False
    )
    assert [o["key"] for o in b.walk("docs/")] == ["docs/b.md", "docs/img.png"]
    small = b.list("", None, 1)
    assert small["truncated"] is True and small["nextToken"]
    assert b.stat("a.txt") == {
        "key": "a.txt",
        "size": 5,
        "metadata": {"owner": "ann"},
        "contentType": "text/plain",
        "etag": '"e"',
        "lastModified": "2026-01-02T00:00:00+00:00",
    }
    assert b.get_text("a.txt") == {"text": "hello", "size": 5, "contentType": "text/plain", "truncated": False}
    assert b.get_text("a.txt", 2)["truncated"] is True
    with pytest.raises(eng.S3Error, match="binary"):
        b.get_text("docs/img.png")
    with pytest.raises(eng.S3Error, match='".."'):
        b.get_text("../other/x")
    assert b.put("new/c.json", b"{}")["size"] == 2 and fake.objects["team/new/c.json"] == (b"{}", "application/json")
    b.mkdir("empty")
    assert fake.objects["team/empty/"][0] == b""
    b.copy("a.txt", "a2.txt", move=True)
    assert "team/a.txt" not in fake.objects and fake.objects["team/a2.txt"][0] == b"hello"
    with pytest.raises(eng.S3Error, match="same key"):
        b.copy("a2.txt", "a2.txt")
    src = tmp_path / "up.bin"
    src.write_bytes(b"\x00" * 10)
    assert (
        b.upload_file(str(src), "bin/up.bin") == {"size": 10}
        and fake.objects["team/bin/up.bin"][1] == "application/octet-stream"
    )
    assert (
        b.download_file("docs/b.md", str(tmp_path / "out" / "b.md")) == {"size": 3}
        and (tmp_path / "out" / "b.md").read_text() == "# b"
    )
    url = b.presign("docs/b.md", 99999999)["url"]
    assert url.endswith("team/docs/b.md?m=get_object&exp=604800")
    fake.objects["team/docs/locked.txt"] = (b"x", "text/plain")
    r = b.delete(["docs/", "a2.txt", ""])
    assert r["deleted"] == 4 and r["errors"] == [
        {"key": "docs/locked.txt", "error": "AccessDenied locked"}
    ]  # the folder marker counts
    assert set(fake.objects) == {"team/docs/locked.txt", "other/x", "team/new/c.json", "team/empty/", "team/bin/up.bin"}
    fake.fail_batch = True
    r = b.delete(["new/c.json"])
    assert r["deleted"] == 1 and "team/new/c.json" not in fake.objects
    assert (
        eng.human(1536) == "1.5 KiB"
        and eng.human(5) == "5 B"
        and eng.guess_mime("x.PARQUET") == "application/vnd.apache.parquet"
    )


async def test_tools_and_routes(home, tmp_path):
    profile = Profile.init("web", home=str(home))
    fake = FakeS3()
    fake.objects = {
        "a.txt": (b"hello world", "text/plain"),
        "logs/1.log": (b"l1", "text/plain"),
        "logs/2.log": (b"l2", "text/plain"),
        "pic.png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    }
    async with Harness(
        profile, patch=[HTTP_OFF, {"id": "s3", "config": {"path": str(tmp_path / "s3.json")}, "merge": True}]
    ) as h:
        s3: S3Service = h.get("s3")
        s3.make_client = lambda profile, secret: fake
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=30
        ) as c:
            r = await c.post(
                "/api/s3/profiles",
                json={
                    "bucket": "demo-bucket",
                    "endpoint": "http://127.0.0.1:9000",
                    "accessKeyId": "minio",
                    "secretAccessKey": "minio123",
                    "name": "demo",
                },
            )
            assert r.status_code == 201
            pid = r.json()["profile"]["id"]
            assert (await c.post("/api/s3/test", json={"id": pid})).json()["result"]["ok"] is True
            page = (await c.get("/api/s3/list", params={"id": pid})).json()["page"]
            assert page["folders"] == ["logs/"] and [o["key"] for o in page["objects"]] == ["a.txt", "pic.png"]
            assert (await c.get("/api/s3/stat", params={"id": pid, "key": "a.txt"})).json()["stat"]["size"] == 11
            assert (await c.get("/api/s3/text", params={"id": pid, "key": "a.txt"})).json()["text"] == "hello world"
            r = await c.get("/api/s3/object", params={"id": pid, "key": "a.txt"})
            assert (
                r.content == b"hello world"
                and r.headers["content-type"].startswith("application/octet-stream")
                and r.headers["content-disposition"].startswith('attachment; filename="a.txt"')
            )
            r = await c.get("/api/s3/object", params={"id": pid, "key": "pic.png", "inline": "1"})
            assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"].startswith("inline")
            assert (await c.get("/api/s3/object", params={"id": pid, "key": "missing"})).status_code == 400
            r = await c.put(
                "/api/s3/upload",
                params={"id": pid, "key": "up/new.csv"},
                content=b"a,b\n1,2\n",
                headers={"content-type": "application/octet-stream"},
            )
            assert r.json() == {"ok": True, "key": "up/new.csv"} and fake.objects["up/new.csv"] == (
                b"a,b\n1,2\n",
                "text/csv; charset=utf-8",
            )
            assert (await c.post("/api/s3/folder", json={"id": pid, "key": "new-dir/"})).json() == {
                "ok": True
            } and "new-dir/" in fake.objects
            assert (
                await c.post("/api/s3/copy", json={"id": pid, "from": "a.txt", "to": "b.txt", "move": True})
            ).json() == {"ok": True} and "a.txt" not in fake.objects
            r = await c.post("/api/s3/presign", json={"id": pid, "key": "b.txt", "expiresIn": 60})
            assert r.json()["url"].endswith("b.txt?m=get_object&exp=60") and r.json()["expiresAt"].endswith("Z")
            r = await c.post("/api/s3/delete", json={"id": pid, "keys": ["logs/", "new-dir/"]})
            assert r.json()["result"] == {"deleted": 4, "errors": []} and not any(
                k.startswith("logs/") for k in fake.objects
            )
            assert (await c.post("/api/s3/delete", json={"id": pid, "keys": []})).status_code == 400
            assert (await c.post("/api/s3/settings", json={"agentTools": True})).json()["settings"][
                "agentTools"
            ] is True
            tools = {t.name: t for t in h.get("tools").list()}
            assert {
                "s3_buckets",
                "s3_list",
                "s3_stat",
                "s3_get",
                "s3_put",
                "s3_upload",
                "s3_download",
                "s3_copy",
                "s3_presign",
                "s3_mkdir",
                "s3_delete",
            } <= set(tools)
            assert "S3 object storage browser" in h.get("prompt").render()
            assert (
                tools["s3_buckets"].invoke({}).splitlines()[2]
                == "demo | demo-bucket | http://127.0.0.1:9000 | us-east-1 | /"
            )
            out = await tools["s3_list"].ainvoke({"profile": "demo"})
            assert out.splitlines()[0] == "prefix: /" and "  b.txt" in out and "pic.png" in out
            out = await tools["s3_list"].ainvoke({"profile": "demo", "recursive": True, "max": 1})
            assert out.splitlines()[-1] == "… truncated at max; raise max or narrow the prefix"
            assert (await tools["s3_get"].ainvoke({"profile": "demo", "key": "b.txt"})) == "hello world"
            assert (await tools["s3_get"].ainvoke({"profile": "demo", "key": "pic.png"})).startswith(
                "read failed: object is binary"
            )
            assert (
                await tools["s3_put"].ainvoke({"profile": "demo", "key": "notes/n.md", "content": "# hi"})
            ) == "wrote notes/n.md (4 bytes)"
            assert (await tools["s3_stat"].ainvoke({"profile": "demo", "key": "notes/n.md"})).splitlines()[
                1
            ] == "size: 4 B (4 bytes)"
            assert (
                await tools["s3_copy"].ainvoke({"profile": "demo", "from": "notes/n.md", "to": "notes/m.md"})
            ) == "copied notes/n.md → notes/m.md"
            assert (await tools["s3_presign"].ainvoke({"profile": "demo", "key": "b.txt", "method": "PUT"})).startswith(
                "https://signed.example/demo-bucket/b.txt?m=put_object&exp=3600\n(expires "
            )
            assert (
                await tools["s3_mkdir"].ainvoke({"profile": "demo", "key": "backups/2026"})
            ) == "created folder backups/2026"
            assert (
                await tools["s3_delete"].ainvoke({"profile": "demo", "keys": ["notes/"], "confirm": False})
            ).startswith("delete failed: refused")
            assert (
                await tools["s3_delete"].ainvoke({"profile": "demo", "keys": ["notes/"], "confirm": True})
            ) == "deleted 3 object(s)"  # two objects and the folder marker
            assert (await tools["s3_list"].ainvoke({"profile": "nope"})).startswith(
                "list failed: unknown bucket profile"
            )
            local = tmp_path / "local.txt"
            local.write_text("local")
            assert (
                await tools["s3_upload"].ainvoke({"profile": "demo", "localPath": str(local), "key": "l.txt"})
            ) == f"uploaded {local} → l.txt (5 B)"
            assert (
                await tools["s3_download"].ainvoke(
                    {"profile": "demo", "key": "l.txt", "localPath": str(tmp_path / "d" / "l.txt")}
                )
            ) == f"downloaded l.txt → {tmp_path / 'd' / 'l.txt'} (5 B)"
            assert (await c.post("/api/s3/settings", json={"agentTools": False})).json()["settings"][
                "agentTools"
            ] is False
            assert not any(t.name.startswith("s3_") for t in h.get("tools").list())
            assert (await c.delete(f"/api/s3/profiles?id={pid}")).json() == {"ok": True}
        assert any(cl["entry"] == "s3" for cl in h.get("webui").clients())
    io.BytesIO()
