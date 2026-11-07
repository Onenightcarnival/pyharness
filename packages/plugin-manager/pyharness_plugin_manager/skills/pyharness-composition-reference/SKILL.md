---
name: pyharness-composition-reference
description: "Use when you need the list of plugin packages and bundles installed with this harness, what service each provides, what it injects, whether it takes config, and the entry ids of the base bundle, for writing a bundle patch or choosing what to build on."
---

# Composition reference

`references/packages.md` in this skill's directory lists every installed plugin entry point (`pyharness.plugins`) and bundle (`pyharness.bundles`): kind, provided service key, injected services, whether the entry takes config, and the first line of its contract. It is generated from the installed distributions; a plugin installed into the profile after generation is listed by `plugin_manager action=list` instead.

Search it with `grep` on the file path rather than reading it whole; it is a reference, not a procedure. Procedures: `pyharness-plugin-development` (write and install a plugin), `editing-pyharness-compositions` (patch dialect).

## Base bundle entry ids

| id | plugin | service |
|---|---|---|
| `llm` | `pyharness-llm` | `llm` |
| `tools` | `pyharness-tools` | `tools` |
| `prompt` | `pyharness-prompt` | `prompt` |
| `checkpoint` | `pyharness-checkpoint-sqlite` | `checkpointer`, `store` |
| `workspace` | `pyharness-workspace` | `workspace`, `backend` |
| `agent-loop` | `pyharness-agent-loop-deepagents` | `agentLoop` |
| `agents` | `pyharness-agent` | `agents` |
| `inspect` | `pyharness-inspect` | — (`harness_inspect` tool) |
| `plugin-manager` | `pyharness-plugin-manager` | — (`plugin_manager` tool, skills) |
| `dev-context` | `pyharness-dev-context` | — (prompt section) |
| `http` | `pyharness-http` | `http` |
| `api` | `pyharness-api` | — (`/api`) |
| `web-ui` | `pyharness-web-ui` | — (`/`) |

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
