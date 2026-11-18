---
name: pyxis-harness-composition-reference
description: "Use when you need the list of plugin packages and bundles installed with this harness, what service each provides, what it injects, whether it takes config, and the entry ids of the base bundle, for writing a bundle patch or choosing what to build on."
---

# Composition reference

`references/packages.md` in this skill's directory lists every installed plugin entry point (`pyharness.plugins`) and bundle (`pyharness.bundles`): kind, provided service key, injected services, whether the entry takes config, and the first line of its contract. It is generated from the installed distributions; a plugin installed into the profile after generation is listed by `plugin_manager action=list` instead.

Search it with `grep` on the file path rather than reading it whole; it is a reference, not a procedure. Procedures: `pyxis-harness-plugin-development` (write and install a plugin), `editing-pyxis-harness-compositions` (patch dialect).

## Base bundle entry ids

| id | plugin | service |
|---|---|---|
| `llm` | `pyxis-harness-llm` | `llm` |
| `tools` | `pyxis-harness-tools` | `tools` |
| `prompt` | `pyxis-harness-prompt` | `prompt` |
| `checkpoint` | `pyxis-harness-checkpoint-sqlite` | `checkpointer`, `store` |
| `workspace` | `pyxis-harness-workspace` | `workspace`, `backend` |
| `agent-loop` | `pyxis-harness-agent-loop-deepagents` | `agentLoop` |
| `agents` | `pyxis-harness-agent` | `agents` |
| `inspect` | `pyxis-harness-inspect` | — (`harness_inspect` tool) |
| `plugin-manager` | `pyxis-harness-plugin-manager` | — (`plugin_manager` tool, skills) |
| `dev-context` | `pyxis-harness-dev-context` | — (prompt section) |
| `http` | `pyxis-harness-http` | `http` |
| `api` | `pyxis-harness-api` | — (`/api`) |
| `web-ui` | `pyxis-harness-web-ui` | — (`/`) |

The live tree, including entries from other bundles and the profile patch, is `harness_inspect topic=plugins`.

## Service summary

| key | members used by plugins |
|---|---|
| `tools` | `register(tool, approval=...)`, `require_approval(name, ...)`, `list()`, `interrupt_on()`, `records()` |
| `prompt` | `add(id, text, order=100)`, `sections()`, `render()` |
| `llm` | `resolve("provider:model", **options)`, `register(provider, factory)`, `providers()`, `default` |
| `http` | `include_router(router, prefix)`, `mount(path, app)`, `routes()`, `contributions()` |
| `agentLoop` | `add_subagent(spec)`, `add_middleware(m)`, `add_skills(dir, label)` |
| `agents` | `create_session()`, `start_run(session_id, content)`, `messages(session_id)`, `cancel(session_id)` |
| `store` | LangGraph store: `aput`, `aget`, `asearch`, `adelete` |
| `workspace` | `resolve(path)`, `root`, `permissions()` |

Exact signatures: `harness_inspect topic=services name=<key>`.
