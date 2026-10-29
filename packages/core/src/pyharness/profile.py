"""Profiles: named, persistent assemblies in the harness home.

``$PYH_HOME`` (default ``~/.pyharness``)::

    $PYH_HOME/
      harness.patch.yaml       home patch, every profile
      profiles/<name>/
        profile.yaml           ordered bundle list
        harness.patch.yaml     profile patch; written by plugin_manager
        site/                  bundles installed into this profile (pip --target)
        data/                  default SQLite location
        runtime/               ready markers, hand-off files, last-known-good, locks
"""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from .config import ConfigError, PatchOp, Tree, compose, dump_yaml, load_yaml, parse_ops, write_yaml
from .plugin import BUNDLE_GROUP, BundleInfo, load_bundle

PATCH_HEADER = "# Patch operations addressed by entry id. Managed by pyharness; comments are not preserved.\n"

TEMPLATES: dict[str, dict[str, Any]] = {
    "web": {"title": "Web", "bundles": ["base"]},
    "empty": {"title": "Empty", "bundles": []},
}


def harness_home(home: str | os.PathLike[str] | None = None) -> Path:
    raw = home or os.environ.get("PYH_HOME") or "~/.pyharness"
    return Path(raw).expanduser().resolve()


@dataclass
class ComposeResult:
    tree: Tree
    warnings: list[str]
    layers: list[tuple[str, list[PatchOp]]]
    bundles: list[BundleInfo]


class Profile:
    def __init__(self, name: str = "web", home: str | os.PathLike[str] | None = None) -> None:
        if not name or "/" in name or name.startswith("."):
            raise ConfigError(f"invalid profile name {name!r}")
        self.name = name
        self.home = harness_home(home)
        self.dir = self.home / "profiles" / name
        self.manifest_path = self.dir / "profile.yaml"
        self.patch_path = self.dir / "harness.patch.yaml"
        self.home_patch_path = self.home / "harness.patch.yaml"
        self.site = self.dir / "site"
        self.data = self.dir / "data"
        self.runtime = self.dir / "runtime"
        self.lkg = self.runtime / "last-known-good"

    # ------------------------------------------------------------------ creation
    def exists(self) -> bool:
        return self.manifest_path.exists()

    @classmethod
    def init(cls, name: str = "web", template: str | None = None, home: str | None = None, *, force: bool = False) -> "Profile":
        profile = cls(name, home)
        if profile.exists() and not force:
            return profile
        tpl = TEMPLATES.get(template or name) or TEMPLATES["web"]
        for path in (profile.site, profile.data, profile.runtime):
            path.mkdir(parents=True, exist_ok=True)
        write_yaml(profile.manifest_path, {"title": tpl["title"], "bundles": list(tpl["bundles"])})
        if not profile.patch_path.exists() or force:
            profile.patch_path.write_text(PATCH_HEADER + "[]\n", encoding="utf-8")
        return profile

    def require(self) -> "Profile":
        if not self.exists():
            raise ConfigError(f"profile {self.name!r} does not exist under {self.home}; create: `pyh init --profile {self.name}`")
        return self

    # ------------------------------------------------------------------ manifest
    def manifest(self) -> dict[str, Any]:
        data = load_yaml(self.manifest_path, default={}) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{self.manifest_path} must be a mapping")
        data.setdefault("bundles", [])
        return data

    def save_manifest(self, data: dict[str, Any]) -> None:
        write_yaml(self.manifest_path, data)

    def bundles(self) -> list[str]:
        return [str(b) for b in self.manifest().get("bundles", [])]

    def patch_ops_raw(self) -> list[dict[str, Any]]:
        data = load_yaml(self.patch_path, default=[]) or []
        if not isinstance(data, list):
            raise ConfigError(f"{self.patch_path} must be a YAML list")
        return data

    def save_patch(self, ops: list[dict[str, Any]]) -> None:
        write_yaml(self.patch_path, ops, header=PATCH_HEADER)

    # ------------------------------------------------------------------ environment
    def activate_site(self) -> None:
        """Append ``site/`` to ``sys.path`` (lowest priority)."""
        site = str(self.site)
        self.site.mkdir(parents=True, exist_ok=True)
        if site not in sys.path:
            sys.path.append(site)
        import importlib

        importlib.invalidate_caches()

    def variables(self, cwd: str | None = None) -> dict[str, str]:
        return {
            "profile": self.name,
            "profile_dir": str(self.dir),
            "home": str(self.home),
            "data_dir": str(self.data),
            "runtime_dir": str(self.runtime),
            "cwd": cwd or os.environ.get("PYH_CWD") or os.getcwd(),
        }

    # ------------------------------------------------------------------ composition
    def layers(self, extra_patches: list[Path] | None = None) -> tuple[list[tuple[str, list[PatchOp]]], list[BundleInfo]]:
        layers: list[tuple[str, list[PatchOp]]] = []
        infos: list[BundleInfo] = []
        for bundle in self.bundles():
            info = load_bundle(bundle)
            infos.append(info)
            layers.append((f"bundle:{bundle}", info.ops))
        layers.append(("profile-patch", parse_ops(self.patch_ops_raw(), str(self.patch_path))))
        layers.append(("home-patch", parse_ops(load_yaml(self.home_patch_path, default=[]), str(self.home_patch_path))))
        for path in extra_patches or []:
            layers.append((f"patch:{path}", parse_ops(load_yaml(Path(path), default=[]), str(path))))
        return layers, infos

    def compose(self, extra_patches: list[Path] | None = None) -> ComposeResult:
        self.activate_site()
        layers, infos = self.layers(extra_patches)
        tree, warnings = compose(layers)
        return ComposeResult(tree=tree, warnings=warnings, layers=layers, bundles=infos)

    # ------------------------------------------------------------------ mutations
    def set_entry_disabled(self, entry_id: str, disabled: bool) -> None:
        ops = self.patch_ops_raw()
        for op in reversed(ops):
            if isinstance(op, dict) and op.get("id") == entry_id and not op.get("remove"):
                op["disabled"] = disabled
                break
        else:
            ops.append({"id": entry_id, "disabled": disabled})
        self.save_patch(ops)

    def set_bundle_enabled(self, bundle: str, enabled: bool) -> bool:
        data = self.manifest()
        bundles = [str(b) for b in data.get("bundles", [])]
        changed = False
        if enabled and bundle not in bundles:
            bundles.append(bundle)
            changed = True
        elif not enabled and bundle in bundles:
            bundles.remove(bundle)
            changed = True
        if changed:
            data["bundles"] = bundles
            self.save_manifest(data)
        return changed

    def site_distributions(self) -> list[metadata.Distribution]:
        if not self.site.exists():
            return []
        return list(metadata.distributions(path=[str(self.site)]))

    def installed_bundles(self) -> list[dict[str, Any]]:
        enabled = set(self.bundles())
        out = []
        seen: set[str] = set()
        for dist in self.site_distributions():
            for ep in dist.entry_points:
                if ep.group == BUNDLE_GROUP and ep.name not in seen:
                    seen.add(ep.name)
                    out.append({"bundle": ep.name, "dist": dist.name, "version": dist.version, "enabled": ep.name in enabled, "installed": "profile"})
        for ep in metadata.entry_points(group=BUNDLE_GROUP):
            if ep.name in seen:
                continue
            seen.add(ep.name)
            dist = ep.dist
            out.append(
                {
                    "bundle": ep.name,
                    "dist": dist.name if dist else None,
                    "version": dist.version if dist else None,
                    "enabled": ep.name in enabled,
                    "installed": "environment",
                }
            )
        return out

    # ------------------------------------------------------------------ snapshots
    def _state_files(self) -> list[Path]:
        return [self.manifest_path, self.patch_path]

    def read_state(self) -> dict[str, str | None]:
        return {str(p): (p.read_text(encoding="utf-8") if p.exists() else None) for p in self._state_files()}

    def write_state(self, state: dict[str, str | None]) -> None:
        for raw_path, text in state.items():
            path = Path(raw_path)
            if text is None:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

    def save_last_known_good(self, state: dict[str, str | None] | None = None) -> None:
        """Save ``state`` as last-known-good; default: the current files.

        The worker passes the state it read before composing.
        """
        state = state if state is not None else self.read_state()
        self.lkg.mkdir(parents=True, exist_ok=True)
        for raw_path, text in state.items():
            target = self.lkg / Path(raw_path).name
            if text is None:
                target.unlink(missing_ok=True)
            else:
                target.write_text(text, encoding="utf-8")

    def last_known_good(self) -> dict[str, str | None] | None:
        if not self.lkg.exists():
            return None
        out: dict[str, str | None] = {}
        for path in self._state_files():
            saved = self.lkg / path.name
            out[str(path)] = saved.read_text(encoding="utf-8") if saved.exists() else None
        return out

    def restore_last_known_good(self) -> bool:
        """Restore last-known-good; returns ``False`` when the files already match."""
        saved = self.last_known_good()
        if saved is None or saved == self.read_state():
            return False
        self.write_state(saved)
        return True

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive cross-process lock on the profile (``flock``; no-op without ``fcntl``)."""
        self.runtime.mkdir(parents=True, exist_ok=True)
        lock_path = self.runtime / "profile.lock"
        with open(lock_path, "w") as fh:
            try:
                import fcntl

                fcntl.flock(fh, fcntl.LOCK_EX)
            except ImportError:  # pragma: no cover
                pass
            yield

    @contextlib.asynccontextmanager
    async def alock(self, poll: float = 0.1) -> AsyncIterator[None]:
        """:meth:`lock` for async code; waits by polling."""
        import asyncio

        self.runtime.mkdir(parents=True, exist_ok=True)
        lock_path = self.runtime / "profile.lock"
        with open(lock_path, "w") as fh:
            try:
                import fcntl
            except ImportError:  # pragma: no cover
                yield
                return
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(poll)
            yield

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "dir": str(self.dir), "bundles": self.bundles(), "home": str(self.home)}

    def dump(self, extra_patches: list[Path] | None = None) -> str:
        from .config import tree_to_data

        result = self.compose(extra_patches)
        return dump_yaml(tree_to_data(result.tree, with_source=True))
