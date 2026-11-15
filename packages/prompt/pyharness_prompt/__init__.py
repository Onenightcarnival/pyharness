from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyharness import Service


@dataclass
class Section:
    id: str
    content: str | Callable[[], str]
    order: int
    owner: str
    seq: int
    presets: tuple[str, ...] | None = None

    def applies(self, preset: str | None) -> bool:
        return self.presets is None or preset is None or preset in self.presets

    def render(self) -> str:
        text = self.content() if callable(self.content) else self.content
        return (text or "").strip()


class PromptService(Service):
    """Ordered system-prompt sections."""

    key = "prompt"
    name = "pyharness-prompt"

    def __init__(self, ctx: Any, config: Any) -> None:
        super().__init__(ctx, config)
        self._sections: dict[str, Section] = {}
        self._seq = 0

    def add(
        self, id: str, content: str | Callable[[], str], order: int = 100, presets: list[str] | None = None
    ) -> Callable[[], Any]:
        """
        Add a section; ``content`` is text or a zero-argument callable; ``presets`` limits it to those agent
        presets. Returns the disposer.
        """
        if id in self._sections:
            raise ValueError(f"prompt section {id!r} already added by {self._sections[id].owner!r}")
        self._seq += 1
        section = Section(
            id=id,
            content=content,
            order=order,
            owner=self.caller.entry_id,
            seq=self._seq,
            presets=tuple(presets) if presets else None,
        )
        self._sections[id] = section
        return self.caller.on_dispose(lambda: self._sections.pop(id, None))

    def sections(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "order": s.order,
                "owner": s.owner,
                "chars": len(s.render()),
                "presets": list(s.presets) if s.presets else None,
            }
            for s in sorted(self._sections.values(), key=lambda s: (s.order, s.seq))
        ]

    def render(self, preset: str | None = None) -> str:
        parts = [
            s.render() for s in sorted(self._sections.values(), key=lambda s: (s.order, s.seq)) if s.applies(preset)
        ]
        return "\n\n".join(p for p in parts if p)


__all__ = ["PromptService", "Section"]
