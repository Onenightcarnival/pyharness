# HTTP routes and pages

`ctx.http` is the FastAPI root application plus its uvicorn server. A plugin that uses it lists `"http"` in `inject`; without the service (headless `pyh exec`, preflight without the entry) the plugin stays `pending`, which is the intended behavior for route-only plugins. A plugin that works with or without HTTP checks `ctx.get("http", None)` on `app/serve` instead.

| member | contract |
|---|---|
| `ctx.http.include_router(router, prefix="", **kwargs)` | routes under `prefix`; removed when the plugin stops |
| `ctx.http.mount(path, asgi_app, name=None)` | sub-application at `path`; removed when the plugin stops |
| `ctx.http.routes()` | flattened route list (`harness_inspect topic=routes`) |
| `ctx.http.contributions()` | which plugin contributed which prefix |

Reserved prefixes: `/api` (`pyharness-api`), `/` (`pyharness-web-ui`), `/docs` and `/openapi.json` (FastAPI). Choose a prefix named after the bundle.

Pages: a plugin that extends the Web UI itself (a panel, a sidebar row, a settings or right-sidebar tab) registers a browser module with `ctx.webui` and fills a slot; see `references/ui-plugin.md`. A standalone page is an HTML response on a route of its own, self-contained (no external requests), reading data from its own JSON routes; it is a separate document and does not inherit the Web UI theme.

Server: `app/serve` binds the socket; the port is `ctx.http.config.port` and `ctx.http.bound_port` once serving. Requests from the agent's own shell reach it at `http://127.0.0.1:<port>`.

Routes registered inside `apply` exist before `app/serve`; routes registered on `app/serve` also work. Routes are plain FastAPI: `async def`, pydantic bodies, `HTTPException` for errors.
