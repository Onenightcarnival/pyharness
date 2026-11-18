from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission

DEFAULT_WORKSPACE = "default-workspace"


class WorkspaceError(ValueError):
    """A path cannot be a workspace."""


class Workspace:
    def __init__(self, root: Path, virtual_mode: bool, protected: list[Path] | None = None) -> None:
        self.root = root
        self.virtual_mode = virtual_mode
        self.protected = list(protected or [])

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)

    def resolve(self, path: str) -> Path:
        """Real path of an agent path (``/notes/x``); raises ``ValueError`` outside the root or inside the home."""
        raw = Path(path)
        candidate = (
            (self.root / str(path).lstrip("/")).resolve()
            if self.virtual_mode or not raw.is_absolute()
            else raw.resolve()
        )
        if self.virtual_mode and candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"{path!r} escapes the workspace root")
        for guarded in self.protected:
            if candidate == guarded or guarded in candidate.parents:
                raise ValueError(f"{path!r} is inside the harness home: access denied")
        return candidate

    def permissions(self) -> list[Any]:
        """deepagents ``FilesystemPermission`` rules: deny read and write on protected paths."""
        rules = []
        for guarded in self.protected:
            base = "/" + guarded.relative_to(self.root).as_posix() if self.virtual_mode else guarded.as_posix()
            rules.append(
                FilesystemPermission(operations=["read", "write"], paths=[base, base.rstrip("/") + "/**"], mode="deny")
            )
        return rules

    def describe(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "name": self.name,
            "virtual_mode": self.virtual_mode,
            "protected": [str(p) for p in self.protected],
        }
