from __future__ import annotations

from pydantic import BaseModel, Field

from pyharness import package_toml

_CFG = package_toml(__file__)
DEFAULT_HOST: str = _CFG["settings"]["DEFAULT_HOST"]
DEFAULT_PORT: int = _CFG["settings"]["DEFAULT_PORT"]
DEFAULT_MAX_BODY_BYTES: int = _CFG["server"]["DEFAULT_MAX_BODY_BYTES"]


class Config(BaseModel):
    """Deployment defaults; the gateway page overrides the listener fields in ``settings.json``."""

    listen: bool = Field(True, description="Initial listener state before the settings file exists.")
    host: str = Field(DEFAULT_HOST, description="Initial bind address.")
    port: int = Field(DEFAULT_PORT, ge=1, le=65535, description="Initial listener port.")
    data_dir: str | None = Field(
        None,
        description="Directory of settings.json, keys.json and usage.sqlite; default <profile data>/toolkit/gateway.",
    )
    max_body_bytes: int = Field(DEFAULT_MAX_BODY_BYTES, ge=1024, description="Request body limit in bytes.")
