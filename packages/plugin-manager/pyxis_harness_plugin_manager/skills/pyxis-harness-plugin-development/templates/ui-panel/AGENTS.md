# __DIST__

__TITLE__: a Web UI panel with a sidebar row, fed by a server-side call.

| item | value |
|---|---|
| entry | `__BUNDLE__`, after `web-ui` |
| plugin | `apply(ctx, config)` of `__MODULE__` |
| inject | `webui` |

## Files

| file | content |
|---|---|
| `__MODULE__/__init__.py` | exports |
| `__MODULE__/plugin.py` | the plugin: `Config`, `apply` |
| `__MODULE__/bundle.py` | `BUNDLE`: the path of `bundle.yaml` |
| `__MODULE__/client.js` | browser module of the entry; plain JavaScript, no bundler |
| `__MODULE__/bundle.yaml` | mount position of the entry |

## Extension points

| extension point | effect |
|---|---|
| `ctx.webui` | serves `client.js` at `/plugins/__BUNDLE__/client.js`; `calls["stats"]` answers `ctx.host.call("stats")` from the page |
| `tools/result` | counts finished tool calls per tool name; the panel shows them |

## Configuration

| key | meaning | default |
|---|---|---|
| `greeting` | text the panel shows under its title | `Hello from __TITLE__` |
