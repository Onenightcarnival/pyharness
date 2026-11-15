# pyharness-audit

Example third-party bundle.

| extension point | mode | effect |
|---|---|---|
| `tools/execute` | waterfall | tools in `deny` return an error without running |
| `tools/result` | parallel | one line per call in `${data_dir}/audit.jsonl` |
| `app/serve` | series | `GET /audit` on `ctx.http`, when the service exists: the last `tail` lines of the log |

`inject` lists only `tools`; the plugin also runs headless.

| file | content |
|---|---|
| `pyharness_audit/__init__.py` | exports |
| `pyharness_audit/plugin.py` | the plugin: `Config`, `apply` |
| `pyharness_audit/bundle.py` | `BUNDLE`: the path of `bundle.yaml` |
| `pyharness_audit/bundle.yaml` | mount position of the entry |

Install (preflighted; a failed preflight leaves the profile unchanged):

```sh
uv run pyh plugin install examples/pyharness-audit
```

Configuration, in the profile patch:

```yaml
- id: audit
  config: {deny: [execute]}
  merge: true
```
