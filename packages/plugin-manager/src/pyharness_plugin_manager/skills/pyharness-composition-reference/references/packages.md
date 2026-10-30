# Installed plugin packages and bundles

Generated from the `pyharness.plugins` and `pyharness.bundles` entry points of the environment: `python scripts/gen_packages.py`.
Plugins installed into a profile after generation: `plugin_manager action=list`.

Columns: `kind` is `service` (provides the service under `provides`) or `function` (`apply(ctx, config)`); `inject` lists the
services the entry waits for; `config` says whether the entry accepts `config`.

## Plugins

| entry point | kind | provides | inject | config | contract |
|---|---|---|---|---|---|
| `pyharness-agent` | service | agents | agentLoop, store | yes | Sessions, runs, approvals, post-restart continuation. |
| `pyharness-agent-loop-deepagents` | service | agentLoop | llm, tools, prompt, checkpointer | yes | deepagents graph built from the services of other plugins. |
| `pyharness-api` | function |  | http, agents, llm | yes | REST and SSE API over ``ctx.agents``, under ``/api`` on ``ctx.http``. |
| `pyharness-checkpoint-postgres` | function |  |  | yes | Persistence provider on PostgreSQL: ``ctx.checkpointer`` and ``ctx.store``. |
| `pyharness-checkpoint-sqlite` | function |  |  | yes | Persistence provider on SQLite: ``ctx.checkpointer`` and ``ctx.store``. |
| `pyharness-dev-context` | function |  | prompt | yes | Prompt section ``dev-context``: where this harness runs. |
| `pyharness-http` | service | http |  | yes | FastAPI root application and uvicorn server. |
| `pyharness-inspect` | function |  | tools | yes | ``harness_inspect`` tool: read-only view of the running harness. |
| `pyharness-llm` | service | llm |  | yes | Chat-model routes; resolves ``route:model`` specs. |
| `pyharness-plugin-manager` | function |  | tools, prompt, agentLoop | yes | ``plugin_manager`` tool, the plugin-authoring skills, and the short prompt section. |
| `pyharness-prompt` | service | prompt |  | no | Ordered system-prompt sections. |
| `pyharness-tools` | service | tools |  | no | Tool registry and the ``tools/execute`` → ``tools/result`` pipeline. |
| `pyharness-web-ui` | function |  | http | yes | Web UI: one self-contained page at ``config.path`` on ``ctx.http``; data from ``/api``. |
| `pyharness-workspace` | function |  | tools | yes | Workspace provider: ``ctx.workspace`` (the workspace registry) and ``ctx.backend`` (the default deepagents backend). |

## Bundles

| bundle | title | description | entries (patch op ids) |
|---|---|---|---|
| `base` | Base | Kernel services, the deepagents loop, SQLite persistence, workspace files, HTTP API and Web UI. | `llm`, `tools`, `prompt`, `checkpoint`, `workspace`, `agent-loop`, `agents`, `inspect`, `plugin-manager`, `dev-context`, `http`, `api`, `web-ui` |
| `creator` | Creator | New sessions start in the Creator preset (plugin-authoring skills, plugin manager and inspection tools). | `agent-loop` |
