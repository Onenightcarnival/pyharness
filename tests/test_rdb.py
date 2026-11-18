"""
Database workbench: statement classification, the SQLite driver, paging and grid changes, profiles, tools and
routes.
"""

from __future__ import annotations

import json
import sqlite3
from textwrap import dedent

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_rdb import RdbService, engine as eng
from pyxis_harness_rdb.store import ProfileStore, StoreError

HTTP_OFF = {"id": "http", "config": {"serve": False}}


def test_classification_and_splitting():
    ro = lambda s, mysql=False: eng.is_read_only(s, mysql)  # noqa: E731
    assert (
        ro("SELECT 1")
        and ro("with x as (select 1) select * from x")
        and ro("EXPLAIN SELECT 1")
        and ro("SHOW CREATE TABLE t", True)
    )
    assert (
        ro("SELECT CASE WHEN a THEN 1 ELSE 2 END FROM t") and ro("PRAGMA table_info(t)") and ro("PRAGMA user_version")
    )
    assert (
        not ro("PRAGMA user_version = 3")
        and not ro("INSERT INTO t VALUES (1)")
        and not ro("SELECT * INTO backup FROM t")
    )
    assert (
        not ro("SELECT * FROM t FOR UPDATE")
        and not ro("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")
        and not ro("-- hi\nDROP TABLE t")
    )
    assert ro("SELECT 'insert into' FROM t") and ro('SELECT "drop" FROM t') and ro("SELECT * FROM t -- drop table t")
    assert eng.split_statements("select 1; select 'a;b'; -- x;\n select 2 ;", False) == [
        "select 1",
        "select 'a;b'",
        "-- x;\n select 2",
    ]
    assert eng.split_statements("insert into t values ('a\\;b'); select 1", True) == [
        "insert into t values ('a\\;b')",
        "select 1",
    ]
    assert eng.split_statements("select (1;2)", False) == ["select (1;2)"]
    assert (
        eng.command_of("  /* c */ select 1", False) == "SELECT"
        and eng.command_of("#x\nupdate t set a=1", True) == "UPDATE"
    )
    assert (
        eng.sql_literal("it's") == "'it''s'"
        and eng.sql_literal("a'b", True) == "'a\\'b'"
        and eng.sql_literal(None) == "NULL"
        and eng.sql_literal(True) == "TRUE"
    )
    assert eng.host_entries("a, ::1 [::2]", 5) == ["a:5", "[::1]:5", "[::2]:5"] and eng.parse_hosts("[::1], b") == [
        "::1",
        "b",
    ]


def seed(path):
    db = sqlite3.connect(path)
    db.executescript(
        dedent(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER DEFAULT 0);
            CREATE INDEX users_name ON users(name);
            CREATE VIEW adults AS SELECT * FROM users WHERE age >= 18;
            CREATE TABLE nopk (a TEXT, b TEXT);
            INSERT INTO users (name, age) VALUES ('ann', 30), ('bob', 12), ('cy', 44);
            """
        ).strip()
    )
    db.commit()
    db.close()


def test_sqlite_driver_paging_and_changes(tmp_path):
    path = tmp_path / "t.sqlite"
    seed(path)
    d = eng.SQLiteDriver(str(path))
    assert d.list_schemas() == ["main"] and d.server_version().startswith("SQLite ")
    assert d.list_tables("main") == [
        {"schema": "main", "name": "nopk", "kind": "table"},
        {"schema": "main", "name": "users", "kind": "table"},
        {"schema": "main", "name": "adults", "kind": "view"},
    ]
    info = eng.table_info(d, "main", "users")
    assert (
        info.primary_key == ["id"]
        and info.estimated_rows == 3
        and [c["name"] for c in info.columns] == ["id", "name", "age"]
    )
    assert info.columns[1] == {
        "name": "name",
        "type": "TEXT",
        "nullable": False,
        "defaultValue": None,
        "primaryKey": False,
        "position": 2,
    }
    assert info.indexes == [{"name": "users_name", "columns": ["name"], "unique": False, "primary": False}]
    assert d.ddl("main", "users", "table").startswith("CREATE TABLE users") and "CREATE INDEX users_name" in d.ddl(
        "main", "users", "table"
    )
    res = eng.run_query(d, "select * from users order by id", allow_write=False, max_rows=2)
    assert (
        res.rows == [[1, "ann", 30], [2, "bob", 12]]
        and res.truncated
        and res.row_count == 2
        and res.command == "SELECT"
    )
    with pytest.raises(eng.EngineError, match="refused"):
        eng.run_query(d, "delete from users", allow_write=False)
    with pytest.raises(eng.EngineError, match="one statement"):
        eng.run_query(d, "select 1; select 2", allow_write=False)
    assert eng.run_query(d, "update users set age = 13 where name = 'bob'", allow_write=True).row_count == 1
    page = eng.page_rows(
        d,
        "main",
        "users",
        offset=0,
        limit=2,
        sort={"column": "age", "desc": True},
        filters=[{"column": "name", "op": "like", "value": "%"}],
    )
    assert [r[1] for r in page["rows"]] == ["cy", "ann"] and page["total"] == 3 and page["primaryKey"] == ["id"]
    page = eng.page_rows(d, "main", "users", filters=[{"column": "age", "op": ">=", "value": "18"}])
    assert page["total"] == 2 and page["rowCount"] == 2
    with pytest.raises(eng.EngineError, match="unknown column"):
        eng.page_rows(d, "main", "users", filters=[{"column": "nope", "op": "="}])
    preview = eng.grid_changes(
        d,
        "main",
        "users",
        [
            {"kind": "update", "key": {"id": 2}, "values": {"name": "bo'b"}},
            {"kind": "insert", "values": {"name": "dee"}},
            {"kind": "delete", "key": {"id": 3}},
        ],
        False,
    )
    assert preview == {
        "statements": [
            'UPDATE "main"."users" SET "name" = \'bo\'\'b\' WHERE "id" = 2',
            'INSERT INTO "main"."users" ("name") VALUES (\'dee\')',
            'DELETE FROM "main"."users" WHERE "id" = 3',
        ],
        "applied": False,
    }
    applied = eng.grid_changes(
        d,
        "main",
        "users",
        [
            {"kind": "update", "key": {"id": 2}, "values": {"name": "bo'b"}},
            {"kind": "insert", "values": {"name": "dee"}},
            {"kind": "delete", "key": {"id": 3}},
        ],
        True,
    )
    assert applied["applied"] is True and applied["affected"] == 3
    assert [r[1] for r in eng.run_query(d, "select * from users order by id", allow_write=False).rows] == [
        "ann",
        "bo'b",
        "dee",
    ]
    failed = eng.grid_changes(
        d, "main", "users", [{"kind": "insert", "values": {"name": None}, "nulls": ["name"]}], True
    )
    assert failed["applied"] is False and "NOT NULL" in failed["error"]
    with pytest.raises(eng.EngineError, match="no primary key"):
        eng.grid_changes(d, "main", "nopk", [{"kind": "delete", "key": {"a": "x"}}], False)
    assert (
        eng.to_csv(eng.run_query(d, "select name, age from users where id = 2", allow_write=False))
        == "name,age\r\nbo'b,13\r\n"
    )
    assert "ann  | 30" in eng.human_table(
        eng.run_query(d, "select name, age from users order by id", allow_write=False)
    )
    with pytest.raises(eng.EngineError, match="timed out"):
        eng.run_query(
            d,
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c",
            allow_write=False,
            timeout_ms=100,
        )
    d.close()


def test_profile_store(tmp_path):
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
    store = ProfileStore(tmp_path / "rdb.json", creds)
    assert store.settings() == {"agentTools": False} and store.profiles() == []
    a = store.create({"kind": "sqlite", "file": "/tmp/x.sqlite"})
    assert a["name"] == "x.sqlite" and a["port"] == 0 and a["host"] == "" and len(a["id"]) == 12
    b = store.create(
        {
            "kind": "postgres",
            "host": "db1.example.com,db2.example.com",
            "database": "app",
            "user": "u",
            "password": "s3cret",
            "allowWrite": True,
        }
    )
    assert (
        b["name"] == "app@db1.example.com"
        and b["port"] == 5432
        and b["host"] == "db1.example.com, db2.example.com"
        and "password" not in b
    )
    assert creds.get(f"RDB_{b['id'].upper()}") == "s3cret" and store.password(b["id"]) == "s3cret"
    c = store.create({"kind": "sqlite", "file": "/tmp/other/x.sqlite"})
    assert c["name"] == "x.sqlite 2"
    for payload, msg in [
        ({"kind": "oracle"}, "kind must be"),
        ({"kind": "sqlite"}, "file is required"),
        ({"kind": "mysql", "host": "h:3306", "database": "d", "user": "u"}, "hosts take no port"),
        ({"kind": "mysql", "host": "", "database": "d", "user": "u"}, "host is required"),
        ({"kind": "mysql", "host": "h", "database": "d", "user": "u", "port": 70000}, "port must be"),
        ({"kind": "mysql", "host": "h", "database": "", "user": "u"}, "database is required"),
        ({"kind": "mysql", "host": "h", "database": "d", "user": "u", "targetSessionAttrs": "x"}, "targetSessionAttrs"),
        ({"kind": "mysql", "host": "h", "database": "d", "user": "u", "name": "bad/name"}, "name may contain"),
    ]:
        with pytest.raises(StoreError, match=msg):
            store.create(payload)
    b2 = store.update(b["id"], {"name": "prod", "password": ""})
    assert (
        b2["name"] == "prod" and creds.get(f"RDB_{b['id'].upper()}") == "s3cret" and b2["updatedAt"] >= b["updatedAt"]
    )
    assert (
        store.find("PROD")["id"] == b["id"] and store.find(a["id"])["kind"] == "sqlite" and store.find("nope") is None
    )
    store.delete(b["id"])
    assert creds.get(f"RDB_{b['id'].upper()}") is None and len(store.profiles()) == 2
    with pytest.raises(StoreError, match="not found"):
        store.delete(b["id"])
    assert store.set_settings(agentTools=True) == {"agentTools": True}


async def test_tools_and_routes(home, tmp_path):
    path = tmp_path / "t.sqlite"
    seed(path)
    profile = Profile.init("web", home=str(home))
    async with Harness(
        profile, patch=[HTTP_OFF, {"id": "rdb", "config": {"path": str(tmp_path / "rdb.json")}, "merge": True}]
    ) as h:
        rdb: RdbService = h.get("rdb")
        assert not any(t.name.startswith("db_") for t in h.get("tools").list())  # agent access is off by default
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=30
        ) as c:
            r = await c.post("/api/rdb/profiles", json={"kind": "sqlite", "file": str(path), "name": "local"})
            assert r.status_code == 201
            pid = r.json()["profile"]["id"]
            assert (await c.post("/api/rdb/profiles", json={"kind": "sqlite"})).status_code == 400
            r = await c.post("/api/rdb/test", json={"id": pid})
            assert r.json()["result"]["ok"] is True and r.json()["result"]["serverVersion"].startswith("SQLite")
            assert (await c.get("/api/rdb/schemas", params={"id": pid})).json() == {
                "schemas": ["main"],
                "defaultSchema": "main",
            }
            tables = (await c.get("/api/rdb/tables", params={"id": pid, "schema": "main"})).json()["tables"]
            assert [t["name"] for t in tables] == ["nopk", "users", "adults"]
            info = (await c.get("/api/rdb/columns", params={"id": pid, "table": "users"})).json()["info"]
            assert info["primaryKey"] == ["id"] and info["estimatedRows"] == 3
            assert (
                "CREATE TABLE users"
                in (await c.get("/api/rdb/ddl", params={"id": pid, "table": "users"})).json()["ddl"]
            )
            page = (
                await c.post(
                    "/api/rdb/rows",
                    json={"id": pid, "table": "users", "limit": 2, "sort": {"column": "id", "desc": True}},
                )
            ).json()["page"]
            assert [r[0] for r in page["rows"]] == [3, 2] and page["total"] == 3
            r = await c.post("/api/rdb/query", json={"id": pid, "sql": "select count(*) from users"})
            assert r.json()["result"]["rows"] == [[3]]
            r = await c.post("/api/rdb/query", json={"id": pid, "sql": "select 1; select 2"})
            assert r.status_code == 400 and "one statement" in r.json()["detail"]
            r = await c.post(
                "/api/rdb/changes",
                json={
                    "id": pid,
                    "table": "users",
                    "changes": [{"kind": "update", "key": {"id": 1}, "values": {"age": "31"}}],
                    "apply": True,
                },
            )
            assert r.json()["result"]["applied"] is True and r.json()["result"]["affected"] == 1
            csv = await c.get(
                "/api/rdb/export.csv",
                params={"id": pid, "sql": "select name from users where id = 1", "name": "main.users"},
            )
            assert csv.text == "﻿name\r\nann\r\n" and 'filename="main.users.csv"' in csv.headers["content-disposition"]
            assert (
                await c.get("/api/rdb/export.csv", params={"id": pid, "sql": "delete from users"})
            ).status_code == 400
            r = await c.post("/api/rdb/settings", json={"agentTools": True})
            assert r.json()["settings"]["agentTools"] is True
            tools = {t.name: t for t in h.get("tools").list()}
            assert {"db_connections", "db_schema", "db_query", "db_explain", "db_execute"} <= set(
                tools
            ) and "database workbench" in h.get("prompt").render()
            assert tools["db_connections"].invoke({}).splitlines()[2] == f"local | sqlite | {path} | read-only"
            out = await tools["db_schema"].ainvoke({"connection": "local"})
            assert out.startswith("schemas: main\n\nmain.nopk\nmain.users\n[view] main.adults")
            out = await tools["db_schema"].ainvoke({"connection": "local", "table": "users"})
            assert (
                out.startswith("main.users (table, ~3 rows)")
                and "id | INTEGER | yes |  | PK" in out
                and "indexes: users_name(name)" in out
            )
            out = await tools["db_query"].ainvoke(
                {"connection": "local", "sql": "select name from users order by id", "maxRows": 2}
            )
            assert out.splitlines()[-1] == "(2 row(s), truncated — add WHERE/LIMIT, 0 ms)" or "truncated" in out
            assert (await tools["db_query"].ainvoke({"connection": "local", "sql": "delete from users"})).startswith(
                "query failed: refused"
            )
            assert (await tools["db_query"].ainvoke({"connection": "nope", "sql": "select 1"})).startswith(
                "query failed: unknown connection"
            )
            assert (
                "SCAN"
                in (
                    await tools["db_explain"].ainvoke({"connection": "local", "sql": "explain select * from users"})
                ).upper()
            )
            assert (
                await tools["db_execute"].ainvoke(
                    {"connection": "local", "statements": ["delete from users"], "confirm": False}
                )
            ).startswith("execute failed (rolled back): refused: confirm")
            assert "read-only for the agent" in await tools["db_execute"].ainvoke(
                {"connection": "local", "statements": ["delete from users"], "confirm": True}
            )
            await c.patch(f"/api/rdb/profiles?id={pid}", json={"allowWrite": True})
            out = await tools["db_execute"].ainvoke(
                {
                    "connection": "local",
                    "statements": [
                        "insert into users (name) values ('zed')",
                        "update users set age = 1 where name = 'zed'",
                    ],
                    "confirm": True,
                }
            )
            assert out == "executed 2 statement(s) in one transaction, 2 row(s) affected"
            out = await tools["db_execute"].ainvoke(
                {
                    "connection": "local",
                    "statements": ["insert into users (name) values ('again')", "insert into nope values (1)"],
                    "confirm": True,
                }
            )
            assert out.startswith("execute failed (rolled back)")
            assert (
                await c.post(
                    "/api/rdb/query",
                    json={"id": pid, "sql": "select count(*) from users where name in ('zed','again')"},
                )
            ).json()["result"]["rows"] == [[1]]
            assert (await c.delete(f"/api/rdb/profiles?id={pid}")).json() == {"ok": True}
            assert (await c.get("/api/rdb/profiles")).json() == {"profiles": []}
        assert rdb.pool.drivers == {}
        assert any(cl["entry"] == "rdb" for cl in h.get("webui").clients())
        json.dumps(h.get("tools").list()[0].name)
