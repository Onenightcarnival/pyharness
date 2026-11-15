"""
Preflight: boot a candidate configuration in a separate process.

| step                                | runs |
|-------------------------------------|------|
| import plugins, validate configs    | yes  |
| start all plugins                   | yes  |
| ``app/ready``                       | yes  |
| ``app/serve`` (ports, resumed work) | no   |
| teardown                            | yes  |

Report: ``ok``, ``errors`` (stage, entry, error), ``pending``, ``warnings``, ``entries``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from .harness import Harness
from .profile import Profile
from .worker import setup_logging


async def preflight_in_process(profile: Profile, extra_patches: list[str] | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"ok": False, "errors": [], "warnings": [], "entries": []}
    try:
        harness = Harness(profile, extra_patches=extra_patches or [], preflight=True)
    except Exception as exc:
        report["errors"].append({"stage": "compose", "error": f"{type(exc).__name__}: {exc}"})
        return report
    report["warnings"] = list(harness.warnings)
    try:
        await harness.start()
        try:
            await harness.ready(serve=False)
        except Exception as exc:
            report["errors"].append({"stage": "app/ready", "error": f"{type(exc).__name__}: {exc}"})
        report["entries"] = harness.loader.snapshot()
    finally:
        await harness.stop()
    for entry in report["entries"]:
        if entry["state"] == "failed":
            report["errors"].append({"stage": "start", "entry": entry["id"], "error": entry.get("error")})
    report["pending"] = [
        {"entry": e["id"], "missing": e.get("missing", [])} for e in report["entries"] if e["state"] == "pending"
    ]
    report["ok"] = not report["errors"]
    return report


def recorded_overlays(profile: Profile) -> list[str]:
    try:
        data = json.loads((profile.runtime / "overlays.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [str(p) for p in data] if isinstance(data, list) else []


async def run_preflight(
    profile: Profile, extra_patches: list[str] | None = None, timeout: float = 180.0
) -> dict[str, Any]:
    """
    Run :func:`preflight_in_process` in a new interpreter; returns its report.

    ``extra_patches=None`` uses the overlays recorded by the running generation.
    """
    if extra_patches is None:
        extra_patches = recorded_overlays(profile)
    cmd = [
        sys.executable,
        "-m",
        "pyharness.preflight",
        "--profile",
        profile.name,
        "--home",
        str(profile.home),
        "--json",
    ]
    for patch in extra_patches or []:
        cmd += ["--patch", str(patch)]
    env = dict(os.environ)
    env.setdefault("PYH_CWD", str(Path.cwd()))
    env["PYH_LOG_LEVEL"] = env.get("PYH_PREFLIGHT_LOG_LEVEL", "WARNING")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "ok": False,
            "errors": [{"stage": "preflight", "error": f"timed out after {timeout:.0f}s"}],
            "entries": [],
        }
    text = out.decode("utf-8", "replace").strip().splitlines()
    for raw in reversed(text):
        line = raw.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    tail = err.decode("utf-8", "replace")[-4000:]
    return {
        "ok": False,
        "errors": [{"stage": "preflight", "error": f"preflight process exited {proc.returncode}", "stderr": tail}],
        "entries": [],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pyharness.preflight")
    parser.add_argument("--profile", default="web")
    parser.add_argument("--home", default=None)
    parser.add_argument("--patch", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()
    profile = Profile(args.profile, args.home).require()
    report = asyncio.run(preflight_in_process(profile, args.patch))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=str))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
