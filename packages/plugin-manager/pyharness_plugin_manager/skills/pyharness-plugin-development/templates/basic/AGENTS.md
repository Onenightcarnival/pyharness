# __DIST__

__TITLE__.

| item | value |
|---|---|
| entry | `__BUNDLE__` |
| plugin | `apply(ctx, config)` of `__MODULE__` |
| inject | `tools` |

## Files

| file | content |
|---|---|
| `__MODULE__/__init__.py` | the plugin: `Config`, `apply` |
| `__MODULE__/bundle.yaml` | mount position of the entry |

## Extension points

| extension point | effect |
|---|---|
| `ctx.tools` | `greet` tool |

## Configuration

| key | meaning | default |
|---|---|---|
| `greeting` | word the `greet` tool starts with | `hello` |
