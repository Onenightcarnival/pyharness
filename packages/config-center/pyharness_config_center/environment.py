"""Managed bun runtime for JavaScript MCP servers: a pinned bun release under ``<profile data>/toolkit/bun/``, verified
against the release's ``SHASUMS256.txt``; MCP server commands that are a bare ``bun`` / ``bunx`` run through it
(see :func:`pyharness_mcp.managed_bun`). PATH is never changed."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from pyharness import package_toml

_ENVIRONMENT = package_toml(__file__)["environment"]

BUN_VERSION: str = _ENVIRONMENT["BUN_VERSION"]
RELEASE: str = _ENVIRONMENT["RELEASE"]
DOWNLOAD_LIMIT = 200 * 1024 * 1024
DOWNLOAD_TIMEOUT = 300.0
LOCK_WAIT = 360.0

# ``(sys.platform, machine)`` → bun release target.
TARGETS: dict[tuple[str, str], str] = {(t["system"], t["machine"]): t["target"] for t in _ENVIRONMENT["TARGETS"]}
MESSAGES = {
    "unsupported": "This operating system or architecture is not supported.",
    "broken": "Installed bun cannot run. Repair the environment.",
    "checksum": "bun checksum verification failed. Try again.",
    "version": "bun version verification failed.",
    "toolarge": "bun download exceeds the size limit.",
    "inuse": "bun is in use or its directory is not writable. Stop related MCP servers and retry.",
}


def target_of() -> str | None:
    key = (sys.platform if sys.platform != "linux2" else "linux", platform.machine().lower())
    if sys.platform.startswith("linux"):
        key = ("linux", key[1])
        if "musl" in (platform.libc_ver()[0] or "").lower():
            return None
    return TARGETS.get(key)


def bun_env(root: Path) -> dict[str, str]:
    """Environment for the managed bun: caches and global installs stay under the data root."""
    return {"BUN_INSTALL": str(root), "BUN_INSTALL_CACHE_DIR": str(root / "cache"), "NO_UPDATE_NOTIFIER": "1"}


class BunManager:
    def __init__(self, root: Path, version: str = BUN_VERSION) -> None:
        self.root = root
        self.version = version
        self.target = target_of()
        self._phase: str | None = None
        self._progress: float | None = None
        self._error: str | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def exe(self) -> Path:
        return self.root / "bin" / ("bun.exe" if sys.platform == "win32" else "bun")

    @property
    def bunx(self) -> Path:
        return self.root / "bin" / ("bunx.exe" if sys.platform == "win32" else "bunx")

    # ------------------------------------------------------------------ status
    def installed_version(self) -> str | None:
        if not self.exe.exists():
            return None
        try:
            out = subprocess.run(
                [str(self.exe), "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
                env={**os.environ, **bun_env(self.root)},
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    def status(self) -> dict[str, Any]:
        version = self.installed_version()
        if self._phase:
            state = self._phase
        elif self.target is None:
            state = "unsupported"
        elif version is None:
            state = "missing"
        elif version != self.version:
            state = "error" if version == "" else "ready"
        else:
            state = "ready"
        out: dict[str, Any] = {
            "state": state,
            "ready": state == "ready",
            "supported": self.target is not None,
            "target": self.target or f"{sys.platform}-{platform.machine()}",
            "recommendedVersion": self.version,
            "path": str(self.exe),
            "dataDirectory": str(self.root),
        }
        if version:
            out["version"] = version
        if self._progress is not None and self._phase == "downloading":
            out["progress"] = round(self._progress)
        error = self._error or (MESSAGES["broken"] if version == "" else None)
        if error:
            out["error"] = error
        return out

    # ------------------------------------------------------------------ install
    def install(self) -> dict[str, Any]:
        """Start the download / verify / install in a thread (one at a time); returns the status right away."""
        if self.target is None:
            raise RuntimeError(MESSAGES["unsupported"])
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._error = None
            self._phase = "downloading"
            self._progress = None
            self._thread = threading.Thread(target=self._run, name="bun-install", daemon=True)
            self._thread.start()
        return self.status()

    def wait(self, timeout: float = 600.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            self._install()
            self._error = None
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc).strip() or type(exc).__name__
        finally:
            self._phase = None
            self._progress = None

    def fetch(self, url: str, on_progress: Any | None = None) -> bytes:
        buf = io.BytesIO()
        with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as res:
            if res.status_code != 200:
                raise RuntimeError(f"bun download failed: HTTP {res.status_code}")
            total = int(res.headers.get("content-length") or 0)
            for chunk in res.iter_bytes():
                buf.write(chunk)
                if buf.tell() > DOWNLOAD_LIMIT:
                    raise RuntimeError(MESSAGES["toolarge"])
                if on_progress and total:
                    on_progress(buf.tell() * 100 / total)
        return buf.getvalue()

    def _install(self) -> None:
        asset = f"bun-{self.target}.zip"
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / "installation"
        waited = 0.0
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if waited > LOCK_WAIT:
                    raise RuntimeError(MESSAGES["inuse"]) from None
                time.sleep(1)
                waited += 1
        tmp = Path(tempfile.mkdtemp(prefix=".install-", dir=self.root))
        try:
            self._phase = "downloading"
            archive = self.fetch(
                RELEASE.format(version=self.version, asset=asset), lambda p: setattr(self, "_progress", p)
            )
            self._phase = "verifying"
            sums = self.fetch(RELEASE.format(version=self.version, asset="SHASUMS256.txt")).decode("utf-8", "replace")
            expected = next((line.split()[0] for line in sums.splitlines() if line.strip().endswith(asset)), None)
            if expected is None or hashlib.sha256(archive).hexdigest() != expected.lower():
                raise RuntimeError(MESSAGES["checksum"])
            self._phase = "installing"
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                members = [m for m in zf.namelist() if m.rsplit("/", 1)[-1] in ("bun", "bun.exe")]
                if not members:
                    raise RuntimeError(MESSAGES["version"])
                ready = tmp / "ready"
                ready.mkdir()
                with zf.open(members[0]) as src, (ready / self.exe.name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            (ready / self.exe.name).chmod(0o755)
            if sys.platform != "win32":
                (ready / "bunx").symlink_to(self.exe.name)
            else:
                shutil.copy2(ready / self.exe.name, ready / "bunx.exe")
            out = subprocess.run(
                [str(ready / self.exe.name), "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
                env={**os.environ, **bun_env(self.root)},
            )
            if out.returncode != 0 or out.stdout.strip() != self.version:
                raise RuntimeError(MESSAGES["version"])
            target = self.root / "bin"
            backup = self.root / f".bin-backup-{int(time.time())}"
            if target.exists():
                try:
                    target.rename(backup)
                except OSError as exc:
                    raise RuntimeError(MESSAGES["inuse"]) from exc
            try:
                ready.rename(target)
            except OSError as exc:
                if backup.exists():
                    backup.rename(target)
                raise RuntimeError(
                    f"bun replacement failed; the previous version is kept at {backup}. "
                    "Stop related MCP servers and retry."
                ) from exc
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            (self.root / "cache").mkdir(exist_ok=True)
            (self.root / "installed.json").write_text(
                f'{{"version": "{self.version}", "target": "{self.target}", '
                f'"installedAt": {int(time.time() * 1000)}}}\n'
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            with contextlib.suppress(OSError):
                lock_path.unlink()
