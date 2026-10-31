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
| `pyharness-ask-user` | service | askUser | tools | yes | Plugin that provides one service under ``key``. |
| `pyharness-checkpoint-postgres` | function |  |  | yes | Persistence provider on PostgreSQL: ``ctx.checkpointer`` and ``ctx.store``. |
| `pyharness-checkpoint-sqlite` | function |  |  | yes | Persistence provider on SQLite: ``ctx.checkpointer`` and ``ctx.store``. |
| `pyharness-compaction` | service | compaction | agentLoop, llm | yes | Plugin that provides one service under ``key``. |
| `pyharness-dev-context` | function |  | prompt | yes | Prompt section ``dev-context``: where this harness runs. |
| `pyharness-http` | service | http |  | yes | FastAPI root application and uvicorn server. |
| `pyharness-inspect` | function |  | tools | yes | ``harness_inspect`` tool: read-only view of the running harness. |
| `pyharness-llm` | service | llm |  | yes | Chat-model routes; resolves ``route:model`` specs. |
| `pyharness-mcp` | service | mcp | tools | yes | MCP servers as tools. |
| `pyharness-memory` | service | memory | tools, prompt, http | yes | Career memory: store, tools, prompt section, routes and the Memory page module. |
| `pyharness-plugin-manager` | function |  | tools, prompt, agentLoop | yes | ``plugin_manager`` tool, the plugin-authoring skills, and the short prompt section. |
| `pyharness-prompt` | service | prompt |  | no | Ordered system-prompt sections. |
| `pyharness-rdb` | service | rdb | tools, prompt, http | yes | Database workbench: profiles, connections, tools, routes and the Database page module. |
| `pyharness-s3` | service | s3 | tools, prompt, http | yes | S3 browser: profiles, clients, tools, routes and the S3 page module. |
| `pyharness-terminal` | service | terminal | tools, http | yes | Plugin that provides one service under ``key``. |
| `pyharness-tools` | service | tools |  | no | Tool registry and the ``tools/execute`` → ``tools/result`` pipeline. |
| `pyharness-web-tools` | service | web | tools | yes | Plugin that provides one service under ``key``. |
| `pyharness-web-ui` | service | webui | http | yes | The Web UI page and the client-module registry. |
| `pyharness-workspace` | function |  | tools | yes | Workspace provider: ``ctx.workspace`` (the workspace registry) and ``ctx.backend`` (the default deepagents backend). |
| `pyharness-workspace-changes` | service | workspaceChanges | agents, workspace, store | yes | Per-turn changed-file summaries and diffs. |

## Bundles

| bundle | title | description | entries (patch op ids) |
|---|---|---|---|
| `base` | Base | Kernel services, the deepagents loop, SQLite persistence, workspace files, HTTP API and Web UI. | `llm`, `tools`, `prompt`, `mcp`, `ask-user`, `checkpoint`, `workspace`, `agent-loop`, `agents`, `compaction`, `workspace-changes`, `inspect`, `plugin-manager`, `dev-context`, `http`, `api`, `web-ui`, `terminal` |
| `creator` | Creator | New sessions start in the Creator preset (plugin-authoring skills, plugin manager and inspection tools). | `agent-loop` |
| `toolkit` | Toolkit | Built-in toolkit; sidebar entries can be hidden in Settings → General. | `memory`, `rdb`, `s3` |
| `web` | Web | web_search (DeepSeek native search; needs DEEPSEEK_API_KEY) and web_fetch tools for the agent. Preset; switch it off on the Plugins page. | `web-tools` |
