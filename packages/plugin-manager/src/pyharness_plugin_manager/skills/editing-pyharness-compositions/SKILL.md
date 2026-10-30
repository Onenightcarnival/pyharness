---
name: editing-pyharness-compositions
description: "Use when writing or reading a bundle patch (bundle.yaml) or the profile patch of this harness: changing an entry's config, position, or disabled state, inserting or removing entries, isolating services in a group, and checking how layers compose."
---

# Editing compositions

The profile's configuration tree is composed at boot from ordered layers; each layer is a list of patch operations addressed by entry id. Nothing edits the tree in place: a change is a bundle whose patch carries the operations, installed with `plugin_manager`.

| layer | source | order |
|---|---|---|
| bundles | `bundle.yaml` of each bundle in `profile.yaml`, in list order | 1 |
| profile patch | `harness.patch.yaml` in the profile directory; written by `plugin_manager` and the settings page | 2 |
| home patch | `harness.patch.yaml` in the harness home; every profile | 3 |
| `--patch` overlays | files given to `pyh run` | 4 |

Later layers win. `pyh dump-config` prints the composed tree with each entry's source layer; `harness_inspect topic=config` lists entries with their effective config.

## Operations

```yaml
patch:
  - id: llm                      # existing id: replace the fields the op sets
    config:                      # config replaced wholesale ...
      default: openai:gpt-4o
  - id: llm                      # ... or deep-merged with merge: true
    merge: true
    config:
      providers:
        openai:
          base_url: http://127.0.0.1:23333/v1
  - id: web-ui                   # disable or enable
    disabled: true
  - id: checkpoint               # delete
    remove: true
  - id: audit                    # new id: insert; name or children required
    name: pyharness-audit
    after: tools                 # position: after / before <id>, or parent <group id>
    config:
      path: ${data_dir}/audit.jsonl
  - id: experiments              # group: children form a sub-tree
    children:
      - id: scratch-tools
        name: pyharness-tools
    isolate: [tools]             # the group gets its own `tools`; outer providers are invisible for that key
```

Rules:

- An id is unique in the whole tree; a duplicate fails composition.
- `name` on an existing id renames the plugin (replaces the entry's plugin); position fields on an existing id are ignored with a warning.
- A new entry without `name` and without `children` is skipped with a warning; an unknown anchor appends to the root with a warning.
- `config` without `merge` replaces the whole mapping: restate every field the entry needs.
- `${env:NAME}` → environment variable, unset → empty; `${env:NAME:-default}`; `${data_dir}`, `${profile_dir}`, `${runtime_dir}`, `${home}`, `${cwd}`, `${profile}`. A string that is exactly one unset `${env:NAME}` becomes null.

## Entry fields

| field | meaning |
|---|---|
| `id` | address for patches; stable |
| `name` | plugin: entry-point name of `pyharness.plugins`, or `module[:attr]` |
| `config` | validated by the plugin's `Config` model; unknown fields fail |
| `disabled` | entry and its registrations absent; dependents of its service become `pending` |
| `isolate` | group only: service keys the group provides for itself |
| `children` | group members |

## Placement

A plugin consumed by others (a service) comes before its consumers; `inject` also makes consumers wait, so order inside a layer is a tie-breaker, not a dependency mechanism. A plugin that replaces the agent loop overrides the `agent-loop` entry by id. A plugin for one experiment goes into a group with `isolate` so its `tools` or `prompt` registrations stay out of the main agent.

## Verify

`plugin_manager action=list` shows every entry with its state and source layer. A patch that targets a missing id produces a compose warning in the preflight report; it does not fail the boot. `pyh preflight` runs the composition in a separate process and reports errors, pending entries, and warnings.
