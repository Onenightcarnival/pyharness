from __future__ import annotations

import base64
import contextlib
import os
import re
import time
from collections import deque
from typing import Any

import requests
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult

from .config import DEFAULT_SERVICE, VERSION, Config
from .spans import AGENT_SYSTEM

LANGFUSE_RE = re.compile(r"langfuse", re.IGNORECASE)


# ---------------------------------------------------------------------- endpoint helpers
def normalize_endpoint(raw: str, langfuse_hint: bool = False) -> str:
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "https://" + url
    if (LANGFUSE_RE.search(url) or langfuse_hint) and not re.search(r"/api/public/otel$|/v1/(traces|metrics)$", url):
        url += "/api/public/otel"
    return url


def is_langfuse_key_pair(public_key: str, secret: str) -> bool:
    return public_key.startswith("pk-lf-") and secret.startswith("sk-lf-")


def is_langfuse_endpoint(url: str) -> bool:
    return bool(LANGFUSE_RE.search(url)) or "/api/public/otel" in url


def signal_url(base: str, signal: str) -> str:
    if re.search(r"/v1/(traces|metrics)$", base):
        return re.sub(r"/v1/(traces|metrics)$", f"/v1/{signal}", base)
    return f"{base}/v1/{signal}"


def basic_auth(public_key: str, secret: str) -> dict[str, str]:
    pk, sk = public_key.strip(), secret.strip()
    if not pk and not sk:
        return {}
    return {"authorization": "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()}


# ---------------------------------------------------------------------- pipeline
class CountingExporter:
    """Wraps the OTLP exporter: batches / spans / last result and the last trace ids, for the status page."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.batches = 0
        self.spans = 0
        self.last_at: float | None = None
        self.last_ok: bool | None = None
        self.last_error: str | None = None
        self.trace_ids: deque[str] = deque(maxlen=50)

    def export(self, spans: Any) -> Any:
        try:
            result = self.inner.export(spans)
        except Exception as exc:  # noqa: BLE001
            self.last_ok, self.last_error, self.last_at = False, f"{type(exc).__name__}: {exc}", time.time()
            return SpanExportResult.FAILURE
        ok = result == SpanExportResult.SUCCESS
        self.batches += 1
        self.spans += len(spans)
        self.last_at, self.last_ok = time.time(), ok
        self.last_error = None if ok else "export failed (see the harness log)"
        for span in spans:
            if span.parent is None:
                self.trace_ids.append(format(span.context.trace_id, "032x"))
        return result

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


class Pipeline:
    def __init__(self, config: Config, secret: str, *, exporter: Any | None = None) -> None:
        self.config = config
        self.endpoint = normalize_endpoint(config.endpoint, is_langfuse_key_pair(config.public_key, secret))
        self.trace_endpoint = signal_url(self.endpoint, "traces") if self.endpoint else ""
        self.langfuse = is_langfuse_endpoint(self.endpoint)
        self.headers = basic_auth(config.public_key, secret)
        if exporter is None:
            session = requests.Session()
            session.trust_env = False  # the proxy settings of the environment and of the system do not apply
            exporter = OTLPSpanExporter(
                session=session,
                endpoint=self.trace_endpoint,
                headers=self.headers,
                timeout=max(1, config.export_timeout_ms // 1000),
                compression=Compression.Gzip if config.gzip else Compression.NoCompression,
            )
        self.exporter = CountingExporter(exporter)
        resource = Resource.create(
            {
                "service.name": config.service_name or os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE,
                "service.instance.id": (
                    f"{config.service_name or DEFAULT_SERVICE}"
                    f"@{os.uname().nodename if hasattr(os, 'uname') else 'host'}:{os.getpid()}"
                ),
                "telemetry.sdk.language": "python",
                "gen_ai.agent.system": AGENT_SYSTEM,
            }
        )
        self.provider = TracerProvider(resource=resource)
        self.provider.add_span_processor(
            BatchSpanProcessor(
                self.exporter,
                max_queue_size=max(config.max_queue_size, config.max_export_batch_size),
                max_export_batch_size=config.max_export_batch_size,
                schedule_delay_millis=config.trace_export_interval_ms,
                export_timeout_millis=config.export_timeout_ms,
            )
        )
        self.tracer = self.provider.get_tracer("pyxis-harness-otel", VERSION)

    def flush(self, timeout_ms: int = 20000) -> bool:
        return self.provider.force_flush(timeout_ms)

    def shutdown(self) -> None:
        with contextlib.suppress(Exception):
            self.provider.shutdown()
