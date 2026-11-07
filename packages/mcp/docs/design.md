# pyharness-mcp

`ctx.mcp`：启动时把 MCP（Model Context Protocol）服务器的工具注册进 `ctx.tools`；stdio 或 HTTP / SSE 传输。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `ServerConfig`、`Config`、`MCPService`；`slug`、`managed_bun`、`connection_of`；`MASK` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | `servers`、`connect_timeout` |
| `MCPService` | 类 | `Service`，key `mcp` |
| `ServerConfig` | 模型 | 一个服务器的配置 |
| `connection_of` | 函数 | `connection_of(cfg, data_dir=None)` → `langchain-mcp-adapters` 连接字典；无 `command` 也无 `url` → `ValueError` |
| `managed_bun` | 函数 | `managed_bun(data_dir)` → `(exe, env)`；`<data_dir>/toolkit/bun/bin/bun` 不存在 → `None` |
| `slug` | 函数 | 服务器名 → `[A-Za-z0-9_]` 前缀；空 → `"server"` |

## 服务

| 项 | 值 |
|---|---|
| key | `mcp` |
| name | `pyharness-mcp` |
| inject | `tools` |
| `Config.servers` | `{}`；`name → ServerConfig` |
| `Config.connect_timeout` | `20.0` 秒；连接并列出工具的上限 |
| `ServerConfig.transport` | `None`：有 `command` 为 `stdio`，否则 `streamable_http`；可选 `sse` |
| `ServerConfig.command` / `args` / `env` / `cwd` | stdio 服务器；`args`、`env` 默认空 |
| `ServerConfig.url` / `headers` | HTTP / SSE 服务器 |
| `ServerConfig.enabled` | `True`；`False` 时保留配置、不连接，状态 `disabled` |
| `ServerConfig.approval` | `False`；`True` 或 `InterruptOnConfig`，作用于该服务器全部工具 |
| `ServerConfig.prefix` | `True`；工具名变为 `<slug(server)>_<tool>` |
| `start()` | 逐服务器 `MultiServerMCPClient.get_tools()`，超时按 `connect_timeout`；失败记 `error` 状态并跳过，不影响启动；注册 tag `("mcp", name)`；同名冲突记告警 |
| `stop()` | 无 |
| `probe(cfg, timeout=None)` | 连接但不注册：`{"ok": True, "tools": [...]}` 或 `{"ok": False, "code": "timeout" / "error", "error"}` |
| `status()` | 每服务器 `state`（`connected` / `error` / `disabled`）、`tools`、`error` |
| `servers()` | 配置（`env`、`headers` 值替换为 `MASK` `"••••"`）合并状态；未记录状态的为 `unknown` |
| `data_dir()` | `ctx.profile.data`；无 profile → `None` |

| 受管 bun | 规则 |
|---|---|
| 触发 | `command` 为裸 `bun` / `bunx` / `bun.exe` / `bunx.exe` 且 `<profile data>/toolkit/bun/bin/bun` 存在 |
| 命令 | 换成受管的 `bun` 或 `bunx` 绝对路径 |
| 环境 | 注入 `BUN_INSTALL`、`BUN_INSTALL_CACHE_DIR`、`NO_UPDATE_NOTIFIER=1`，配置的 `env` 覆盖之；PATH 不改 |

## 工具

| 工具 | 审批 | 标签 |
|---|---|---|
| `<server>_<tool>`（`prefix: false` 时原名） | `ServerConfig.approval` | `mcp`、`<server>` |

工具调用经 `tools/execute` 管线，权限模式与审批同样生效。

## 数据

| 项 | 位置 |
|---|---|
| 服务器配置 | 条目 `mcp` 的 `config.servers`（profile patch；`${env:VAR}` 插值保持密钥不落盘） |
| 受管 bun | `<profile data>/toolkit/bun/`（由 `pyharness-config-center` 安装） |
