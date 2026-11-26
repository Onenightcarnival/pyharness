# pyxis-harness-mcp

MCP 服务器的工具：启动时注册进 `ctx.tools`。

| 项 | 值 |
|---|---|
| 条目 | `mcp`（`base` bundle） |
| 服务 | `MCPService`，`ctx.mcp` |
| 注入 | `tools` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `MCPService`、`managed_bun` |
| `config.py` | `mcp` 条目的配置模型 |
| `templates.py` | MCP 服务器传输字符串中的凭据模板 |

## 配置

| 配置 | 含义 |
|---|---|
| `servers.<name>` | stdio：`command`、`args`、`env`、`cwd`；HTTP / SSE 传输：`url`、`headers` |
| `${credential:REF}` | 写在上述任一字符串内：一个凭据，连接时解析 |
| `servers.<name>.enabled` | `false`：保留配置，不连接 |
| `servers.<name>.approval` | 该服务器全部工具的审批门：`true` 或 LangChain `InterruptOnConfig` |
| `servers.<name>.prefix` | 工具名为 `<server>_<tool>`（默认） |
| `connect_timeout` | 列出一个服务器的工具的秒数上限；超出 → 状态 `error` |

## 连接

| 情形 | 契约 |
|---|---|
| 连接失败 | 记入 `MCPService.status`，跳过；harness 照常启动 |
| 工具执行 | 经 `tools/execute` 管线；权限模式与审批适用 |
| stdio 服务器，命令为裸 `bun` / `bunx` | 配置中心安装的 bun 运行时（`<profile data>/toolkit/bun/`）存在时经它运行；`managed_bun` 查找 |

## HTTP 客户端

| 项 | 契约 |
|---|---|
| 适用 | `streamable_http`、`sse` 连接：连接的 `httpx_client_factory` 为 `http_client` |
| `http_client(headers, timeout, auth)` | `httpx.AsyncClient`，`trust_env=False`：环境变量与系统的代理设置不生效 |
| 默认超时 | MCP 的默认值：30 秒；读取流 300 秒 |

## 凭据

`env` 与 `headers` 中的机密不写入配置文件。

| 写法 | 值 |
|---|---|
| `${credential:REF}` | 环境变量 `REF`，否则 profile 凭据库（`credentials.yaml`） |
| `${env:VAR}` | 环境变量 `VAR`；启动时插值 |

| 情形 | 契约 |
|---|---|
| 无 profile | 凭据只从环境变量解析 |
| 凭据未解析 | 服务器状态 `waiting-credentials`，不连接 |
| 已解析的凭据值 | 在状态错误、探测错误、日志中显示为 `[redacted]` |

## 凭据模板（`templates.py`）

| 项 | 契约 |
|---|---|
| 语法 | `${credential:REF}`；`REF` 遵循 `pyxis_harness.credentials.REFERENCE` |
| 字段 | `command`、`args`、`env` 的值、`cwd`、`url`、`headers` 的值 |
| 混合 | 一个值含字面文本与任意数量的模板（`Bearer ${credential:GH_TOKEN}`） |
| 其余文本 | 字面量；`REF` 非法的 `${credential:...}` 亦然 |
