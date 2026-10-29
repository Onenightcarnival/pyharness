# pyharness-audit

Example third-party bundle.

| extension point | effect                                          |
|-----------------|-------------------------------------------------|
| `tools/execute` | tools in `deny` return an error without running |
| `tools/result`  | one line per call in `${data_dir}/audit.jsonl`  |
| `GET /audit`    | last `tail` lines of the log                    |

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
