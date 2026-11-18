# Plugin practices

Confirm every service method, event name, and dispatch mode named here with `harness_inspect` (`services`, `events`); the running harness is the authority.

## Principles

1. **Registrations are effects owned by a context.** Register through `ctx`; the entry's stop undoes them. State kept elsewhere (module globals, files, threads) needs `ctx.on_dispose`.
2. **Use the weakest mechanism that suffices.** From weakest to strongest: a new tool; a `tools/result` listener (observe); an approval gate (`ctx.tools.require_approval`); a `tools/execute` listener (can replace a call); an `agent/model-request` listener (can rewrite the model request); replacing the `agent-loop` entry. The stronger the mechanism, the more of other plugins' behavior it must preserve.
3. **Configuration belongs in `Config`.** Users change it in the profile patch, which survives upgrades; constants in code do not. Constants a user does not configure and model-visible text live in `config.toml` and `prompts.toml` beside the module (`conventions.md`).
4. **Services are shared.** A service another plugin consumes belongs in the base composition order before its consumers (`after:` position); `inject` makes the consumer wait for it.
5. **Every change goes through preflight.** Code that fails at import, at `apply`, or at `app/ready` rejects the installation. Keep `apply` cheap and fail early with a clear message.

## Tool pipeline

| event | mode | listener | use |
|---|---|---|---|
| `tools/execute` | waterfall | `(call, next)` | `await next()` runs the tool; returning a `ToolMessage` instead replaces the call |
| `tools/result` | parallel | `(call, result)` | observe every finished call, including agent-loop built-ins and subagents |

`call` is `pyharness_tools.ToolCall`: `name`, `args`, `id`, `session_id`, `owner`. Listeners run in registration order; a waterfall listener that does not own the decision returns `await next()`.

Approval: `ctx.tools.register(tool, approval={"allowed_decisions": ["approve", "reject"], "description": "...", "when": predicate})` gates the plugin's own tool; `ctx.tools.require_approval(name, ...)` gates another plugin's tool. A gate is owned by the plugin that set it; another plugin cannot remove it.

## Lifecycle events

| event | mode | use |
|---|---|---|
| `app/ready` | series | assemble; no ports, no external resources; runs in preflight |
| `app/serve` | series | bind ports, start accepting input; not run in preflight |
| `app/started` | parallel | background work after the generation is committed |
| `app/stopping` | parallel | cancel work before teardown |
| `agent/turn-start`, `agent/turn-end` | parallel | `Turn` with `session_id`, `kind`, `input`, `outcome` |
| `agent/model-request` | waterfall | `ModelCall` with `request`; `await next()` returns the response |
| `agent-loop/build` | waterfall | the `create_deep_agent` kwargs before the graph is built |

Errors in `series` listeners fail the boot; errors in `parallel` listeners are logged.

## Prompt

`ctx.prompt.add(id, text, order=100)`; `text` may be a zero-argument callable, rendered once per graph build (`app/ready`). Keep sections short: every section is in every model request. Say each fact once: a tool's rules belong in the tool description, not in a prompt section.

## Agent loop

`ctx.agentLoop.add_subagent(spec)` adds a deepagents subagent spec (`name`, `description`, `system_prompt`, `tools` by registered name, optional `model` spec). `ctx.agentLoop.add_middleware(m)` adds a LangChain `AgentMiddleware`. `ctx.agentLoop.add_skills(dir, label)` mounts a skills directory at `/skills/<label>/`. All three are owned by the calling plugin.

## Persistence

`ctx.store` (LangGraph `BaseStore`): `await ctx.store.aput(namespace_tuple, key, dict)`, `aget`, `asearch`. Use a namespace that starts with the plugin's name. `ctx.checkpointer` holds session histories; do not write to it.

## Restart and generations

A saved change restarts the process: module state is lost, `app/*` runs again. Write durable state under `${data_dir}` or `ctx.store`. A plugin cannot keep a session running across the restart; the harness resumes listed sessions with a continuation message.

## Workspace

`ctx.workspace.resolve(agent_path)` maps `/notes/x` to a real path and refuses paths outside the root or inside the harness home. `ctx.backend` is the deepagents backend of the file tools.
