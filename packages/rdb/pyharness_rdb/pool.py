"""Connection opening (host order, ``target_session_attrs``) and the per-profile :class:`Pool`."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .driver import Driver, EngineError, parse_hosts, session_matches
from .mysql import MySQLDriver
from .postgres import PgDriver
from .sqlite import SQLiteDriver


def connect(profile: dict[str, Any], password: str) -> Driver:
    """Open a connection for a profile; network kinds try the hosts in order (target_session_attrs, load balancing)."""
    kind = profile["kind"]
    if kind == "sqlite":
        return SQLiteDriver(profile["file"])
    hosts = parse_hosts(profile["host"])
    if profile.get("loadBalanceHosts"):
        hosts = hosts[:]
        random.shuffle(hosts)
    target = profile.get("targetSessionAttrs") or "any"
    passes = ["standby", "any"] if target == "prefer-standby" else [target]
    failures: list[str] = []
    for want in passes:
        for host in hosts:
            port = int(profile["port"])
            try:
                if kind == "mysql":
                    driver: Driver = MySQLDriver(
                        host, port, profile["database"], profile["user"], password, bool(profile.get("ssl"))
                    )
                else:
                    driver = PgDriver(
                        kind, host, port, profile["database"], profile["user"], password, bool(profile.get("ssl"))
                    )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{host}:{port}: {str(exc).strip()}")
                continue
            if want == "any":
                return driver
            try:
                state = driver.session_state()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                driver.close()
                failures.append(f"{host}:{port}: {str(exc).strip()}")
                continue
            if session_matches(want, state):
                return driver
            driver.close()
            failures.append(f"{host}:{port}: session does not satisfy '{want}'")
    raise EngineError(f"no node accepted the connection (target {target}): {'; '.join(failures)}")


@dataclass
class Pool:
    """One live driver per profile id; reopened when the profile changed or the connection died; idle ones closed."""

    idle_close_s: float = 600.0
    drivers: dict[str, tuple[Driver, int]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, profile: dict[str, Any], password: str) -> Driver:
        pid = profile["id"]
        with self.lock:
            entry = self.drivers.get(pid)
            if entry and entry[1] == profile.get("updatedAt") and entry[0].alive:
                entry[0].last_used = time.monotonic()
                return entry[0]
            if entry:
                try:
                    entry[0].close()
                except Exception:  # noqa: BLE001
                    pass
            driver = connect(profile, password)
            self.drivers[pid] = (driver, int(profile.get("updatedAt") or 0))
            return driver

    def drop(self, pid: str) -> None:
        with self.lock:
            entry = self.drivers.pop(pid, None)
        if entry:
            try:
                entry[0].close()
            except Exception:  # noqa: BLE001
                pass

    def sweep(self) -> None:
        now = time.monotonic()
        with self.lock:
            stale = [pid for pid, (d, _) in self.drivers.items() if now - d.last_used > self.idle_close_s]
        for pid in stale:
            self.drop(pid)

    def close_all(self) -> None:
        for pid in list(self.drivers):
            self.drop(pid)
