# pyxis-harness-http

FastAPI 应用及其 uvicorn 服务器。

| 项 | 值 |
|---|---|
| 条目 | `http`（`base` bundle） |
| 服务 | `HttpService`，`ctx.http` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `HttpService`、`HttpConfig` |

## 服务

| 成员 | 契约 |
|---|---|
| `include_router` | 前缀下的 router；归调用方插件所有 |
| `mount` | 路径上的子应用；归调用方插件所有 |
| `routes` | 展平的路由列表 |

## 服务器

| 事件 | 服务器 |
|---|---|
| `app/serve` | 先绑定 socket，再启动 uvicorn；绑定出错则启动失败 |
| `app/stopping` | 停止接收请求；进行中的请求有 `shutdown_timeout` |
