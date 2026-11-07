"""The career memory model and its SQLite store.

Tree: ``profile`` (one root) → ``work`` → ``project`` (``fields.workId``; empty = independent, under the root) →
``lesson`` (``fields.parentId``). Every write is a commit: when content changes it adds one revision (time, actor,
source, summary) with a full snapshot of the entries; blobs are content-addressed so unchanged entries are stored once.
``revision`` is a monotonic concurrency counter (``stateToken``); the displayed version is the number of revisions.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from pyharness import package_prompts

PROMPTS = package_prompts(__file__)
KINDS = ("profile", "work", "project", "lesson")
FIELDS: dict[str, tuple[str, ...]] = {
    "profile": ("name", "position", "specialties", "abilities"),
    "work": ("organization", "startDate", "endDate", "jobTitle", "highlights"),
    "project": ("title", "startDate", "endDate", "role", "highlights", "workId"),
    "lesson": ("parentId", "lesson"),
}
KIND_GUIDE: dict[str, str] = PROMPTS["store"]["KIND_GUIDE"]
FIELD_DESCRIPTIONS = {
    "name": "Confirmed agent identity; never infer a name.",
    "position": "Professional focus.",
    "specialties": "Areas of expertise.",
    "abilities": "Demonstrated capabilities.",
    "organization": "Company or organization.",
    "startDate": "Known start date in YYYY-MM-DD; omit unknown dates.",
    "endDate": dedent(
        """
        End date in YYYY-MM-DD, no earlier than startDate; use present for explicitly ongoing work/projects.
        Omit when unknown; empty clears.
        """
    ).strip(),
    "jobTitle": "One position held during this period.",
    "highlights": "Objectives, work performed, verified achievements and concurrent roles.",
    "title": "Short factual title.",
    "role": "Roles in this project.",
    "workId": "Work id or @ref from this batch. Empty for an independent project.",
    "parentId": "Project id or @ref from this batch. Required for a new lesson.",
    "lesson": "One reusable conclusion in one or two sentences; name the scope it applies to.",
}
ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$")
CREATED_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
DATE_RE = re.compile(r"^\d{4}-\d\d-\d\d$")
MAX_ENTRIES = 1000
MAX_FIELD = 12000
MAX_HIGHLIGHTS = 50000
MAX_CHANGES = 100
MAX_SUMMARY = 500
MAX_SOURCE = 2000
SCHEMA_VERSION = 1
EMPTY_ENTRIES: list[dict[str, Any]] = [{"id": "profile", "kind": "profile", "fields": {}}]

MESSAGES = {
    "date": "Use a real calendar date in YYYY-MM-DD format.",
    "dateRange": "End date cannot precede start date.",
    "invalid": "Invalid arguments. Check the field schema and supplied values.",
    "missing": "Record not found. Read its parent node again.",
    "conflict": "Memory changed. Read the affected records again before rebuilding this update; do not blindly retry.",
    "protected": "This operation is only available in the user interface.",
    "reference": dedent(
        """
        Invalid parent reference. Lessons belong to projects; projects optionally belong to work.
        Referenced entries must remain present.
        """
    ).strip(),
    "content": "Required content is missing: work needs any field, a project needs a title, a lesson needs its text.",
    "disabled": "Memory tools are disabled.",
    "busy": "A write is in progress. Retry shortly.",
    "storage": "Memory storage is unavailable.",
}


class MemoryError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, MESSAGES["storage"])

    @property
    def retryable(self) -> bool:
        return self.code in ("conflict", "busy")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(UTC).microsecond // 1000:03d}Z"


def valid_date(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        return date.fromisoformat(value) >= date(1, 1, 1)
    except ValueError:
        return False


def experience_date(entry: dict[str, Any]) -> str:
    if entry["kind"] in ("lesson", "profile"):
        return ""
    fields = entry.get("fields") or {}
    start = fields.get("startDate") or ""
    if start:
        return start
    end = fields.get("endDate") or ""
    return "" if end == "present" else end


def sort_entries(entries: list[dict[str, Any]], order: str = "newest") -> list[dict[str, Any]]:
    """Stable: dated entries by experience date (newest first by default), undated ones last in insertion order."""
    dated = [(experience_date(e), i, e) for i, e in enumerate(entries)]
    with_date = [t for t in dated if t[0]]
    without = [t[2] for t in dated if not t[0]]
    with_date.sort(key=lambda t: t[0], reverse=order == "newest")
    return [t[2] for t in with_date] + without


def children_of(entries: list[dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    by_id = {e["id"]: e for e in entries}
    node = by_id.get(node_id)
    if node is None:
        return []
    kind = node["kind"]
    if kind == "profile":
        out = [
            e
            for e in entries
            if e["kind"] == "work" or (e["kind"] == "project" and not (e["fields"].get("workId") or ""))
        ]
    elif kind == "work":
        out = [e for e in entries if e["kind"] == "project" and e["fields"].get("workId") == node_id]
    elif kind == "project":
        out = [e for e in entries if e["kind"] == "lesson" and e["fields"].get("parentId") == node_id]
    else:
        out = []
    return sort_entries(out, "newest")


def validate_snapshot(entries: Any) -> None:
    """Raise :class:`MemoryError` unless ``entries`` is a valid résumé."""
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise MemoryError("invalid")
    seen: set[str] = set()
    profiles = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"id", "kind", "fields", "createdAt"}:
            raise MemoryError("invalid")
        eid, kind, fields = entry.get("id"), entry.get("kind"), entry.get("fields")
        if (
            not isinstance(eid, str)
            or not ID_RE.match(eid)
            or eid in seen
            or kind not in KINDS
            or not isinstance(fields, dict)
        ):
            raise MemoryError("invalid")
        seen.add(eid)
        created = entry.get("createdAt")
        if created is not None and (not isinstance(created, str) or not CREATED_RE.match(created)):
            raise MemoryError("invalid", "createdAt")
        if kind == "profile":
            profiles += 1
            if eid != "profile":
                raise MemoryError("content", eid)
        for key, value in fields.items():
            if key not in FIELDS[kind] or not isinstance(value, str):
                raise MemoryError("invalid", key)
            if len(value) > (MAX_HIGHLIGHTS if key == "highlights" else MAX_FIELD):
                raise MemoryError("invalid", key)
            if (
                key in ("startDate", "endDate")
                and value
                and not (key == "endDate" and value == "present")
                and not valid_date(value)
            ):
                raise MemoryError("date", key)
        start, end = fields.get("startDate") or "", fields.get("endDate") or ""
        if start and end and end != "present" and start > end:
            raise MemoryError("dateRange")
        if kind == "work" and not any(v.strip() for v in fields.values()):
            raise MemoryError("content", eid)
        if kind == "project" and not (fields.get("title") or "").strip():
            raise MemoryError("content", eid)
        if kind == "lesson" and not (fields.get("lesson") or "").strip():
            raise MemoryError("content", eid)
    if profiles != 1:
        raise MemoryError("invalid")
    by_id = {e["id"]: e for e in entries}
    for entry in entries:
        fields = entry["fields"]
        if entry["kind"] == "lesson":
            parent = by_id.get(fields.get("parentId") or "")
            if parent is None or parent["kind"] != "project":
                raise MemoryError("reference", entry["id"])
        if entry["kind"] == "project" and (fields.get("workId") or ""):
            work = by_id.get(fields["workId"])
            if work is None or work["kind"] != "work":
                raise MemoryError("reference", entry["id"])


def _copy(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(entries))


SCHEMA = dedent(
    """
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS blobs (hash TEXT PRIMARY KEY, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS entries (
        seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, hash TEXT NOT NULL REFERENCES blobs(hash));
    CREATE TABLE IF NOT EXISTS revisions (
        revision INTEGER PRIMARY KEY, time TEXT NOT NULL, actor TEXT NOT NULL, source TEXT NOT NULL,
        summary TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS revision_entries (
        revision INTEGER NOT NULL REFERENCES revisions(revision) ON DELETE CASCADE, seq INTEGER NOT NULL,
        id TEXT NOT NULL, hash TEXT NOT NULL REFERENCES blobs(hash), PRIMARY KEY (revision, seq));
    """
).strip()


class MemoryStore:
    """SQLite-backed résumé with content-addressed revision history. Thread-safe through one lock."""

    def __init__(self, path: str | Path, *, busy_timeout: float = 5.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=busy_timeout)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA secure_delete = ON")
        self.db.executescript(SCHEMA)
        with self._lock:
            if self._meta("schemaVersion") is None:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    self._set_meta("schemaVersion", str(SCHEMA_VERSION))
                    self._set_meta("revision", "0")
                    self._set_meta("agentTools", "1")
                    self._write_entries(EMPTY_ENTRIES)
                    self.db.execute("COMMIT")
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
            elif self._meta("schemaVersion") != str(SCHEMA_VERSION):
                raise MemoryError("invalid", "schemaVersion")

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # ------------------------------------------------------------------ low level
    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _put_blob(self, entry: dict[str, Any]) -> str:
        body = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.db.execute("INSERT OR IGNORE INTO blobs (hash, body) VALUES (?, ?)", (digest, body))
        return digest

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        self.db.execute("DELETE FROM entries")
        for seq, entry in enumerate(entries):
            self.db.execute(
                "INSERT INTO entries (seq, id, hash) VALUES (?, ?, ?)", (seq, entry["id"], self._put_blob(entry))
            )

    def _write_revision_entries(self, revision: int, entries: list[dict[str, Any]]) -> None:
        for seq, entry in enumerate(entries):
            self.db.execute(
                "INSERT INTO revision_entries (revision, seq, id, hash) VALUES (?, ?, ?, ?)",
                (revision, seq, entry["id"], self._put_blob(entry)),
            )

    def _entries(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT b.body FROM entries e JOIN blobs b ON b.hash = e.hash ORDER BY e.seq").fetchall()
        return [json.loads(r[0]) for r in rows]

    def _snapshot(self, revision: int) -> list[dict[str, Any]] | None:
        if self.db.execute("SELECT 1 FROM revisions WHERE revision = ?", (revision,)).fetchone() is None:
            return None
        rows = self.db.execute(
            "SELECT b.body FROM revision_entries r JOIN blobs b ON b.hash = r.hash WHERE r.revision = ? ORDER BY r.seq",
            (revision,),
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def _history(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT revision, time, actor, source, summary FROM revisions ORDER BY revision"
        ).fetchall()
        return [{"revision": r[0], "time": r[1], "actor": r[2], "source": r[3], "summary": r[4]} for r in rows]

    # ------------------------------------------------------------------ reads
    @property
    def revision(self) -> int:
        with self._lock:
            return int(self._meta("revision") or 0)

    @property
    def agent_tools(self) -> bool:
        with self._lock:
            return self._meta("agentTools") == "1"

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._entries()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "revision": int(self._meta("revision") or 0),
                "entries": self._entries(),
                "agentTools": self._meta("agentTools") == "1",
                "history": self._history(),
            }

    def diff(self, revision: int) -> dict[str, Any] | None:
        with self._lock:
            after = self._snapshot(revision)
            if after is None:
                return None
            row = self.db.execute("SELECT MAX(revision) FROM revisions WHERE revision < ?", (revision,)).fetchone()
            before = self._snapshot(row[0]) if row and row[0] is not None else _copy(EMPTY_ENTRIES)
            return {"revision": revision, "before": {"entries": before or []}, "after": {"entries": after}}

    # ------------------------------------------------------------------ writes
    def _transaction(self):
        return _Txn(self)

    def commit(self, input: dict[str, Any], actor: str, source: str) -> dict[str, Any]:
        """Apply ``changes`` (and/or ``restore`` / ``imported``) at ``baseRevision``; returns the new state."""
        if not isinstance(input, dict) or "agentTools" in input:
            raise MemoryError("invalid")
        base = input.get("baseRevision")
        summary = input.get("summary")
        if not isinstance(base, int) or isinstance(base, bool):
            raise MemoryError("invalid")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY:
            raise MemoryError("invalid")
        src = input.get("source", source)
        if not isinstance(src, str) or len(src) > MAX_SOURCE:
            raise MemoryError("invalid")
        changes = input.get("changes")
        if changes is not None and (not isinstance(changes, list) or len(changes) > MAX_CHANGES):
            raise MemoryError("invalid")
        with self._lock, self._transaction():
            current_rev = int(self._meta("revision") or 0)
            if base != current_rev:
                raise MemoryError("conflict")
            if actor == "agent" and self._meta("agentTools") != "1":
                raise MemoryError("disabled")
            if actor == "agent" and ("restore" in input or "imported" in input):
                raise MemoryError("protected")
            current = self._entries()
            nxt = _copy(current)
            if "restore" in input and input["restore"] is not None:
                target = input["restore"]
                if not isinstance(target, int) or isinstance(target, bool):
                    raise MemoryError("invalid")
                if target == 0:
                    nxt = _copy(EMPTY_ENTRIES)
                else:
                    snap = self._snapshot(target)
                    if snap is None:
                        raise MemoryError("missing")
                    nxt = snap
            elif "imported" in input and input["imported"] is not None:
                imported = input["imported"]
                if not isinstance(imported, dict):
                    raise MemoryError("invalid")
                if imported.get("schemaVersion") not in (None, SCHEMA_VERSION):
                    raise MemoryError("invalid", "schemaVersion")
                validate_snapshot(imported.get("entries"))
                nxt = _copy(imported["entries"])
            now = now_iso()
            for change in changes or []:
                if not isinstance(change, dict):
                    raise MemoryError("invalid")
                cid, kind = change.get("id"), change.get("kind")
                if not isinstance(cid, str) or not ID_RE.match(cid) or kind not in KINDS:
                    raise MemoryError("invalid")
                existing = next((e for e in nxt if e["id"] == cid), None)
                if existing is not None and existing["kind"] != kind:
                    raise MemoryError("invalid")
                if change.get("remove"):
                    if existing is None or cid == "profile":
                        raise MemoryError("invalid")
                    nxt = [e for e in nxt if e["id"] != cid]
                    continue
                if existing is None:
                    existing = {"id": cid, "kind": kind, "fields": {}, "createdAt": now}
                    nxt.append(existing)
                fields = change.get("fields")
                if fields is not None:
                    if not isinstance(fields, dict):
                        raise MemoryError("invalid")
                    for key, value in fields.items():
                        existing["fields"][key] = value
            validate_snapshot(nxt)
            if nxt == current:
                return self._state_locked()
            created = {e["id"]: e.get("createdAt") for e in current}
            for entry in nxt:
                if not entry.get("createdAt"):
                    entry["createdAt"] = created.get(entry["id"]) or now
            revision = current_rev + 1
            self.db.execute(
                "INSERT INTO revisions (revision, time, actor, source, summary) VALUES (?, ?, ?, ?, ?)",
                (revision, now, actor, src, summary.strip()),
            )
            self._write_entries(nxt)
            self._write_revision_entries(revision, nxt)
            self._set_meta("revision", str(revision))
            return self._state_locked()

    def clear(self, base_revision: Any) -> dict[str, Any]:
        if not isinstance(base_revision, int) or isinstance(base_revision, bool):
            raise MemoryError("invalid")
        with self._lock:
            with self._transaction():
                current_rev = int(self._meta("revision") or 0)
                if base_revision != current_rev:
                    raise MemoryError("conflict")
                if not self._history() and self._entries() == EMPTY_ENTRIES:
                    return self._state_locked()
                self.db.execute("DELETE FROM entries")
                self.db.execute("DELETE FROM revisions")
                self.db.execute("DELETE FROM blobs")
                self._write_entries(EMPTY_ENTRIES)
                self._set_meta("revision", str(current_rev + 1))
            self.db.execute("VACUUM")
            return self._state_locked()

    def set_agent_tools(self, enabled: Any) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise MemoryError("invalid")
        with self._lock:
            self._set_meta("agentTools", "1" if enabled else "0")
            return self._state_locked()

    def _state_locked(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": int(self._meta("revision") or 0),
            "entries": self._entries(),
            "agentTools": self._meta("agentTools") == "1",
            "history": self._history(),
        }


class _Txn:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def __enter__(self) -> None:
        try:
            self.store.db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                raise MemoryError("busy") from exc
            raise

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self.store.db.execute("COMMIT")
        else:
            self.store.db.execute("ROLLBACK")
            if isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc) or "busy" in str(exc)):
                raise MemoryError("busy") from exc
