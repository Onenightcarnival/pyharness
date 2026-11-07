"""``ctx.compaction``: context compaction — a checkpoint summary replaces older history.

- auto: before a model call, once the measured context reaches ``threshold_ratio`` × window; kept verbatim: the tail
  worth ``retain_ratio`` × window.
- manual: ``/compact`` — a run of kind ``compact`` (``POST /sessions/{id}/compact``); kept verbatim: nothing, the
  whole history is summarized.

Measurement: the usage of the latest model response (input + output tokens) plus an estimate of the messages after
it; without usage (first steps, right after a compaction) the estimate covers everything. The window is the model's
declared ``context_window`` (Settings → Models), else ``default_context_window``.

The cut never separates a tool call from its results. The summary comes from the session's model (``summary_model``
overrides) prompted with a structured checkpoint template; the replacement is a user message whose
``additional_kwargs["pyharness"]`` is ``{"kind": "compact-checkpoint", ...}`` — the Web UI shows it as a marker, the
run stream carries a ``compact`` event, and the turn record a ``compact`` entry. Automatic compaction failures are
logged and the turn continues; manual ones fail the run.
"""

from __future__ import annotations

from .checkpoint import (
    CHECKPOINT_KIND,
    COMMAND_KIND,
    checkpoint_message,
    command_of,
    cut_index,
    is_checkpoint,
    measure,
    summary_of,
    transcript,
)
from .service import CompactionError, CompactionMiddleware, CompactionService, Config

__all__ = [
    "CHECKPOINT_KIND",
    "COMMAND_KIND",
    "CompactionError",
    "CompactionMiddleware",
    "CompactionService",
    "Config",
    "checkpoint_message",
    "command_of",
    "cut_index",
    "is_checkpoint",
    "measure",
    "summary_of",
    "transcript",
]
