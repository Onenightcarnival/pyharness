"""
Image inputs of requests: base64 payloads and remote URLs become ``data:`` URLs for the model.

| name                 | contract                                                                    |
|----------------------|-----------------------------------------------------------------------------|
| ``ImageResolver``    | ``await resolver(image)`` → a ``data:`` URL; ``GatewayError`` 400 on any rejection |
| ``sniff_media_type`` | media type from the leading bytes, for responses without a usable content type |

PNG, JPEG, WebP and GIF up to :data:`MAX_IMAGE_BYTES`; remote URLs are fetched with ``http`` or ``https``.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from pyharness import package_toml

from .drafts import invalid

_CFG = package_toml(__file__)["images"]
MEDIA_TYPES: tuple[str, ...] = tuple(_CFG["MEDIA_TYPES"])
MAX_IMAGE_BYTES: int = _CFG["MAX_IMAGE_BYTES"]
FETCH_TIMEOUT_S: float = _CFG["FETCH_TIMEOUT_S"]


def _media_type(value: str | None) -> str | None:
    kind = (value or "").split(";")[0].strip().lower()
    kind = "image/jpeg" if kind == "image/jpg" else kind
    return kind if kind in MEDIA_TYPES else None


def sniff_media_type(data: bytes) -> str | None:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ImageResolver:
    """``transport`` overrides the HTTP transport of remote fetches (tests)."""

    def __init__(self, max_bytes: int = MAX_IMAGE_BYTES, transport: Any = None) -> None:
        self.max_bytes = max_bytes
        self.transport = transport

    async def _fetch(self, url: str) -> tuple[bytes, str]:
        if urlparse(url).scheme not in ("http", "https"):
            raise invalid("image URLs must use http or https")
        try:
            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT_S, follow_redirects=True, transport=self.transport
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise invalid(f"image URL could not be fetched: {exc}") from exc
        if not response.is_success:
            raise invalid(f"image URL returned HTTP {response.status_code}")
        data = response.content
        kind = _media_type(response.headers.get("content-type")) or sniff_media_type(data)
        if kind is None:
            raise invalid("image URL did not return a PNG, JPEG, WebP or GIF image")
        return data, kind

    async def __call__(self, image: dict[str, Any]) -> str:
        source = image["source"]
        if source["kind"] == "base64":
            kind = _media_type(source["media_type"])
            if kind is None:
                raise invalid(f'unsupported image media type "{source["media_type"]}"')
            try:
                data = base64.b64decode(re.sub(r"\s+", "", source["data"]), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise invalid("image data is not valid base64") from exc
        else:
            data, kind = await self._fetch(source["url"])
        if not data:
            raise invalid("image data is empty")
        if len(data) > self.max_bytes:
            raise invalid(f"image exceeds {self.max_bytes} bytes")
        return f"data:{kind};base64,{base64.b64encode(data).decode()}"
