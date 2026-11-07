# pyharness-http

`ctx.http`：FastAPI 根应用与 uvicorn 服务器；其他插件经 `include_router` / `mount` 贡献路由。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `HttpConfig`、`HttpService`；`_Server`（无信号处理的 `uvicorn.Server`，信号归 worker） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `HttpConfig` | 模型 | 服务配置 |
| `HttpService` | 类 | `Service`，key `http` |

## 服务

| 项 | 值 |
|---|---|
| key | `http` |
| name | `pyharness-http` |
| inject | 无 |
| `Config.host` | `"127.0.0.1"` |
| `Config.port` | `8765` |
| `Config.serve` | `True`；为假时 `app/serve` 不绑定端口 |
| `Config.log_level` | `"warning"` |
| `Config.title` | `"pyharness"` |
| `Config.shutdown_timeout` | `5` 秒；停止时进行中请求的宽限 |
| `start()` | 监听 `app/serve` → `_serve`；监听 `app/stopping` → `stop` |
| `stop()` | 置 `should_exit`，等待服务任务至多 15 秒 |
| `_serve()` | 先 `bind` socket（IPv6 按 host 含 `:` 判断，`SO_REUSEADDR`），再以 `lifespan="off"` 启动 uvicorn；绑定失败或启动失败 → `RuntimeError`，启动失败；`bound_port` 记录实际端口 |
| `include_router(router, prefix="", **kwargs)` | 归属 `caller`；返回 disposer，撤销时移除新增路由并清空 `openapi_schema` |
| `mount(path, app, name=None)` | 挂载 ASGI 子应用，归属 `caller`；返回 disposer |
| `routes()` | 展平的 `{"path", "methods"}` 列表（展开 included router 的前缀） |
| `contributions()` | `{"kind": "router" / "mount", "prefix", "owner", "routes"}` 列表 |
| `app` | `FastAPI(title=config.title)` 实例 |

## 事件

| 事件 | 角色 | 效果 |
|---|---|---|
| `app/serve` | 监听 | 绑定 socket、启动 uvicorn；失败 → 启动失败 |
| `app/stopping` | 监听 | 停止接收请求；进行中请求有 `shutdown_timeout` 秒 |
