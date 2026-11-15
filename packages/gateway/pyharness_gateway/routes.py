"""
Management routes under ``/api/gateway`` for the API gateway page.

| request                                   | response                                                       |
|-------------------------------------------|----------------------------------------------------------------|
| ``GET status``                            | settings, listener state, model list, key list                 |
| ``PUT settings``                          | saves the complete settings object, restarts the listener; the status |
| ``GET keys`` / ``GET keys?id=``           | key list; one key in full                                      |
| ``POST keys`` ``{name, models}``          | ``{key, record}``: the new key in full                         |
| ``PATCH keys`` ``{id, name?, enabled?, models?}`` | ``{record}``                                           |
| ``DELETE keys?id=``                       | remaining keys                                                 |
| ``GET usage?range=&key=&model=&protocol=&outcome=`` | range facets; totals, groups and newest rows of the filter |

Invalid settings and keys answer 400, an unknown key id 404.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from .keys import KeyStore, KeyStoreError
from .settings import SettingsError, SettingsStore
from .usage import RANGES, UsageStore, parse_filter


class Host(Protocol):
    """The service, as the routes use it."""

    settings: SettingsStore
    keys: KeyStore
    usage: UsageStore

    def status(self) -> dict[str, Any]: ...
    async def save_settings(self, raw: Any) -> dict[str, Any]: ...


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(400, "invalid JSON body")
    return data


def _key_error(error: KeyStoreError) -> HTTPException:
    return HTTPException(404 if error.code == "missing" else 400, str(error))


def build_router(service: Host) -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return service.status()

    @router.put("/settings")
    async def put_settings(request: Request) -> dict[str, Any]:
        try:
            return await service.save_settings(await _body(request))
        except SettingsError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/keys")
    async def get_keys(id: str | None = None) -> dict[str, Any]:
        if id is None:
            return {"keys": service.keys.list()}
        key = service.keys.reveal(id)
        if key is None:
            raise HTTPException(404, "key not found")
        return {"id": id, "key": key}

    @router.post("/keys")
    async def create_key(request: Request) -> dict[str, Any]:
        data = await _body(request)
        try:
            return service.keys.create(data.get("name"), data.get("models"))
        except KeyStoreError as exc:
            raise _key_error(exc) from exc

    @router.patch("/keys")
    async def update_key(request: Request) -> dict[str, Any]:
        data = await _body(request)
        if not isinstance(data.get("id"), str):
            raise HTTPException(400, "id required")
        try:
            return {"record": service.keys.update(data["id"], data)}
        except KeyStoreError as exc:
            raise _key_error(exc) from exc

    @router.delete("/keys")
    async def delete_key(id: str) -> dict[str, Any]:
        try:
            service.keys.remove(id)
        except KeyStoreError as exc:
            raise _key_error(exc) from exc
        return {"keys": service.keys.list()}

    @router.get("/usage")
    async def get_usage(request: Request, range: str = "today") -> dict[str, Any]:  # noqa: A002 — query parameter name
        if range not in RANGES:
            raise HTTPException(400, "range must be today, 7d or 30d")
        pricing = service.settings.get()["pricing"]
        return service.usage.summary(range, pricing, parse_filter(request.query_params))

    return router
