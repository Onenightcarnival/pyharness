# __DIST__

__TITLE__: one tool, one `tools/result` listener, one HTTP route.

| item | value |
|---|---|
| entry | `__BUNDLE__`, after `tools` |
| plugin | `apply(ctx, config)` of `__MODULE__` |
| inject | `tools`, `http` |

## Files

| file | content |
|---|---|
| `__MODULE__/__init__.py` | exports |
| `__MODULE__/plugin.py` | the plugin: `Config`, `apply` |
| `__MODULE__/bundle.py` | `BUNDLE`: the path of `bundle.yaml` |
| `__MODULE__/bundle.yaml` | mount position of the entry |

## Extension points

| extension point | mode | effect |
|---|---|---|
| `ctx.tools` | | `__MODULE___note` tool, owned by this plugin |
| `tools/result` | parallel | counts finished tool calls per tool name |
| `ctx.http` | | `GET /__BUNDLE__` returns the notes and the counts |

## Configuration

| key | meaning | default |
|---|---|---|
| `prefix` | route prefix on `ctx.http` | `/__BUNDLE__` |
| `max_note_chars` | longest note the tool accepts | `2000` |
