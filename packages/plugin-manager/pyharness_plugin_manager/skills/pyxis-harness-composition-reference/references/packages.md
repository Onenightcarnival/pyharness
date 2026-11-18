# Installed plugin packages and bundles

Generated from the `pyharness.plugins` and `pyharness.bundles` entry points of the environment:
`python scripts/gen_packages.py`.
Plugins installed into a profile after generation: `plugin_manager action=list`.

Columns: `kind` is `service` (provides the service under `provides`) or `function` (`apply(ctx, config)`);
`inject` lists the
services the entry waits for; `config` says whether the entry accepts `config`.

## Plugins

| entry point | kind | provides | inject | config | contract |
|---|---|---|---|---|---|
| `pyxis-harness-agent` | service | agents | agentLoop, store | yes | Sessions, runs, approvals, post-restart continuation. |
| `pyxis-harness-agent-loop-deepagents` | service | agentLoop | llm, tools, prompt, checkpointer | yes | deepagents graph built from the services of other plugins. |
| `pyxis-harness-api` | function |  | http, agents, llm | yes | REST and SSE API over ``ctx.agents``, under ``/api`` on ``ctx.http``. |
| `pyxis-harness-ask-user` | service | askUser | tools | yes | Plugin that provides one service under ``key``. |
| `pyxis-harness-auto-review` | function |  | agentLoop, llm | yes | Auto review permission mode: a model reviews each gated tool call before it runs; a denied call asks the user. |
| `pyxis-harness-checkpoint-postgres` | function |  |  | yes | Persistence provider on PostgreSQL: ``ctx.checkpointer`` and ``ctx.store``. |
| `pyxis-harness-checkpoint-sqlite` | function |  |  | yes | Persistence provider on SQLite: ``ctx.checkpointer`` and ``ctx.store``. |
| `pyxis-harness-compaction` | service | compaction | agentLoop, llm | yes | Plugin that provides one service under ``key``. |
| `pyxis-harness-config-center` | service | configCenter | http, webui, agentLoop | yes | MCP page, skills and the managed runtime. |
| `pyxis-harness-dev-context` | function |  | prompt | yes | Prompt section ``dev-context``: where this harness runs. |
| `pyxis-harness-gateway` | service | gateway | llm, http, webui | yes | Local LLM API gateway over the routes of ``ctx.llm``. |
| `pyxis-harness-http` | service | http |  | yes | FastAPI root application and uvicorn server. |
| `pyxis-harness-http-client` | service | httpClient | tools, prompt, http, webui | yes | HTTP API request tool: targets, saved requests, history, the ``http_*`` tools and the HTTP page. |
| `pyxis-harness-inspect` | function |  | tools | yes | ``harness_inspect`` tool: read-only view of the running harness. |
| `pyxis-harness-llm` | service | llm |  | yes | Chat-model routes; resolves ``route:model`` specs. |
| `pyxis-harness-mcp` | service | mcp | tools | yes | MCP servers as tools. |
| `pyxis-harness-memory` | service | memory | tools, prompt, http | yes | Career memory: store, tools, prompt section, routes and the Memory page module. |
| `pyxis-harness-otel` | service | otel | http, webui | yes | Turn traces to an OTLP backend; the Observability settings page. |
| `pyxis-harness-plugin-manager` | function |  | tools, prompt, agentLoop | yes | ``plugin_manager`` tool, the plugin-authoring skills, the package and plugin-source mounts, the prompt sections. |
| `pyxis-harness-prompt` | service | prompt |  | no | Ordered system-prompt sections. |
| `pyxis-harness-rdb` | service | rdb | tools, prompt, http | yes | Database workbench: profiles, connections, tools, routes and the Database page module. |
| `pyxis-harness-s3` | service | s3 | tools, prompt, http | yes | S3 browser: profiles, clients, tools, routes and the S3 page module. |
| `pyxis-harness-subscriptions` | service | subscriptions | llm, tools, http, webui | yes | Subscriptions: providers, model routes, tools, the AI subscriptions page. |
| `pyxis-harness-terminal` | service | terminal | tools, http | yes | Plugin that provides one service under ``key``. |
| `pyxis-harness-tools` | service | tools |  | no | Tool registry and the ``tools/execute`` → ``tools/result`` pipeline. |
| `pyxis-harness-web-tools` | service | web | tools | yes | Plugin that provides one service under ``key``. |
| `pyxis-harness-web-ui` | service | webui | http | yes | The Web UI page and the client-module registry. |
| `pyxis-harness-workspace` | function |  | tools | yes | Workspace provider: ``ctx.workspace`` (workspace registry) and ``ctx.backend`` (default deepagents backend). |
| `pyxis-harness-workspace-changes` | service | workspaceChanges | agents, workspace, store | yes | Per-turn changed-file summaries and diffs. |

## Bundles

| bundle | title | description | entries (patch op ids) |
|---|---|---|---|
| `base` | Base | Kernel services, the deepagents loop, SQLite persistence, workspace files, HTTP API and Web UI. | `llm`, `tools`, `prompt`, `mcp`, `ask-user`, `checkpoint`, `workspace`, `agent-loop`, `agents`, `auto-review`, `compaction`, `workspace-changes`, `inspect`, `plugin-manager`, `dev-context`, `http`, `api`, `web-ui`, `terminal` |
| `creator` | Creator | New sessions start in the Creator preset (plugin-authoring skills, plugin manager and inspection tools). | `agent-loop` |
| `toolkit` | Toolkit | Built-in toolkit; sidebar entries can be unpinned to the More menu. | `memory`, `rdb`, `s3`, `config-center`, `otel`, `subscriptions`, `gateway`, `http-client` |
| `web` | Web | web_search (DeepSeek native search; needs DEEPSEEK_API_KEY) and web_fetch tools for the agent. Preset; switch it off on the Plugins page. | `web-tools` |
