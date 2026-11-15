from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml

FRONTMATTER_RE = re.compile(r"^﻿?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)")
ZIP_LIMIT = 32 * 1024 * 1024
EXPAND_LIMIT = 100 * 1024 * 1024
ENTRY_LIMIT = 4000
PREVIEW_LIMIT = 256 * 1024
WALK_DEPTH = 12
WALK_ENTRIES = 400
NAME_LIMIT = 128
UNIX_HOSTS = (3, 19)  # ``create_system`` of archives written on Unix and macOS
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class SkillError(ValueError):
    pass


def unsafe_part(part: str) -> bool:
    """A path segment that is empty, relative, or not portable across file systems."""
    return (
        part in ("", ".", "..")
        or ":" in part
        or any(ord(c) < 32 for c in part)
        or part[-1] in ". "
        or part.lower().split(".")[0] in RESERVED
    )


def valid_name(name: str) -> bool:
    return (
        len(name) <= NAME_LIMIT and not name.startswith(".") and not re.search(r"[\\/]", name) and not unsafe_part(name)
    )


def fenced(root: Path, rel: str) -> Path:
    """``root / rel`` when every part is a plain name and no symlink sits on the way."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if any(unsafe_part(part) for part in parts):
        raise SkillError("invalid path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise SkillError("symbolic links are not supported")
    return path


def parse_frontmatter(text: str) -> dict[str, Any]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def describe(text: str) -> tuple[str, str, dict[str, Any]]:
    fm = parse_frontmatter(text)
    description = str(fm.get("description") or "").strip()
    if not description:
        body = FRONTMATTER_RE.sub("", text, count=1)
        description = next(
            (
                line.strip()
                for line in body.splitlines()
                if line.strip() and not line.startswith("#") and not line.startswith("---")
            ),
            "",
        )
    version = fm.get("version")
    if version is None and isinstance(fm.get("metadata"), dict):
        version = fm["metadata"].get("version")
    return description[:2000], "" if version is None else str(version), fm


def entry_path(info: zipfile.ZipInfo) -> str:
    """Archive entry path with ``/`` separators; a UTF-8 name stored without the ZIP UTF-8 flag is decoded."""
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("utf-8")
        except UnicodeError:
            name = info.filename
    return re.sub(r"^(?:\./)+", "", name.replace("\\", "/"))


def is_executable(info: zipfile.ZipInfo) -> bool:
    """The archive records a Unix mode with an executable bit for a regular file."""
    mode = info.external_attr >> 16
    return info.create_system in UNIX_HOSTS and mode & 0o170000 != 0o120000 and bool(mode & 0o111)


class SkillStore:
    def __init__(self, base: Path) -> None:
        self.enabled_dir = base / "skills"
        self.disabled_dir = base / "disabled-skills"
        self.enabled_dir.mkdir(parents=True, exist_ok=True)
        self.disabled_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ reads
    def _scan(self, root: Path, enabled: bool) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not root.is_dir():
            return out
        for entry in sorted(root.iterdir()):
            if entry.name.startswith(".") or not valid_name(entry.name) or entry.is_symlink():
                continue
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                try:
                    text = (entry / "SKILL.md").read_text("utf-8", "replace")
                except OSError:
                    continue
                description, version, _ = describe(text)
                out[entry.name] = {
                    "name": entry.name,
                    "description": description,
                    "version": version,
                    "kind": "bundle",
                    "enabled": enabled,
                }
        return out

    def list(self) -> list[dict[str, Any]]:
        skills = self._scan(self.disabled_dir, False)
        skills.update(self._scan(self.enabled_dir, True))  # an enabled copy wins
        return [skills[k] for k in sorted(skills)]

    def locate(self, name: str) -> tuple[Path, bool]:
        if not valid_name(name):
            raise SkillError("invalid skill name")
        for root, enabled in ((self.enabled_dir, True), (self.disabled_dir, False)):
            path = fenced(root, name)
            if path.is_dir() and (path / "SKILL.md").is_file():
                return path, enabled
        raise SkillError("skill not found")

    def detail(self, name: str) -> dict[str, Any]:
        path, enabled = self.locate(name)
        text = (path / "SKILL.md").read_text("utf-8", "replace")
        description, version, fm = describe(text)
        files: list[dict[str, Any]] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(path):
            rel_dir = Path(dirpath).relative_to(path)
            if len(rel_dir.parts) >= WALK_DEPTH:
                dirnames[:] = []
            dirnames[:] = sorted(
                d for d in dirnames if d not in (".git", "node_modules") and not (Path(dirpath) / d).is_symlink()
            )
            for fn in sorted(filenames):
                fp = Path(dirpath) / fn
                if fp.is_symlink():
                    continue
                if len(files) >= WALK_ENTRIES:
                    truncated = True
                    break
                files.append({"path": str((rel_dir / fn).as_posix()), "size": fp.stat().st_size})
            if truncated:
                break
        return {
            "name": name,
            "description": description,
            "version": version,
            "kind": "bundle",
            "enabled": enabled,
            "path": str(path),
            "entryFile": "SKILL.md",
            "frontmatter": fm,
            "files": files,
            "truncated": truncated,
        }

    def read_file(self, name: str, rel: str) -> dict[str, Any]:
        path, _ = self.locate(name)
        file = fenced(path, rel)
        if not file.is_file():
            raise SkillError("not a file")
        size = file.stat().st_size
        with file.open("rb") as f:
            data = f.read(PREVIEW_LIMIT + 1)
        if b"\0" in data:
            raise SkillError("binary file cannot be previewed")
        return {
            "text": data[:PREVIEW_LIMIT].decode("utf-8", "replace"),
            "size": size,
            "truncated": size > PREVIEW_LIMIT,
        }

    # ------------------------------------------------------------------ writes
    def set_enabled(self, name: str, enabled: bool) -> None:
        path, current = self.locate(name)
        if current == enabled:
            return
        target = (self.enabled_dir if enabled else self.disabled_dir) / name
        if target.exists():
            raise SkillError("a skill with this name exists at the destination")
        shutil.move(str(path), str(target))

    def remove(self, name: str) -> None:
        if not valid_name(name):
            raise SkillError("invalid skill name")
        found = False
        for root in (self.enabled_dir, self.disabled_dir):
            path = fenced(root, name)
            if path.is_dir():
                shutil.rmtree(path)
                found = True
        if not found:
            raise SkillError("skill not found")

    def exists(self, name: str) -> bool:
        return any((root / name).is_dir() for root in (self.enabled_dir, self.disabled_dir))

    def _occupants(self, name: str) -> list[Path]:
        """Existing entries named ``name`` in the enabled and the disabled directory."""
        return [root / name for root in (self.enabled_dir, self.disabled_dir) if os.path.lexists(root / name)]

    def install_zip(self, data: bytes, policy: str = "ask") -> dict[str, Any]:
        """
        Extract a ZIP into the enabled directory (the rules of the module table). ``policy``: ask (report
        conflicts, write nothing), skip (keep existing entries), replace (overwrite).
        """
        if len(data) > ZIP_LIMIT:
            raise SkillError("ZIP size limit: 32 MB")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise SkillError("not a ZIP file") from exc
        infos = zf.infolist()
        if len(infos) > ENTRY_LIMIT or sum(i.file_size for i in infos) > EXPAND_LIMIT:
            raise SkillError("extracted contents exceed the limit")
        directories: list[str] = []
        files: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            path = entry_path(info)
            if not path or "__MACOSX" in path.split("/"):
                continue
            fenced(self.enabled_dir, path)
            if info.is_dir():
                directories.append(path.rstrip("/"))
            else:
                files[path] = info
        # Top-level entry -> install name.
        units: dict[str, str] = {}
        for path in [*directories, *files]:
            top = path.split("/")[0]
            units[top] = top[:-3] if top == path and path in files and top.endswith(".md") else top
        if not units:
            raise SkillError("no files to extract in ZIP")
        seen: set[str] = set()
        for name in units.values():
            if not valid_name(name):
                raise SkillError("invalid skill name")
            if name.lower() in seen:
                raise SkillError(f"duplicate skill name in ZIP: {name}")
            seen.add(name.lower())
        occupants = {top: self._occupants(name) for top, name in units.items()}
        conflicts = [name for top, name in units.items() if occupants[top]]
        if conflicts and policy == "ask":
            return {"installed": [], "skipped": [], "conflicts": conflicts}
        installed, skipped = [], []
        stage = Path(tempfile.mkdtemp(prefix=".install-", dir=self.disabled_dir))
        extracted, replaced = stage / "new", stage / "old"
        keep_stage = False
        try:
            # Complete extraction before replacing installed entries.
            replaced.mkdir()
            for path in directories:
                fenced(extracted, path).mkdir(parents=True, exist_ok=True)
            for path, info in files.items():
                dest = fenced(extracted, path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                if sys.platform != "win32" and is_executable(info):
                    dest.chmod(0o755)
            for top, name in units.items():
                if name in conflicts and policy == "skip":
                    skipped.append(name)
                    continue
                backups: list[tuple[Path, Path]] = []
                try:
                    for path in occupants[top]:
                        backup = replaced / f"{len(backups)}-{name}"
                        shutil.move(path, backup)
                        backups.append((backup, path))
                    target = self.enabled_dir / name
                    if name == top:
                        shutil.move(extracted / top, target)
                    else:  # a top-level markdown file becomes the entry file of its own bundle
                        target.mkdir()
                        shutil.move(extracted / top, target / "SKILL.md")
                    installed.append(name)
                except Exception:
                    try:
                        for backup, original in reversed(backups):
                            shutil.rmtree(original, ignore_errors=True)
                            shutil.move(backup, original)
                    except OSError as restore:
                        keep_stage = True
                        raise SkillError(f"restore failed; the previous files are kept in {stage}") from restore
                    raise
        finally:
            if not keep_stage:
                shutil.rmtree(stage, ignore_errors=True)
        return {"installed": installed, "skipped": skipped, "conflicts": []}

    def open_folder(self, name: str | None) -> None:
        path = self.locate(name)[0] if name else self.enabled_dir
        opener = (
            ["open", str(path)]
            if sys.platform == "darwin"
            else ["explorer.exe", str(path)]
            if sys.platform == "win32"
            else ["xdg-open", str(path)]
        )
        subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
