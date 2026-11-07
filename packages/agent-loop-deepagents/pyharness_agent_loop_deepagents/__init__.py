"""``ctx.agentLoop``: the default agent loop, built on deepagents.

Contract with ``ctx.agents``: ``build()`` returns a LangGraph graph with ``astream`` and
``aget_state``. Another loop replaces this entry through a patch.

``build(workspace, mode, preset)`` builds one graph; ``build()`` builds the default one on ``app/ready``.
Sessions choose a workspace (root directory), a permission mode and an agent preset; ``ctx.agents`` keeps
one graph per combination.

| permission mode     | effect                                                                  |
|---------------------|-------------------------------------------------------------------------|
| ``read-only``       | file writes denied, no ``execute`` tool, tools tagged ``shell`` left out; approvals as |
|                     | configured                                                              |
| ``workspace-write`` | writes inside the workspace; approvals as configured                    |
| ``full-access``     | writes inside the workspace; no approval gates                          |

| preset field      | effect                                                          |
|-------------------|-----------------------------------------------------------------|
| ``tools``         | registered tool names the preset keeps (``None``: all)          |
| ``exclude_tools`` | registered tool names the preset drops                          |
| ``skills``        | skills directories mounted for the preset (``add_skills``)      |
| prompt sections   | ``ctx.prompt.add(..., presets=[...])`` limits a section          |

``build()`` reads:

| input         | source                                                          |
|---------------|-----------------------------------------------------------------|
| model         | ``ctx.llm``                                                     |
| tools         | ``ctx.tools``                                                   |
| system prompt | ``ctx.prompt``                                                  |
| persistence   | ``ctx.checkpointer``; ``ctx.store`` when present                |
| files, shell  | ``ctx.backend`` and ``ctx.workspace`` permissions, when present |
| approvals     | ``ctx.tools.interrupt_on()`` and ``config.interrupt_on``        |
| subagents     | ``config.subagents`` and :meth:`DeepAgentsLoop.add_subagent`    |
| skills        | ``config.skills`` and :meth:`DeepAgentsLoop.add_skills`         |

:class:`HarnessMiddleware` runs in the main agent and in every declarative subagent:

| hook       | route                                                                           |
|------------|---------------------------------------------------------------------------------|
| model call | model from ``configurable.model_spec`` or ``ctx.llm.default`` when it differs from the built one; |
|            | then ``agent/model-request`` (waterfall)                                        |
| tool call  | ``ctx.tools.execute``                                                           |

A default model that cannot be initialised at boot (missing package or credential) does not fail the boot outside
preflight: the graph is built with ``echo:echo`` and each request resolves the configured model, so the error
reaches the session and the settings page stays available.

``agent-loop/build`` (waterfall) receives the ``create_deep_agent`` keyword arguments.

Skills directories added by plugins are mounted read-only for the model at ``/skills/<label>/``
(``CompositeBackend`` route over ``ctx.backend``); deepagents lists them in the system prompt and
the model reads a skill with ``read_file``.
"""

from .config import DEFAULT_PRESETS, MODES, SKILLS_MOUNT, LoopConfig, PresetConfig
from .middleware import HarnessMiddleware, ModelCall
from .service import DeepAgentsLoop

__all__ = [
    "DEFAULT_PRESETS",
    "MODES",
    "SKILLS_MOUNT",
    "DeepAgentsLoop",
    "HarnessMiddleware",
    "LoopConfig",
    "ModelCall",
    "PresetConfig",
]
