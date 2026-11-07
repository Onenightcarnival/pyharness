"""Worker process: one generation of the harness.

``python -m pyharness.worker --profile web``

1. compose the profile; start every plugin
2. ``app/ready``, ``app/serve``
3. save last-known-good, write the ready marker, commit the hand-off (supervised)
4. ``app/started``; run until stopped

| signal          | effect                                   |
|-----------------|------------------------------------------|
| SIGINT, SIGTERM | stop, exit 0                             |
| SIGHUP          | restart once holds are released, exit 75 |

Exit codes follow :mod:`pyharness.lifecycle`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from .harness import Harness
from .lifecycle import BOOT_FAILURE_EXIT_CODE, RESTART_EXIT_CODE
from .profile import Profile

log = logging.getLogger("pyharness.worker")


def setup_logging(level: str | None = None) -> None:
    level = (level or os.environ.get("PYH_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    for noisy in ("httpx", "httpcore", "aiosqlite", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _write_boot_error(
    profile: Profile, generation: int, stage: str, exc: BaseException, harness: Harness | None
) -> None:
    profile.runtime.mkdir(parents=True, exist_ok=True)
    payload = {
        "generation": generation,
        "stage": stage,
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": "".join(traceback.format_exception(exc))[-8000:],
        "at": time.time(),
        "entries": harness.loader.snapshot() if harness is not None else [],
    }
    (profile.runtime / "boot-error.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def run_generation(
    profile: Profile,
    *,
    extra_patches: list[str] | None = None,
    generation: int = 1,
    supervised: bool = False,
    ready_file: Path | None = None,
) -> int:
    harness: Harness | None = None
    stage = "compose"
    booted_state = profile.read_state()  # last-known-good candidate
    record_overlays(profile, extra_patches or [])
    try:
        harness = Harness(profile, extra_patches=extra_patches or [], generation=generation, supervised=supervised)
        for warning in harness.warnings:
            log.warning("compose: %s", warning)
        _install_signal_handlers(harness)
        stage = "start"
        await harness.start()
        stage = "ready"
        await harness.ready()
    except BaseException as exc:  # noqa: BLE001
        log.error(
            "generation %d failed during %s: %s", generation, stage, exc, exc_info=log.isEnabledFor(logging.DEBUG)
        )
        _write_boot_error(profile, generation, stage, exc, harness)
        if harness is not None:
            await harness.stop()
        if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
            return 0
        return BOOT_FAILURE_EXIT_CODE

    lifecycle = harness.lifecycle
    summary = harness.loader.summary()
    log.info("generation %d ready (%s)", generation, ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))
    for entry in harness.loader.snapshot():
        if entry["state"] == "pending":
            log.info("  %s is pending: missing %s", entry["id"], ", ".join(entry.get("missing", [])))
    # Commit point.
    profile.save_last_known_good(booted_state)
    if ready_file is not None:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text(
            json.dumps({"pid": os.getpid(), "generation": generation, "summary": summary}), encoding="utf-8"
        )
    if supervised:
        lifecycle.handoff()
        lifecycle.commit_handoff()
    await harness.started()

    code = await lifecycle.wait_stopped()
    log.info(
        "generation %d stopping (exit code %d%s)",
        generation,
        code,
        ", restart requested" if code == RESTART_EXIT_CODE else "",
    )
    if code != RESTART_EXIT_CODE:
        lifecycle.discard_pending_restart()
    await harness.stop()
    return code


def record_overlays(profile: Profile, extra_patches: list[str]) -> None:
    """Record the generation's ``--patch`` overlays in ``runtime/overlays.json`` (read by preflight)."""
    profile.runtime.mkdir(parents=True, exist_ok=True)
    paths = [str(Path(p).resolve()) for p in extra_patches]
    (profile.runtime / "overlays.json").write_text(json.dumps(paths), encoding="utf-8")


def _install_signal_handlers(harness: Harness) -> None:
    lifecycle = harness.lifecycle
    loop = asyncio.get_running_loop()
    handlers: list[tuple[int, Any]] = [
        (signal.SIGINT, lambda: lifecycle.stop(0)),
        (signal.SIGTERM, lambda: lifecycle.stop(0)),
    ]
    if hasattr(signal, "SIGHUP"):
        handlers.append((signal.SIGHUP, lambda: lifecycle.request_restart("restart signal")))
    for sig, handler in handlers:
        with contextlib.suppress((NotImplementedError, RuntimeError)):
            loop.add_signal_handler(sig, handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pyharness.worker")
    parser.add_argument("--profile", default=os.environ.get("PYH_PROFILE", "web"))
    parser.add_argument("--home", default=None)
    parser.add_argument("--patch", action="append", default=[])
    parser.add_argument("--generation", type=int, default=int(os.environ.get("PYH_GENERATION", "1")))
    parser.add_argument("--ready-file", default=None)
    parser.add_argument("--supervised", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()
    profile = Profile(args.profile, args.home).require()
    code = asyncio.run(
        run_generation(
            profile,
            extra_patches=args.patch,
            generation=args.generation,
            supervised=args.supervised,
            ready_file=Path(args.ready_file) if args.ready_file else None,
        )
    )
    sys.exit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
