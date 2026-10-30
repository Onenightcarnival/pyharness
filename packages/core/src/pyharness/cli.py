"""``pyh`` command line."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from .profile import Profile


def _profile(args: argparse.Namespace, *, must_exist: bool = True) -> Profile:
    profile = Profile(args.profile, args.home)
    return profile.require() if must_exist else profile


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_init(args: argparse.Namespace) -> int:
    profile = Profile.init(args.profile, args.template, args.home, force=args.force)
    print(f"profile {profile.name!r} at {profile.dir}")
    print(f"bundles: {', '.join(profile.bundles()) or '(none)'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .worker import run_generation, setup_logging

    setup_logging(args.log_level)
    profile = Profile(args.profile, args.home)
    if not profile.exists():
        Profile.init(args.profile, None, args.home)
    os.environ.setdefault("PYH_CWD", os.getcwd())
    if args.no_supervisor:
        return asyncio.run(run_generation(profile, extra_patches=args.patch))
    from .supervisor import Supervisor

    return Supervisor(profile, extra_patches=args.patch, boot_timeout=args.boot_timeout).run()


def cmd_dump(args: argparse.Namespace) -> int:
    profile = _profile(args)
    result = profile.compose(args.patch)
    for warning in result.warnings:
        print(f"# warning: {warning}", file=sys.stderr)
    print(profile.dump(args.patch), end="")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from .preflight import preflight_in_process
    from .worker import setup_logging

    setup_logging("WARNING")
    report = asyncio.run(preflight_in_process(_profile(args), args.patch))
    _print(report if args.verbose else {k: report[k] for k in ("ok", "errors", "pending", "warnings") if k in report})
    return 0 if report["ok"] else 1


def cmd_plugin(args: argparse.Namespace) -> int:
    from . import manage

    profile = _profile(args)
    preflight = not args.no_preflight
    action = args.action
    if action == "list":
        from .preflight import preflight_in_process
        from .worker import setup_logging

        setup_logging("WARNING")
        report = asyncio.run(preflight_in_process(profile))
        rows = [{k: e.get(k) for k in ("id", "name", "state", "source", "missing", "error") if e.get(k)} for e in report["entries"]]
        _print({"bundles": profile.installed_bundles(), "entries": rows})
        return 0
    if action == "install":
        result = asyncio.run(manage.install_bundle(profile, args.target, preflight=preflight))
    elif action == "uninstall":
        result = asyncio.run(manage.uninstall_bundle(profile, args.target, preflight=preflight))
    elif action in ("enable", "disable"):
        result = asyncio.run(manage.set_entry_enabled(profile, args.target, action == "enable", preflight=preflight))
    elif action in ("enable-bundle", "disable-bundle"):
        result = asyncio.run(manage.set_bundle_enabled(profile, args.target, action == "enable-bundle", preflight=preflight))
    else:  # pragma: no cover
        raise SystemExit(f"unknown action {action}")
    _print(result)
    if result.get("application") == "saved":
        from .supervisor import signal_restart

        if signal_restart(profile):
            print("restart signalled to the running supervisor", file=sys.stderr)
        else:
            print("saved; applies on the next start or `pyh restart`", file=sys.stderr)
    return 0 if result.get("application") in ("saved", "unchanged") else 1


def cmd_restart(args: argparse.Namespace) -> int:
    from .supervisor import signal_restart

    if signal_restart(_profile(args)):
        print("restart signalled")
        return 0
    print("no running supervisor for this profile", file=sys.stderr)
    return 1


def cmd_exec(args: argparse.Namespace) -> int:
    from .harness import Harness
    from .worker import setup_logging

    setup_logging(args.log_level or "WARNING")
    profile = _profile(args)
    # Headless: `http` disabled; plugins injecting it stay PENDING.
    patch = [{"id": args.http_entry, "disabled": True}] if args.http_entry else []

    async def main() -> int:
        harness = Harness(profile, patch=[p for p in patch if _has_entry(profile, p["id"])], extra_patches=args.patch)
        async with harness:
            agents = harness.get("agents")
            session = await agents.create_session(title=args.prompt[:60])
            events = agents.start_run(session["id"], args.prompt)
            exit_code = 0
            async for event in events.subscribe():
                kind = event["type"]
                if kind == "token":
                    print(event["text"], end="", flush=True)
                elif kind == "tool_call":
                    print(f"\n[tool] {event['name']}({json.dumps(event.get('args', {}), ensure_ascii=False)})", file=sys.stderr)
                elif kind == "tool_result":
                    print(f"[tool result] {str(event.get('content', ''))[:300]}", file=sys.stderr)
                elif kind == "interrupt":
                    print(f"\n[approval needed] {json.dumps(event['interrupts'], ensure_ascii=False)[:800]}", file=sys.stderr)
                    exit_code = 2
                elif kind == "error":
                    print(f"\n[error] {event['message']}", file=sys.stderr)
                    exit_code = 1
            print()
            print(f"session: {session['id']}", file=sys.stderr)
            return exit_code

    return asyncio.run(main())


def _has_entry(profile: Profile, entry_id: str) -> bool:
    from .config import find

    return find(profile.compose().tree, entry_id) is not None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyh", description="pyharness: an everything-is-a-plugin agent harness")
    parser.add_argument("--home", default=None, help="harness home (default: $PYH_HOME or ~/.pyharness)")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_profile(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("-p", "--profile", default=os.environ.get("PYH_PROFILE", "web"))
        return p

    p = with_profile(sub.add_parser("init", help="create a profile from a template"))
    p.add_argument("--template", default=None, help="web (default), creator or empty")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = with_profile(sub.add_parser("run", help="run the profile under the supervisor"))
    p.add_argument("--patch", action="append", default=[], help="extra patch file applied last (repeatable)")
    p.add_argument("--no-supervisor", action="store_true", help="run one generation without a supervisor; a restart request exits")
    p.add_argument("--boot-timeout", type=float, default=120.0)
    p.add_argument("--log-level", default=None)
    p.set_defaults(func=cmd_run)

    p = with_profile(sub.add_parser("dump-config", help="print the composed configuration tree"))
    p.add_argument("--patch", action="append", default=[])
    p.set_defaults(func=cmd_dump)

    p = with_profile(sub.add_parser("preflight", help="boot the configuration without serving and print the report"))
    p.add_argument("--patch", action="append", default=[])
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_preflight)

    p = with_profile(sub.add_parser("plugin", help="manage bundles and entries of a profile"))
    p.add_argument(
        "action",
        choices=["list", "install", "uninstall", "enable", "disable", "enable-bundle", "disable-bundle"],
    )
    p.add_argument("target", nargs="?", help="path (install), bundle name or entry id")
    p.add_argument("--no-preflight", action="store_true")
    p.set_defaults(func=cmd_plugin)

    p = with_profile(sub.add_parser("restart", help="restart the running worker (SIGHUP to the supervisor)"))
    p.set_defaults(func=cmd_restart)

    p = with_profile(sub.add_parser("exec", help="run one prompt headless (no HTTP server)"))
    p.add_argument("prompt")
    p.add_argument("--patch", action="append", default=[])
    p.add_argument("--http-entry", default="http", help="entry disabled for the run; '' disables none")
    p.add_argument("--log-level", default=None)
    p.set_defaults(func=cmd_exec)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plugin" and args.action != "list" and not args.target:
        parser.error(f"`pyh plugin {args.action}` needs a target")
    sys.exit(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    main()
