from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib
import os
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from .config import (
    ConfigError,
    PatchOp,
    Tree,
    compose,
    deep_merge,
    dump_yaml,
    load_yaml,
    parse_ops,
    tree_to_data,
    write_yaml,
)
from .credentials import CredentialStore
from .plugin import BUNDLE_GROUP, BundleInfo, bundle_entry_points, load_bundle
from .resources import package_toml

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX only
    fcntl = None

PATCH_HEADER = "# Patch operations addressed by entry id. Managed by pyharness; comments are not preserved.\n"

TEMPLATES: dict[str, dict[str, Any]] = package_toml(__file__)["profile"]["TEMPLATES"]  # name -> title, bundles


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
        self.credentials_path = self.dir / "credentials.yaml"
        self.documents = Path.home() / "Documents" / "pyharness" / name

    @property
    def credentials(self) -> CredentialStore:
        return CredentialStore(self.credentials_path)

    # ------------------------------------------------------------------ creation
    def exists(self) -> bool:
        return self.manifest_path.exists()

    @classmethod
    def init(
        cls, name: str = "web", template: str | None = None, home: str | None = None, *, force: bool = False
    ) -> Profile:
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

    def require(self) -> Profile:
        if not self.exists():
            raise ConfigError(
                f"profile {self.name!r} does not exist under {self.home}; create: `pyh init --profile {self.name}`"
            )
        return self

    # ------------------------------------------------------------------ manifest
    def manifest(self) -> dict[str, Any]:
        data = load_yaml(self.manifest_path, default={}) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{self.manifest_path} must be a mapping")
        data.setdefault("bundles", [])
        data.setdefault("disabled", [])
        return data

    def save_manifest(self, data: dict[str, Any]) -> None:
        write_yaml(self.manifest_path, data)

    def bundles(self) -> list[str]:
        """
        Enabled bundles in composition order: the manifest's ``bundles``, then the built-in environment bundles
        (``builtin: true``, always on), then the optional ones (``optional: true``) not listed under ``disabled``.
        """
        data = self.manifest()
        explicit = [str(b) for b in data.get("bundles", [])]
        disabled = {str(b) for b in data.get("disabled", [])}
        builtin = [b for b in self.builtin_bundles() if b not in explicit]
        return (
            explicit
            + builtin
            + [b for b in self.optional_bundles() if b not in explicit and b not in builtin and b not in disabled]
        )

    def _flagged_bundles(self, flag: str) -> list[str]:
        self.activate_site()
        names = []
        for name in sorted(bundle_entry_points()):
            try:
                if getattr(load_bundle(name), flag):
                    names.append(name)
            except Exception:  # noqa: BLE001 — a broken bundle is reported where it is loaded
                continue
        return names

    def optional_bundles(self) -> list[str]:
        """Installed bundles declared ``optional: true``: on by default, switched off through ``disabled``."""
        return self._flagged_bundles("optional")

    def builtin_bundles(self) -> list[str]:
        """Installed bundles declared ``builtin: true``: part of every profile, never switched off."""
        return self._flagged_bundles("builtin")

    def bundle_meta(self, name: str) -> dict[str, Any]:
        try:
            info = load_bundle(name)
        except Exception as exc:  # noqa: BLE001
            return {
                "title": name,
                "description": "",
                "optional": False,
                "builtin": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "title": info.title,
            "description": info.description,
            "optional": info.optional,
            "builtin": info.builtin,
        }

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
        importlib.invalidate_caches()

    def variables(self, cwd: str | None = None) -> dict[str, str]:
        return {
            "profile": self.name,
            "profile_dir": str(self.dir),
            "home": str(self.home),
            "data_dir": str(self.data),
            "runtime_dir": str(self.runtime),
            "cwd": cwd or os.environ.get("PYH_CWD") or str(Path.cwd()),
        }

    # ------------------------------------------------------------------ composition
    def layers(
        self, extra_patches: list[Path] | None = None
    ) -> tuple[list[tuple[str, list[PatchOp]]], list[BundleInfo]]:
        layers: list[tuple[str, list[PatchOp]]] = []
        infos: list[BundleInfo] = []
        for bundle in self.bundles():
            info = load_bundle(bundle)
            infos.append(info)
            layers.append((f"bundle:{bundle}", info.ops))
        layers.append(("profile-patch", parse_ops(self.patch_ops_raw(), str(self.patch_path))))
        layers.append(("home-patch", parse_ops(load_yaml(self.home_patch_path, default=[]), str(self.home_patch_path))))
        layers.extend(
            (f"patch:{path}", parse_ops(load_yaml(Path(path), default=[]), str(path))) for path in extra_patches or []
        )
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

    def set_entry_config(self, entry_id: str, config: dict[str, Any], *, merge: bool = True) -> None:
        """
        Patch an entry's ``config`` in the profile patch.

        The entry's last op is reused: with ``merge`` the new keys are deep-merged into its
        ``config``; otherwise its ``config`` is replaced. Without an op, ``{id, config, merge}`` is appended.
        """
        ops = self.patch_ops_raw()
        for op in reversed(ops):
            if isinstance(op, dict) and op.get("id") == entry_id and not op.get("remove"):
                existing = op.get("config")
                if merge and isinstance(existing, dict):
                    op["config"] = deep_merge(existing, config)
                else:
                    op["config"] = copy.deepcopy(config)
                    op["merge"] = merge
                break
        else:
            ops.append({"id": entry_id, "config": copy.deepcopy(config), "merge": merge})
        self.save_patch(ops)

    def set_bundle_enabled(self, bundle: str, enabled: bool) -> bool:
        """
        Enable or disable a bundle: optional bundles move in and out of ``disabled``, others in and out of
        ``bundles``.
        A built-in bundle (``builtin: true``) is always on: disabling it raises :class:`ConfigError`.
        """
        if not enabled and bundle in self.builtin_bundles():
            raise ConfigError(f"bundle {bundle!r} is built in and cannot be disabled")
        data = self.manifest()
        bundles = [str(b) for b in data.get("bundles", [])]
        disabled = [str(b) for b in data.get("disabled", [])]
        optional = bundle in self.optional_bundles()
        changed = False
        if enabled:
            if bundle in disabled:
                disabled.remove(bundle)
                changed = True
            if not optional and bundle not in bundles:
                bundles.append(bundle)
                changed = True
        else:
            if bundle in bundles:
                bundles.remove(bundle)
                changed = True
            if optional and bundle not in disabled:
                disabled.append(bundle)
                changed = True
        if changed:
            data["bundles"] = bundles
            data["disabled"] = disabled
            self.save_manifest(data)
        return changed

    def site_distributions(self) -> list[metadata.Distribution]:
        if not self.site.exists():
            return []
        return list(metadata.distributions(path=[str(self.site)]))

    def installed_bundles(self) -> list[dict[str, Any]]:
        """
        Bundles of the profile site and the environment: ``enabled``, ``installed`` (``profile`` / ``environment``),
        ``optional``, ``builtin``, ``title``, ``description``.
        """
        enabled = set(self.bundles())
        out = []
        seen: set[str] = set()
        for dist in self.site_distributions():
            for ep in dist.entry_points:
                if ep.group == BUNDLE_GROUP and ep.name not in seen:
                    seen.add(ep.name)
                    out.append(
                        {
                            "bundle": ep.name,
                            "dist": dist.name,
                            "version": dist.version,
                            "enabled": ep.name in enabled,
                            "installed": "profile",
                            **self.bundle_meta(ep.name),
                        }
                    )
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
                    **self.bundle_meta(ep.name),
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
        """
        Save ``state`` as last-known-good; default: the current files.

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
        with lock_path.open("w") as fh:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX)
            yield

    @contextlib.asynccontextmanager
    async def alock(self, poll: float = 0.1) -> AsyncIterator[None]:
        """:meth:`lock` for async code; waits by polling."""
        self.runtime.mkdir(parents=True, exist_ok=True)
        lock_path = self.runtime / "profile.lock"
        with lock_path.open("w") as fh:
            if fcntl is None:  # pragma: no cover
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
        result = self.compose(extra_patches)
        return dump_yaml(tree_to_data(result.tree, with_source=True))
