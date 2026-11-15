from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_SERVICE = "pyharness"
SECRET_REF = "OTEL_SECRET_KEY"


class Config(BaseModel):
    enabled: bool = False
    endpoint: str = ""
    public_key: str = ""
    secret_key: str | None = Field(SECRET_REF, description="Credential reference of the Basic-auth password.")
    capture_content: bool = True
    content_max_chars: int = Field(128000, ge=100, le=10_000_000)
    gzip: bool = False
    max_export_batch_size: int = Field(512, ge=1, le=4096)
    max_queue_size: int = 2048
    trace_export_interval_ms: int = 5000
    export_timeout_ms: int = 30000
    service_name: str = DEFAULT_SERVICE
