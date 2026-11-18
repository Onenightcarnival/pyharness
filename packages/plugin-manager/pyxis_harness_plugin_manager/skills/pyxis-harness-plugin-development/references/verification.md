# Verification

## What the installation result establishes

| field | meaning |
|---|---|
| `application: rejected`, `stage`, `errors` | nothing changed; `stage` is `install`, `dependencies`, or `preflight` |
| `application: restart-scheduled`, `preflight.ok` | saved; the configuration booted in a separate process up to `app/ready`; restart after this turn |
| `preflight.pending` | entries whose `inject` is unmet in that boot; headless preflight has no `http` |
| `preflight.warnings` | compose warnings, such as a patch target not found |

`app/serve` does not run in preflight: port binding and anything on `app/serve` is verified only in the next generation.

## In the next generation

The continuation message names the generation and the reasons; `rollback` in it means the new generation failed to boot and the previous configuration runs. Then:

1. `harness_inspect topic=plugins name=<entry id>`: state `active`; `failed` carries the error, `pending` the missing services.
2. Exercise the capability: call the tool; for a route, request it through the shell (`curl http://127.0.0.1:<port>/<prefix>`) or inspect `harness_inspect topic=routes`; for a listener, trigger the event and read the effect (a log line, a file under `${data_dir}`, a store entry).
3. Confirm the model-visible surface: `harness_inspect topic=tools name=<tool>` shows the description and schema as the model sees them; `topic=prompt` lists sections and sizes.

## Limits

- Without a shell tool, a route is verified by `harness_inspect topic=routes` and the user's browser; say so.
- A page's appearance cannot be seen from here; report the URL and what was checked.
- Logs of the harness process are in the terminal running `pyh run`, not in the workspace; `runtime/boot-error.json` in the profile directory records a failed boot.
- Clean up test files written to the workspace during verification.
