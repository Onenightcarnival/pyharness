"""User skills: ``<profile data>/toolkit/skills/<name>/SKILL.md`` (enabled, mounted for the agent at ``/skills/user/``)
and ``<profile data>/toolkit/disabled-skills/`` (kept, not mounted). Install from ZIP, enable / disable by moving the
directory, remove, read files."""

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

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^﻿?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)")
ZIP_LIMIT = 32 * 1024 * 1024
EXPAND_LIMIT = 100 * 1024 * 1024
ENTRY_LIMIT = 4000
PREVIEW_LIMIT = 256 * 1024
WALK_DEPTH = 12
WALK_ENTRIES = 400
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class SkillError(ValueError):
    pass


def valid_name(name: str) -> bool:
    return bool(name) and len(name) <= 64 and bool(NAME_RE.match(name))


def normalize_name(raw: str) -> str:
    base = re.sub(r"\.(zip|md)$", "", raw.lower())
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", base))


def fenced(root: Path, rel: str) -> Path:
    """``root / rel`` when every part is a plain name and no symlink sits on the way."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    for part in parts:
        if (
            part in (".", "..")
            or ":" in part
            or any(ord(c) < 32 for c in part)
            or part[-1] in ". "
            or part.lower().split(".")[0] in RESERVED
        ):
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
        with open(file, "rb") as f:
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

    def install_zip(self, data: bytes, filename: str, policy: str = "ask") -> dict[str, Any]:
        """Install the skills of a ZIP: a root ``SKILL.md`` (one skill named after the file), ``<dir>/SKILL.md``
        bundles,
        and top-level ``*.md`` files (each becomes ``<name>/SKILL.md``). ``policy``: ask (report conflicts, write
        nothing), skip (keep existing), replace (overwrite and enable)."""
        if len(data) > ZIP_LIMIT:
            raise SkillError("ZIP size limit: 32 MB")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise SkillError("not a ZIP file") from exc
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > ENTRY_LIMIT or sum(i.file_size for i in infos) > EXPAND_LIMIT:
            raise SkillError("extracted contents exceed the limit")
        names = [i.filename.replace("\\", "/") for i in infos]
        for n in names:
            if n.startswith("/") or ".." in n.split("/"):
                raise SkillError("invalid path")
        candidates: dict[str, list[tuple[str, zipfile.ZipInfo]]] = {}
        if "SKILL.md" in names:
            skill = normalize_name(filename)
            if not valid_name(skill):
                raise SkillError("invalid skill name")
            candidates[skill] = [(n, i) for n, i in zip(names, infos, strict=True)]
        else:
            for n, i in zip(names, infos, strict=True):
                parts = n.split("/")
                top = parts[0]
                if len(parts) >= 2 and not top.startswith(".") and top != "__MACOSX":
                    if f"{top}/SKILL.md" in names:
                        skill = normalize_name(top)
                        if skill in candidates or valid_name(skill):
                            candidates.setdefault(skill, []).append(("/".join(parts[1:]), i))
                elif len(parts) == 1 and n.lower().endswith(".md") and n.lower() != "readme.md":
                    skill = normalize_name(n)
                    if valid_name(skill):
                        candidates[skill] = [("SKILL.md", i)]
        candidates = {k: v for k, v in candidates.items() if valid_name(k)}
        if not candidates:
            raise SkillError("no skills found in ZIP")
        conflicts = sorted(k for k in candidates if self.exists(k))
        if conflicts and policy == "ask":
            return {"installed": [], "skipped": [], "conflicts": conflicts}
        installed, skipped = [], []
        for skill, members in candidates.items():
            if skill in conflicts and policy == "skip":
                skipped.append(skill)
                continue
            stage = Path(tempfile.mkdtemp(prefix=".install-", dir=self.disabled_dir))
            try:
                for rel, info in members:
                    if not rel:
                        continue
                    dest = fenced(stage, rel)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(dest, "wb") as out:
                        head = src.read(2)
                        out.write(head)
                        shutil.copyfileobj(src, out)
                    if head == b"#!":
                        os.chmod(dest, 0o755)
                target = self.enabled_dir / skill
                backup = None
                if skill in conflicts:
                    old = (
                        (self.enabled_dir / skill)
                        if (self.enabled_dir / skill).exists()
                        else (self.disabled_dir / skill)
                    )
                    backup = old.with_name(f".{skill}.backup")
                    if backup.exists():
                        shutil.rmtree(backup)
                    shutil.move(str(old), str(backup))
                try:
                    shutil.move(str(stage), str(target))
                except Exception:
                    if backup is not None:
                        shutil.move(str(backup), str(target))
                    raise
                if backup is not None and backup.exists():
                    shutil.rmtree(backup)
                installed.append(skill)
            finally:
                if stage.exists():
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
