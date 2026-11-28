from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import re
import shutil
import sys
import time
from collections.abc import AsyncIterator
from importlib import metadata
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from uv import find_uv_bin

from .config import ConfigError, find
from .plugin import BUNDLE_GROUP
from .preflight import run_preflight
from .profile import Profile

_process_lock = asyncio.Lock()


class ManageError(RuntimeError):
    pass


# ---------------------------------------------------------------------- installer
def kernel_pins(profile: Profile) -> list[str]:
    """
    ``name==version`` of the distributions the harness process imports ahead of the profile's ``site/``.

    | distribution                                   | pinned |
    |------------------------------------------------|--------|
    | installed from an index or a wheel             | yes    |
    | installed from a local directory (a checkout)  | no     |
    | in the profile's ``site/``                     | no     |
    """
    site = profile.site.resolve()
    pins: dict[str, str] = {}
    for dist in metadata.distributions():
        name, location = dist.metadata["Name"], getattr(dist, "_path", None)
        if not name or not dist.version or _norm(name) in pins:
            continue
        if location is not None and site in Path(location).resolve().parents:
            continue
        if '"dir_info"' in (dist.read_text("direct_url.json") or ""):
            continue
        pins[_norm(name)] = f"{name}=={dist.version}"
    return sorted(pins.values())


def _installer(profile: Profile) -> list[str]:
    """
    ``uv pip install`` into the profile's ``site/``, constrained by :func:`kernel_pins`: a requirement that
    contradicts a version of the harness fails the resolution, and nothing is installed.
    """
    profile.runtime.mkdir(parents=True, exist_ok=True)
    constraints = profile.runtime / "install-constraints.txt"
    constraints.write_text("\n".join(kernel_pins(profile)) + "\n", encoding="utf-8")
    return [
        find_uv_bin(),
        "pip",
        "install",
        "--python",
        sys.executable,
        "--target",
        str(profile.site),
        "--upgrade",
        "--constraints",
        str(constraints),
    ]


async def _run(cmd: list[str], timeout: float = 600.0) -> tuple[int, str]:
    """Exit code and output of ``cmd``; the output is plain text (``NO_COLOR``): it is shown in the page."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"timed out after {timeout:.0f}s"
    return proc.returncode or 0, out.decode("utf-8", "replace")


def _norm(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _site_dists(profile: Profile) -> dict[str, metadata.Distribution]:
    return {_norm(d.name): d for d in profile.site_distributions()}


def _info_mtime(dist: metadata.Distribution) -> float:
    location = getattr(dist, "_path", None)
    try:
        return Path(location).stat().st_mtime if location is not None else 0.0
    except OSError:
        return 0.0


def _dist_for_path(profile: Profile, path: Path) -> metadata.Distribution | None:
    """Distribution installed from ``path``; the newest matching dist-info."""
    target = path.resolve().as_uri().rstrip("/")
    matches: list[metadata.Distribution] = []
    dists = profile.site_distributions()
    for dist in dists:
        raw = dist.read_text("direct_url.json")
        if not raw:
            continue
        try:
            if json.loads(raw).get("url", "").rstrip("/") == target:
                matches.append(dist)
        except json.JSONDecodeError:
            pass
    pool = matches or dists
    return max(pool, key=_info_mtime) if pool else None


def _prune_stale_dist_infos(profile: Profile, keep: metadata.Distribution) -> None:
    """Delete dist-info directories of older versions of ``keep``'s project; files stay."""
    keep_path = getattr(keep, "_path", None)
    for dist in profile.site_distributions():
        location = getattr(dist, "_path", None)
        if location is None or location == keep_path:
            continue
        try:
            same = _norm(dist.metadata["Name"] or "") == _norm(keep.name)
        except Exception:  # noqa: BLE001  # pragma: no cover
            same = False
        if same:
            shutil.rmtree(location, ignore_errors=True)


def unmet_requirements(dist: metadata.Distribution) -> list[str]:
    unmet = []
    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker is not None and not req.marker.evaluate({"extra": ""}):
            continue
        try:
            version = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            unmet.append(raw)
            continue
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            unmet.append(raw)
    return unmet


def remove_distribution(profile: Profile, dist: metadata.Distribution) -> list[str]:
    """Delete a distribution from the profile's ``site/``; returns the removed paths."""
    site = profile.site.resolve()
    removed: list[str] = []
    dirs: set[Path] = set()
    for file in dist.files or []:
        path = Path(dist.locate_file(file)).resolve()
        if site not in path.parents:
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed.append(str(path.relative_to(site)))
        dirs.add(path.parent)
    info_dir = getattr(dist, "_path", None)
    if info_dir is not None and Path(info_dir).exists():
        shutil.rmtree(info_dir, ignore_errors=True)
    for leaf in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        directory = leaf
        while directory != site and site in directory.parents:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent
    return removed


def _bundles_of(dist: metadata.Distribution) -> list[str]:
    return [ep.name for ep in dist.entry_points if ep.group == BUNDLE_GROUP]


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": report.get("ok"),
        "errors": report.get("errors", []),
        "pending": report.get("pending", []),
        "warnings": report.get("warnings", []),
    }


def _new_failures(report: dict[str, Any], baseline: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    errors = list(report.get("errors", []))
    if baseline is None:
        return errors
    already = {e["id"] for e in baseline if e.get("state") == "failed"}
    return [e for e in errors if e.get("entry") not in already]


class _Transaction:
    """Snapshot of the profile files and optionally the site directory."""

    def __init__(self, profile: Profile, *, site: bool) -> None:
        self.profile = profile
        self.state = profile.read_state()
        self.site_backup: Path | None = None
        if site:
            profile.site.mkdir(parents=True, exist_ok=True)
            self.site_backup = profile.runtime / f"site-backup-{os.getpid()}-{time.time_ns()}"
            shutil.copytree(profile.site, self.site_backup, symlinks=True)

    def rollback(self) -> None:
        self.profile.write_state(self.state)
        if self.site_backup is not None:
            shutil.rmtree(self.profile.site, ignore_errors=True)
            self.site_backup.replace(self.profile.site)
            self.site_backup = None
        importlib.invalidate_caches()

    def commit(self) -> None:
        if self.site_backup is not None:
            shutil.rmtree(self.site_backup, ignore_errors=True)
            self.site_backup = None


@contextlib.asynccontextmanager
async def _locked(profile: Profile) -> AsyncIterator[None]:
    async with _process_lock, profile.alock():
        yield


async def _preflight(
    profile: Profile, baseline: list[dict[str, Any]] | None, preflight: bool
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not preflight:
        return None, []
    report = await run_preflight(profile)
    return report, _new_failures(report, baseline)


def _rejected(stage: str, txn: _Transaction, **data: Any) -> dict[str, Any]:
    txn.rollback()
    return {"application": "rejected", "stage": stage, **data}


def _saved(txn: _Transaction, report: dict[str, Any] | None, **data: Any) -> dict[str, Any]:
    txn.commit()
    out: dict[str, Any] = {"application": "saved", **data}
    if report is not None:
        out["preflight"] = _compact(report)
    return out


# ---------------------------------------------------------------------- operations
async def install_bundle(
    profile: Profile,
    path: str | os.PathLike[str],
    *,
    baseline: list[dict[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        return {"application": "rejected", "stage": "install", "error": f"{source} does not exist"}
    if source.is_dir() and not (source / "pyproject.toml").exists() and not (source / "setup.py").exists():
        return {"application": "rejected", "stage": "install", "error": f"{source} has no pyproject.toml"}
    async with _locked(profile):
        profile.activate_site()
        txn = _Transaction(profile, site=True)
        try:
            code, out = await _run([*_installer(profile), "--no-deps", str(source)])
            if code != 0:
                return _rejected("install", txn, error=out[-4000:])
            dist = _dist_for_path(profile, source)
            if dist is None:
                return _rejected("install", txn, error="installed distribution not found in the profile site")
            return await _complete_install(
                profile, txn, dist, baseline=baseline, preflight=preflight, source=str(source)
            )
        except BaseException:
            txn.rollback()
            raise


REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


def requirement_name(requirement: str) -> str | None:
    """Project name of a PEP 508 requirement (``pyh-todo==0.1.0`` → ``pyh-todo``); ``None`` when it is not one."""
    match = REQUIREMENT_NAME.match(requirement)
    if not match or any(ch in requirement for ch in " /\\"):
        return None
    return match.group(1)


def looks_like_path(target: str) -> bool:
    """
    Whether an install target names a directory rather than a package: a separator, ``~``, ``.`` or an existing
    path.
    """
    return target.startswith(("/", ".", "~")) or "/" in target or "\\" in target or Path(target).expanduser().exists()


async def install_package(
    profile: Profile,
    requirement: str,
    *,
    index_url: str | None = None,
    baseline: list[dict[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    """Install a bundle from the package index (PyPI by default) into the profile site, dependencies included."""
    name = requirement_name(requirement)
    if name is None:
        return {
            "application": "rejected",
            "stage": "install",
            "error": f"{requirement!r} is not a package requirement (name, optionally with a version)",
        }
    async with _locked(profile):
        profile.activate_site()
        txn = _Transaction(profile, site=True)
        try:
            argv = _installer(profile) + ([f"--index-url={index_url}"] if index_url else []) + [requirement]
            code, out = await _run(argv)
            if code != 0:
                return _rejected("install", txn, error=out[-4000:])
            dist = _site_dists(profile).get(_norm(name))
            if dist is None:
                return _rejected("install", txn, error=f"{name} was not installed into the profile site")
            return await _complete_install(
                profile, txn, dist, baseline=baseline, preflight=preflight, source=f"package:{requirement}"
            )
        except BaseException:
            txn.rollback()
            raise


async def _complete_install(
    profile: Profile,
    txn: _Transaction,
    dist: metadata.Distribution,
    *,
    baseline: list[dict[str, Any]] | None,
    preflight: bool,
    source: str,
) -> dict[str, Any]:
    dist_name, dist_version = dist.name, dist.version
    bundles = _bundles_of(dist)
    if not bundles:
        return _rejected(
            "install",
            txn,
            error=f"{dist_name} declares no `{BUNDLE_GROUP}` entry point; a bundle must say how it is mounted",
        )
    _prune_stale_dist_infos(profile, dist)
    unmet = unmet_requirements(dist)
    if unmet:
        code, deps_output = await _run(_installer(profile) + unmet)
        if code != 0:
            return _rejected("dependencies", txn, error=deps_output[-4000:], unmet=unmet)
    for bundle in bundles:
        profile.set_bundle_enabled(bundle, True)
    outcome = {
        "dist": dist_name,
        "version": dist_version,
        "bundles": bundles,
        "dependencies_installed": unmet,
        "source": source,
    }
    report, failures = await _preflight(profile, baseline, preflight)
    if failures:
        return _rejected("preflight", txn, errors=failures, preflight=_compact(report or {}), **outcome)
    return _saved(txn, report, **outcome)


async def uninstall_bundle(
    profile: Profile,
    bundle: str,
    *,
    baseline: list[dict[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    async with _locked(profile):
        owner = next((d for d in profile.site_distributions() if bundle in _bundles_of(d)), None)
        if owner is None:
            return {
                "application": "rejected",
                "error": (
                    f"bundle {bundle!r} is not installed in profile {profile.name!r}; environment bundles: disable only"
                ),
            }
        txn = _Transaction(profile, site=True)
        try:
            owner_name = owner.name
            for name in _bundles_of(owner):
                profile.set_bundle_enabled(name, False)
            removed = remove_distribution(profile, owner)
            importlib.invalidate_caches()
            report, failures = await _preflight(profile, baseline, preflight)
            if failures:
                return _rejected("preflight", txn, errors=failures, preflight=_compact(report or {}))
            return _saved(txn, report, dist=owner_name, removed_files=len(removed))
        except BaseException:
            txn.rollback()
            raise


async def set_bundle_enabled(
    profile: Profile,
    bundle: str,
    enabled: bool,
    *,
    baseline: list[dict[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    async with _locked(profile):
        known = {b["bundle"] for b in profile.installed_bundles()}
        if enabled and bundle not in known:
            return {"application": "rejected", "error": f"bundle {bundle!r} is not installed"}
        txn = _Transaction(profile, site=False)
        try:
            changed = profile.set_bundle_enabled(bundle, enabled)
        except ConfigError as exc:
            return {"application": "rejected", "error": str(exc)}
        if not changed:
            return {"application": "unchanged", "bundle": bundle, "enabled": enabled}
        report, failures = await _preflight(profile, baseline, preflight)
        if failures:
            return _rejected("preflight", txn, errors=failures, preflight=_compact(report or {}), bundle=bundle)
        return _saved(txn, report, bundle=bundle, enabled=enabled)


async def set_entry_enabled(
    profile: Profile,
    entry_id: str,
    enabled: bool,
    *,
    baseline: list[dict[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    async with _locked(profile):
        if find(profile.compose().tree, entry_id) is None:
            return {"application": "rejected", "error": f"no entry {entry_id!r} in profile {profile.name!r}"}
        txn = _Transaction(profile, site=False)
        profile.set_entry_disabled(entry_id, not enabled)
        report, failures = await _preflight(profile, baseline, preflight)
        if failures:
            return _rejected("preflight", txn, errors=failures, preflight=_compact(report or {}), entry=entry_id)
        return _saved(txn, report, entry=entry_id, enabled=enabled)


async def set_entry_config(
    profile: Profile,
    entry_id: str,
    config: dict[str, Any],
    *,
    merge: bool = True,
    baseline: list[dict[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    """Patch an entry's ``config`` in the profile patch (see :meth:`Profile.set_entry_config`)."""
    async with _locked(profile):
        if find(profile.compose().tree, entry_id) is None:
            return {"application": "rejected", "error": f"no entry {entry_id!r} in profile {profile.name!r}"}
        txn = _Transaction(profile, site=False)
        profile.set_entry_config(entry_id, config, merge=merge)
        report, failures = await _preflight(profile, baseline, preflight)
        if failures:
            return _rejected("preflight", txn, errors=failures, preflight=_compact(report or {}), entry=entry_id)
        return _saved(txn, report, entry=entry_id)
