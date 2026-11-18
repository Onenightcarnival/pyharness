---
name: agent-experience
description: "Use when writing or changing a model-facing tool definition (name, description, argument schema, or its prompt section), a skill, a subagent spec, or a continuation message, so that information is discoverable and context is used efficiently."
---

# Agent experience

- **Start with minimal context.** Expose purpose, available actions, and constraints first; put detailed instructions where they are loaded on demand (a skill, a tool result, a reference file).
- **Make discovery explicit.** Every deferred resource needs a description that says when it applies and a reliable way to retrieve it (a path, a tool call).
- **Keep critical constraints visible.** Permissions, destructive effects, and required approvals appear before the action that needs them, in the tool's own description.
- **Prefer bounded outputs.** A tool returns a concise result with identifiers or paths for details; it never dumps whole logs or documents. State truncation explicitly and give a way to get more.
- **Use locality.** Return the bounded adjacent context an operation's caller needs next (the entry state after an install, the generation after a restart).
- **Evaluate total work.** Saving context is useful only when it does not cause more searches, repeated reads, or mistakes.

## Tool definitions (`ctx.tools.register`)

- The function name is the tool name: lowercase, underscores, specific (`audit_tail`, not `get`). A plugin's tools share a prefix.
- The docstring is the description. First line: what the tool does and returns. Omit rules the model learns from the result, such as a missing file failing to read.
- Describe behavior, not implementation: no internal mechanisms, no enforcement details, no output markers.
- Put parameter rules on the parameter: type annotations and defaults form the schema; a constraint that varies with configuration belongs in a parameter description, not the tool description.
- Say each fact once: not in the description and again in a prompt section, not in one tool and again in another.
- Errors are results: return a short message that names the cause and the next step; raise only for programming errors.
- Approval gates (`approval=`) carry a one-line `description` of the effect the user approves.

## Prompt sections (`ctx.prompt.add`)

- One section per concern, under a `##` heading; three to six lines. Every section is in every request.
- Guidance that only matters once a capability is used belongs in that tool's description or in a skill.
- A callable section renders once per graph build; values that change per session do not belong in the prompt.

## Skills

- `SKILL.md` frontmatter: `name` (directory name) and `description` written so that the catalog line alone routes the request: start with "Use when ...".
- Body under 8000 characters: a procedure with numbered steps, then a table of files to read next. Reference material goes to `references/`, copyable files to `templates/`.
- State the knowledge-source order (inspection, documentation, files) so the model does not guess.

## Subagents (`ctx.agentLoop.add_subagent`)

- `description` says what tasks to delegate and what the result looks like; the parent decides from it alone.
- Give the subagent the smallest tool set that completes its task; tools are named by registered name.

## Continuation and status messages

- One line per fact: generation, reason, what is new, what the task continues with.
- No history, no apology, no restatement of the previous turn.

## Measure

Compare first-request prompt size (`harness_inspect topic=prompt` lists section sizes; `topic=tools name=<tool>` shows a schema) before and after a change.
