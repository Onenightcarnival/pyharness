---
name: pyxis-harness-plugin-development
description: "Use when designing, reviewing, writing, installing, enabling, disabling, configuring, or debugging a plugin, bundle, tool, event listener, prompt section, or HTTP route of this harness profile, and when a request needs a capability the current tools do not have."
---

# Persistent harness plugins

A plugin is a Python distribution installed into the current profile with `plugin_manager action=install_bundle`. The change affects every session of the profile and survives restarts. Profile files (`profile.yaml`, `harness.patch.yaml`, `site/`) change only through `plugin_manager`; a hand-made write there is denied by the file tools.

Every mutating `plugin_manager` action waits for the user's approval; `list` and `template` do not. Call mutating actions only when their result decides the next step.

## Design or review

Read the references below and inspect the proposed or existing plugin against the live API with `harness_inspect`. Report findings. Do not write files or install anything unless the user asks for implementation.

## Deliver a working plugin first

1. Resolve the requested result: a tool, a listener on an event, a prompt section, an HTTP route, a service, or a combination. Choose a small first version; install it before refinement.
2. Discover only the APIs that version needs: `harness_inspect topic=services name=<key>` for methods and signatures, `topic=events` for event names and dispatch modes, `topic=config name=<entry id>` for a config schema and the package directory, `topic=tools` and `topic=routes` for what exists. Read `references/practices.md` before choosing an extension point for anything beyond a plain tool, and `references/conventions.md` before a plugin grows beyond one file.
3. `plugin_manager action=template target=<name>` returns starter files (`variant=tool-and-route` adds a listener and a route; `variant=ui-panel` adds a Web UI panel with a browser module). Write them under `/plugins/<name>/` with the file tools, then edit; `/plugins/` is the profile's plugin source directory, the same in every session. The same files are in this skill's `templates/` directory with `__DIST__`, `__MODULE__`, `__BUNDLE__`, `__TITLE__` tokens. Check the module imports (`python -c "import ..."` through the shell when available, from the directory on disk named in the "Plugin sources" section of the system prompt) before installing.
4. `plugin_manager action=install_bundle target=/plugins/<name>`. Read the result's `application`:
   - `rejected`: `stage` and `errors` say why; the profile is unchanged. Fix and install again.
   - `restart-scheduled`: saved; the harness restarts after this turn and this session continues in the next generation. End the turn with a one-line status.
   - `saved-restart-required`: saved; unsupervised harness, applies on the next start.
5. In the new generation: `harness_inspect topic=plugins name=<entry id>` shows the entry `active`; exercise the capability (call the tool, request the route through the shell or ask the user); fix defects in the same plugin. A rollback marker in the continuation message means the generation failed to boot and the previous configuration runs: read `boot-error.json` in the profile's `runtime/` directory through `harness_inspect topic=overview` paths, fix, reinstall.
6. Finish with the entry id, what was verified, and what was not. Do not add speculative features.

## Install a published plugin

`plugin_manager action=install_bundle target=<package requirement>` (for example `pyh-example` or `pyh-example==0.1.0`) installs a bundle from PyPI with its dependencies, then preflights like a directory install. The package must declare a `pyharness.bundles` entry point; otherwise the install is rejected and rolled back.

## Enable, disable, configure a shipped plugin

`plugin_manager action=set_plugin_enabled target=<entry id> enabled=<bool>` toggles an entry; `set_bundle_enabled` toggles a bundle. Configuration of an existing entry changes through a bundle whose patch overrides that entry (`editing-pyxis-harness-compositions` skill): `id`, `config`, `merge: true`.

## Knowledge sources, in order

1. Inspection: `harness_inspect` answers from the running process: services and their methods, events with modes and listeners, config JSON Schemas and effective values, registered tools and approval gates, HTTP routes, prompt sections.
2. Package documentation: `harness_inspect topic=config name=<entry id>` returns `docs`, the path of the package's `AGENTS.md` (its design: files, members, configuration, routes, rules), `package_dir` and `doc`. Read `docs` with the file tools when the inspection leaves a question open, then the sources under `package_dir`; both lie under `/harness/<module>/`, the read-only mount of the package.
3. Reference files of this skill (table below).

## Read next

Paths are relative to this skill's directory, which the skill catalog shows. Read with the file tools; the directory is read-only.

| Task | File |
|---|---|
| Bundle layout, entry points, plugin forms, `inject`, `Config`, ownership of registrations | `references/host-plugin.md` |
| Choosing extension points: tool pipeline, events, prompt, services, stability rules | `references/practices.md` |
| Code conventions: module layout beyond one file, `__all__`, Protocols instead of import cycles, `config.toml` / `prompts.toml`, pinned dependencies | `references/conventions.md` |
| HTTP routes and pages on `ctx.http` | `references/http.md` |
| Web UI panels, sidebar rows, settings and right-sidebar tabs: browser module, slots, `ctx.host.call` | `references/ui-plugin.md` |
| What can be verified after the restart, and what cannot | `references/verification.md` |
| Starter files | `templates/basic/`, `templates/tool-and-route/`, `templates/ui-panel/` |
| Patch dialect: ids, merge, remove, position, interpolation, isolate | the `editing-pyxis-harness-compositions` skill |
| Installed plugin packages and bundles | the `pyxis-harness-composition-reference` skill |
