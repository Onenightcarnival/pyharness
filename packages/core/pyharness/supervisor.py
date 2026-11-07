"""Supervisor: runs one worker generation at a time; owns restarts and rollbacks.

| worker outcome                        | supervisor action                                                   |
|---------------------------------------|---------------------------------------------------------------------|
| ready marker written                  | record ``ready``                                                    |
| exit 75                               | start the next generation                                           |
| exit 0, or SIGINT/SIGTERM received    | stop                                                                |
| boot failure                          | restore last-known-good, write ``rollback.json``, start again; once |
| boot failure, nothing to restore      | exit 3                                                              |
| killed by a forwarded signal, booting | start again; no rollback                                            |
| other exit after boot                 | back-off restart; stop after ``max_crashes`` in ``crash_window``    |

| signal to supervisor | effect                                                 |
|----------------------|--------------------------------------------------------|
| SIGINT, SIGTERM      | stop the worker, exit 0                                |
| SIGHUP               | forwarded; the worker restarts once holds are released |

Events are appended to ``runtime/supervisor.log.jsonl``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .lifecycle import BOOT_FAILURE_EXIT_CODE, RESTART_EXIT_CODE
from .profile import Profile

log = logging.getLogger("pyharness.supervisor")


class Supervisor:
    def __init__(
        self,
        profile: Profile,
        *,
        extra_patches: list[str] | None = None,
        boot_timeout: float = 120.0,
        max_crashes: int = 3,
        crash_window: float = 60.0,
        python: str | None = None,
    ) -> None:
        self.profile = profile
        self.extra_patches = list(extra_patches or [])
        self.boot_timeout = boot_timeout
        self.max_crashes = max_crashes
        self.crash_window = crash_window
        self.python = python or sys.executable
        self.generation = 0
        self.proc: subprocess.Popen[bytes] | None = None
        self._stopping = False
        self._signalled = False  # the current worker received a supervisor signal
        self._crashes: list[float] = []
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ signals
    def _install_signals(self) -> None:
        def stop(signum: int, _frame: Any) -> None:
            self._stopping = True
            self._signal_worker(signal.SIGTERM)

        def restart(_signum: int, _frame: Any) -> None:
            log.info("SIGHUP: worker restart after running turns")
            self._signal_worker(signal.SIGHUP)

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, restart)

    def _signal_worker(self, sig: int) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self._signalled = True
            with contextlib.suppress(ProcessLookupError):
                self.proc.send_signal(sig)

    # ------------------------------------------------------------------ one generation
    def _spawn(self) -> tuple[subprocess.Popen[bytes], Path]:
        self.generation += 1
        self._signalled = False
        ready = self.profile.runtime / f"ready-{self.generation}.json"
        ready.unlink(missing_ok=True)
        (self.profile.runtime / "boot-error.json").unlink(missing_ok=True)
        cmd = [
            self.python,
            "-m",
            "pyharness.worker",
            "--profile",
            self.profile.name,
            "--home",
            str(self.profile.home),
            "--generation",
            str(self.generation),
            "--ready-file",
            str(ready),
            "--supervised",
        ]
        for patch in self.extra_patches:
            cmd += ["--patch", patch]
        env = dict(os.environ)
        env.setdefault("PYH_CWD", str(Path.cwd()))
        env["PYH_GENERATION"] = str(self.generation)
        log.info("starting generation %d", self.generation)
        self.proc = subprocess.Popen(cmd, env=env)
        return self.proc, ready

    def _wait_ready(self, proc: subprocess.Popen[bytes], ready: Path) -> bool:
        deadline = time.monotonic() + self.boot_timeout
        while time.monotonic() < deadline:
            if ready.exists():
                return True
            if proc.poll() is not None:
                return ready.exists()
            time.sleep(0.1)
        log.error("generation %d did not become ready within %.0fs", self.generation, self.boot_timeout)
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return False

    def _boot_error(self) -> dict[str, Any]:
        path = self.profile.runtime / "boot-error.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"error": "worker exited before becoming ready (no boot-error.json)"}

    def _record(self, event: str, **data: Any) -> None:
        item = {"generation": self.generation, "event": event, "at": time.time(), **data}
        self.history.append(item)
        self.profile.runtime.mkdir(parents=True, exist_ok=True)
        with (self.profile.runtime / "supervisor.log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ loop
    def run(self) -> int:
        self.profile.require()
        self.profile.runtime.mkdir(parents=True, exist_ok=True)
        (self.profile.runtime / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
        self._install_signals()
        rolled_back_once = False
        try:
            while not self._stopping:
                proc, ready = self._spawn()
                booted = self._wait_ready(proc, ready)
                if not booted:
                    code = proc.wait()
                    if self._stopping:
                        return 0
                    if self._signalled:
                        self._record("interrupted-boot", code=code)
                        continue
                    error = self._boot_error()
                    self._record("boot-failed", code=code, error=error.get("error"))
                    if not rolled_back_once and self.profile.restore_last_known_good():
                        rolled_back_once = True
                        log.error(
                            "generation %d failed to boot (%s); restored last-known-good configuration",
                            self.generation,
                            error.get("error"),
                        )
                        (self.profile.runtime / "rollback.json").write_text(
                            json.dumps({"failed_generation": self.generation, **error}, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        self._record("rolled-back")
                        continue
                    log.error(
                        "generation %d failed to boot and there is nothing to roll back to: %s",
                        self.generation,
                        error.get("error"),
                    )
                    return BOOT_FAILURE_EXIT_CODE
                rolled_back_once = False
                self._record("ready")
                code = proc.wait()
                self._record("exited", code=code)
                if self._stopping:
                    return 0
                if code == RESTART_EXIT_CODE:
                    log.info("generation %d requested a restart", self.generation)
                    continue
                if code == 0:
                    return 0
                now = time.monotonic()
                self._crashes = [t for t in self._crashes if now - t < self.crash_window] + [now]
                if len(self._crashes) > self.max_crashes:
                    log.error("worker crashed %d times within %.0fs; giving up", len(self._crashes), self.crash_window)
                    return code
                delay = min(2 ** (len(self._crashes) - 1), 10)
                log.warning("generation %d exited with %d; restarting in %ss", self.generation, code, delay)
                time.sleep(delay)
            return 0
        finally:
            self._signal_worker(signal.SIGTERM)
            if self.proc is not None:
                try:
                    self.proc.wait(15)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    self.proc.kill()
            (self.profile.runtime / "supervisor.pid").unlink(missing_ok=True)


def signal_restart(profile: Profile) -> bool:
    """Send SIGHUP to the profile's supervisor; returns ``False`` without a live supervisor (POSIX)."""
    pid_file = profile.runtime / "supervisor.pid"
    try:
        pid = int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return False
    if not hasattr(signal, "SIGHUP"):
        return False
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.parent.parent.exists():  # /proc: the pid must belong to a pyharness process
        try:
            if b"pyharness" not in cmdline.read_bytes() and b"pyh" not in cmdline.read_bytes():
                return False
        except OSError:
            return False
    try:
        os.kill(pid, signal.SIGHUP)
    except ProcessLookupError:
        return False
    return True
