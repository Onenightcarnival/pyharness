# Bundles and plugins

## Bundle layout

```
/plugins/<name>/                 # the profile's plugin source directory
  AGENTS.md                     # design of the plugin
  pyproject.toml                # distribution; two entry points
  <module>/__init__.py          # imports of the public names; no other code
  <module>/plugin.py            # the plugin
  <module>/bundle.py            # BUNDLE: the path of bundle.yaml
  <module>/bundle.yaml          # mount position: patch ops over the profile tree
```

A plugin that outgrows `plugin.py` splits into modules (`service.py`, `tools.py`, `routes.py`, `config.toml`, `prompts.toml`); `conventions.md` gives the layout and its rules.

`pyproject.toml` declares:

| entry-point group | value | meaning |
|---|---|---|
| `pyxis_harness.plugins` | `<dist> = "<module>"` | the plugin; an entry's `name` refers to it |
| `pyxis_harness.bundles` | `<bundle> = "<module>:BUNDLE"` | `BUNDLE` is the path of `bundle.yaml` |

`dependencies` lists only packages the harness does not provide, each pinned to an exact version (`httpx==0.28.1`). Provided: `pyxis-harness-core`, `pydantic`, `langchain-core`, `langchain`, `fastapi`. A dependency is installed with `uv pip install --target` into the profile `site/`, constrained to the versions the harness runs on: a requirement that contradicts one of them, or an unavailable package, rejects the installation and installs nothing.

`bundle.yaml`:

```yaml
title: Audit log
description: One line.
patch:
  - id: audit            # entry id; unique in the tree
    name: pyxis-harness-audit  # plugin entry-point name
    after: tools          # position; or before / parent
    config:
      path: ${data_dir}/audit.jsonl
```

Variables: `${data_dir}`, `${profile_dir}`, `${runtime_dir}`, `${home}`, `${cwd}`, `${profile}`, `${env:NAME:-default}`.

## Plugin forms

Module with `apply`:

```python
name = "pyxis-harness-audit"  # optional; defaults to the entry-point name
inject = ["tools"]  # services read as ctx.<key>: required before start; missing → entry PENDING


class Config(BaseModel): ...  # validates the entry's config; omitted → config None


def apply(ctx, config): ...  # sync or async; returns nothing
```

`Service` subclass, providing one service under `key`:

```python
from typing import ClassVar

from pyxis_harness import Service


class AuditService(Service):
    key = "audit"  # ctx.audit for other plugins
    inject: ClassVar[list[str]] = ["tools"]
    Config = AuditConfig

    async def start(self): ...
    async def stop(self): ...
    def record(self, line): ...  # self.caller is the calling plugin's context
```

`apply` receives the plugin's `ctx` (`pyxis_harness.Context`): services as attributes (`ctx.tools`, `ctx.http`), `ctx.get(key, default)`, `ctx.has(key)`, `ctx.logger`, `ctx.lifecycle`, `ctx.loader`, `ctx.get("profile")`, `ctx.get("workspace")`.

## Reading services

| form | rule |
|---|---|
| `ctx.<key>` | the key is in the plugin's `inject`, or the plugin provides it, or it is a kernel service (`lifecycle`, `events`, `profile`, `loader`); any other key raises `AttributeError` |
| `ctx.get(key, None)` | an optional service: `None` while no provider is active; no `inject` entry |
| `self.caller` in a `Service` method | context of the calling plugin, in plain, `async`, generator and async-generator methods |

## Ownership of registrations

Every registration made through `ctx` belongs to the plugin and is undone, in reverse order, when the entry stops or fails:

| call | effect |
|---|---|
| `ctx.tools.register(fn_or_tool, approval=...)` | tool; `approval` is an interrupt config or `False` |
| `ctx.on("tools/result", fn)` / decorator | listener; the call form returns its disposer |
| `ctx.prompt.add(id, text_or_callable, order=100)` | system prompt section |
| `ctx.http.include_router(router, prefix="")` | routes |
| `ctx.provide(key, value)` | service; conflicts with an existing provider |
| `ctx.define_event(name, mode, doc)` | new event |
| `ctx.effect(setup)` | `setup()` runs now; a callable it returns is the disposer |
| `await ctx.enter(cm)` | context manager exited at stop |
| `ctx.on_dispose(fn)` | any cleanup |

Objects created outside `ctx` (threads, files, subprocesses) need `ctx.on_dispose`.

## Install, enable, observe

| action | effect |
|---|---|
| `install_bundle target=/plugins/<name>` | installs the directory into `site/`, enables the bundle, preflights, saves or restores |
| `uninstall_bundle target=<bundle>` | removes the distribution and disables the bundle |
| `set_bundle_enabled`, `set_plugin_enabled` | toggles; preflighted |
| `list` | entries with state (`active`, `pending`, `disabled`, `failed`), installed bundles |

Reinstalling the same directory upgrades it: the newest dist-info wins and older ones are pruned.

Entry states after boot: `active`; `pending` lists the missing services (`inject`); `failed` carries the error. An entry that fails at start does not stop the harness; its registrations are undone.
