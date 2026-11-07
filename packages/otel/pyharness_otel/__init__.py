"""``ctx.otel``: OpenTelemetry export of agent turns (GenAI semantic conventions) to an OTLP/HTTP backend such as
Langfuse.

| member        | contract                                                                  |
|---------------|---------------------------------------------------------------------------|
| ``status()``  | configuration (secret never returned), pipeline state, export counters    |
| ``save()``    | write the settings to the profile and restart the pipeline in place       |
| ``test()``    | send test spans (connectivity, payload, GenAI shape) and verify on Langfuse |

| config                   | meaning                                                              |
|--------------------------|----------------------------------------------------------------------|
| ``enabled``              | export turns (default off)                                           |
| ``endpoint``             | OTLP base URL; a Langfuse host gets ``/api/public/otel`` appended    |
| ``public_key``           | Basic-auth user (Langfuse ``pk-lf-…``)                               |
| ``secret_key``           | credential reference of the Basic-auth password (``OTEL_SECRET_KEY``) |
| ``capture_content``      | put messages, system prompt, tool definitions, arguments and results on spans |
| ``content_max_chars``    | per-attribute limit; longer values become ``{"truncated": true, …}`` |
| ``gzip``                 | compress OTLP requests                                               |
| ``max_export_batch_size``| spans per export request                                             |
| ``service_name``         | ``service.name`` resource attribute                                  |

One trace per turn: ``enter_ai_application_system`` (ENTRY) → ``invoke_agent <preset>`` (AGENT) → ``react step`` (STEP)
→ ``chat <model>`` (LLM) and ``execute_tool <name>`` (TOOL), built from the turn record after ``agent/turn-end``.
Attribute names follow the GenAI semantic conventions used by dsh-otel; Langfuse aliases (``langfuse.session.id``,
``langfuse.user.id``) ride along. Routes under ``/api/otel``: ``GET status``, ``PUT settings``, ``POST test``,
``POST verify``.
"""

from __future__ import annotations

from .config import Config
from .pipeline import Pipeline, normalize_endpoint, signal_url
from .service import OtelService
from .spans import build_turn_spans

__all__ = ["Config", "OtelService", "Pipeline", "build_turn_spans", "normalize_endpoint", "signal_url"]
