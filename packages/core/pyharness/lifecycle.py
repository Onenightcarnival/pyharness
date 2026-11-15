"""
Process lifecycle: activity holds, restarts, and the hand-off between generations.

| exit code                    | meaning                   |
|------------------------------|---------------------------|
| ``0``                        | stop                      |
| ``RESTART_EXIT_CODE`` 75     | start the next generation |
| ``BOOT_FAILURE_EXIT_CODE`` 3 | boot failed               |

Restart:

1. :meth:`Lifecycle.request_restart` records reasons and sessions to resume.
2. The process exits 75 once every :meth:`Lifecycle.hold` is released.
3. While a restart is pending, :attr:`Lifecycle.accepting_work` is ``False``.

Hand-off files (runtime directory):

| file              | writer                           | content                     |
|-------------------|----------------------------------|-----------------------------|
| ``resume.json``   | :meth:`request_restart`          | reasons, sessions to resume |
| ``rollback.json`` | supervisor, after a boot failure | failed generation, error    |

| step   | method                          | effect                                                       |
|--------|---------------------------------|--------------------------------------------------------------|
| read   | :meth:`handoff`                 | reads both files once; files stay                            |
| commit | :meth:`commit_handoff`          | worker deletes both files after the generation boots         |
| abort  | :meth:`discard_pending_restart` | a non-restart exit deletes this generation's ``resume.json`` |
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger("pyharness.lifecycle")

RESTART_EXIT_CODE = 75
BOOT_FAILURE_EXIT_CODE = 3


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        log.warning("ignoring malformed %s", path)
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class Lifecycle:
    def __init__(
        self,
        runtime_dir: Path | None,
        generation: int = 1,
        *,
        supervised: bool = False,
        preflight: bool = False,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.generation = generation
        self.supervised = supervised
        self.preflight = preflight
        self.restart_pending: dict[str, Any] | None = None
        self.exit_code: int | None = None
        self._active: dict[int, tuple[str, str | None]] = {}
        self._seq = 0
        self._stopped: asyncio.Event | None = None
        self._handoff: dict[str, Any] | None = None
        self._handoff_read = False

    # ------------------------------------------------------------------ files
    @property
    def resume_file(self) -> Path | None:
        return self.runtime_dir / "resume.json" if self.runtime_dir else None

    @property
    def rollback_file(self) -> Path | None:
        return self.runtime_dir / "rollback.json" if self.runtime_dir else None

    def _event(self) -> asyncio.Event:
        if self._stopped is None:
            self._stopped = asyncio.Event()
        return self._stopped

    # ------------------------------------------------------------------ activity
    @property
    def active(self) -> list[str]:
        return [label for label, _ in self._active.values()]

    @property
    def accepting_work(self) -> bool:
        """``False`` while a restart is pending or the process is stopping."""
        return self.restart_pending is None and self.exit_code is None

    @contextlib.asynccontextmanager
    async def hold(self, label: str = "work", *, session: str | None = None) -> AsyncIterator[None]:
        self._seq += 1
        token = self._seq
        self._active[token] = (label, session)
        try:
            yield
        finally:
            self._active.pop(token, None)
            self._maybe_finish()

    # ------------------------------------------------------------------ control
    def request_restart(self, reason: str, resume: Iterable[str] = ()) -> dict[str, Any]:
        """Request the next generation; the process exits once all holds are released."""
        record = self.restart_pending or {"reasons": [], "resume": [], "requested_at": time.time()}
        if reason not in record["reasons"]:
            record["reasons"].append(reason)
        for session in resume:
            if session and session not in record["resume"]:
                record["resume"].append(session)
        record["from_generation"] = self.generation
        self.restart_pending = record
        if self.resume_file is not None and not self.preflight:
            _write_json(self.resume_file, record)
        log.info("restart requested: %s (waiting for %d active holds)", reason, len(self._active))
        self._maybe_finish()
        return record

    def stop(self, code: int = 0) -> None:
        if self.exit_code is None:
            self.exit_code = code
        self._event().set()

    async def wait_stopped(self) -> int:
        await self._event().wait()
        return self.exit_code or 0

    def _maybe_finish(self) -> None:
        if self.restart_pending is not None and not self._active and self.exit_code is None:
            self.stop(RESTART_EXIT_CODE)

    def discard_pending_restart(self) -> None:
        """Delete this generation's pending ``resume.json``; called on a non-restart exit."""
        if self.restart_pending is not None and self.resume_file is not None:
            data = _read_json(self.resume_file)
            if isinstance(data, dict) and data.get("from_generation") == self.generation:
                self.resume_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------ hand-off
    def handoff(self) -> dict[str, Any] | None:
        """Hand-off left by earlier generations; read once, files kept."""
        if not self._handoff_read:
            self._handoff_read = True
            state: dict[str, Any] = {}
            if self.resume_file is not None:
                data = _read_json(self.resume_file)
                if isinstance(data, dict) and data.get("from_generation") != self.generation:
                    state.update(data)
            if self.rollback_file is not None:
                rollback = _read_json(self.rollback_file)
                if isinstance(rollback, dict):
                    state["rollback"] = rollback
            self._handoff = state or None
        return self._handoff

    def commit_handoff(self) -> None:
        """Delete the hand-off files; the worker calls this after the generation boots."""
        self.handoff()
        for path in (self.resume_file, self.rollback_file):
            if path is None:
                continue
            if path == self.resume_file and self.restart_pending is not None:
                continue  # this generation's own request belongs to the next generation
            path.unlink(missing_ok=True)

    def describe(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "supervised": self.supervised,
            "preflight": self.preflight,
            "restart_pending": self.restart_pending,
            "active": self.active,
        }


__all__ = ["BOOT_FAILURE_EXIT_CODE", "RESTART_EXIT_CODE", "Lifecycle"]
