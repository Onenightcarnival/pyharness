"""Model catalog of the gateway: every model of every route as ``provider:model``, and alias resolution.

| name            | contract                                                                             |
|-----------------|--------------------------------------------------------------------------------------|
| ``list()``      | ``{id, provider, providerName, model, name}`` of every model the routes offer        |
| ``resolve()``   | a request's model name → ``Target``: an alias first, then a ``provider:model`` id of a known route |

A request names its model; an absent name or one of an unknown route raises :class:`ModelResolutionError`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

SEPARATOR = ":"
HINT = "use a provider:model id from GET /v1/models"


class ModelResolutionError(LookupError):
    """The request names no model, or one of an unknown route."""


@dataclass(frozen=True)
class Target:
    provider: str
    model: str

    @property
    def id(self) -> str:
        return f"{self.provider}{SEPARATOR}{self.model}"


def split_id(model_id: str) -> Target | None:
    """Split ``provider:model`` at the first separator; ``None`` when either side is empty."""
    provider, sep, model = model_id.partition(SEPARATOR)
    return Target(provider, model) if sep and provider and model else None


class ModelCatalog:
    """``groups()`` are the route groups of ``ctx.llm.directory()``; ``routes()`` the configured route ids."""

    def __init__(
        self,
        groups: Callable[[], Iterable[Mapping[str, Any]]],
        routes: Callable[[], Iterable[str]],
        settings: Callable[[], Mapping[str, Any]],
    ) -> None:
        self._groups = groups
        self._routes = routes
        self._settings = settings

    def list(self) -> list[dict[str, str]]:
        return [
            {
                "id": f"{group['id']}{SEPARATOR}{model['id']}",
                "provider": group["id"],
                "providerName": group.get("title") or group["id"],
                "model": model["id"],
                "name": model.get("name") or model["id"],
            }
            for group in self._groups()
            for model in group.get("models") or []
        ]

    def resolve(self, requested: Any) -> Target:
        name = requested.strip() if isinstance(requested, str) else ""
        if not name:
            raise ModelResolutionError(f"the request names no model; {HINT}")
        target = split_id(self._settings()["aliases"].get(name, name))
        known = {*self._routes(), *(group["id"] for group in self._groups())}
        if target is None or target.provider not in known:
            raise ModelResolutionError(f'unknown model "{name}"; {HINT}')
        return target
