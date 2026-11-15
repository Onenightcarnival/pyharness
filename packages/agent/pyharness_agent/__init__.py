"""``ctx.agents``: sessions and runs over the graph ``ctx.agentLoop`` builds.

| concept    | contract                                                                            |
|------------|-------------------------------------------------------------------------------------|
| session    | LangGraph thread (``ctx.checkpointer``) + metadata record (``ctx.store``)           |
| run        | background task; events to a :class:`RunHandle`                                     |
| subscriber | replay from the start; a disconnect leaves the run running                          |
| hold       | each run holds the lifecycle; a pending restart waits for it                        |
| refusal    | restart pending → :meth:`AgentService.start_run` raises ``RestartPending``          |
| resume     | ``app/started`` of a supervised generation: continuation message per listed session |
| model      | ``session.model`` (``route:model``) reaches the loop as ``configurable.model_spec``    |
| graph      | one graph per (``workspace``, ``mode``, ``preset``) of the session, built on first use |

Run events: ``reasoning``, ``token``, ``image``, ``tool_call``, ``tool_result``, ``compact``, ``retry``,
``interrupt``, ``error``, ``done``. ``compact``: a compaction checkpoint replaced older history (``removed``,
``before_tokens``, ``after_tokens``, ``trigger``, ``summary``). ``retry``: the route's retry policy runs a failed
model call again (``attempt``, ``max_retries``, ``code``, ``message``, ``delay_ms``); the text streamed by the
failed attempt is void. ``error``: ``code`` (a failure code of ``pyharness_llm``), ``message``, ``continuable``.

Failed turns: a turn that ends with outcome ``error`` keeps ``error: {code, message}`` in its record.
``failure(session_id)`` reports it while it is the last turn; ``retry_run(session_id)`` continues a failure whose
code is one of ``CONTINUABLE_CODES`` with a run of kind ``retry``: the graph resumes at the step that failed and
no message is added.

Images: a user message carries ``image_url`` content blocks (data URLs) beside its text; serialized messages
list them under ``images``; an AI message with image blocks emits ``image`` events and lists them likewise.

| event                | mode     | listener                               |
|----------------------|----------|----------------------------------------|
| ``agent/turn-start`` | parallel | ``(turn: Turn)``                       |
| ``agent/turn-end``   | parallel | ``(turn: Turn)``; ``turn.outcome`` set |

``turn.extras`` of ``agent/turn-end`` reaches the ``done`` event as ``extras``.

Turn records: every turn is recorded in ``ctx.store`` (``("pyharness", "turns", session_id)``, key run id) with
``stats`` (steps, tool calls, token usage, llm/tool/ttft/decode wall time, duration, compactions) and ``records``
(the trajectory: user, step, tool, compact, retry, end). ``turns(session_id)`` lists them; ``done`` carries the new
one as ``extras.turn``.

| module        | content                                                              |
|---------------|----------------------------------------------------------------------|
| ``service``   | ``AgentService``, ``AgentConfig``, the session record namespace      |
| ``runs``      | ``RunHandle``, ``Turn``, ``TurnRecorder``, ``SessionBusy``, ``RestartPending``, |
|               | ``NotContinuable``                                                   |
| ``messages``  | message content helpers and ``serialize_message``                    |
"""

from __future__ import annotations

from .messages import serialize_message
from .runs import NotContinuable, RestartPending, RunHandle, SessionBusy, Turn
from .service import AgentConfig, AgentService

__all__ = [
    "AgentConfig",
    "AgentService",
    "NotContinuable",
    "RestartPending",
    "RunHandle",
    "SessionBusy",
    "Turn",
    "serialize_message",
]
