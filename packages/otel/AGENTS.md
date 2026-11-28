# pyxis-harness-otel

agent 回合的 OpenTelemetry 导出（GenAI 语义约定），目标为 OTLP/HTTP 后端，如 Langfuse。

| 项 | 值 |
|---|---|
| 条目 | `otel`（`base` bundle） |
| 服务 | `OtelService`，`ctx.otel` |
| 注入 | `http`、`webui` |
| 路由前缀 | `/api/otel` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `OtelService`：配置、回合结束钩子、可观测的状态 / 设置 / 测试路由 |
| `config.py` | 插件配置 |
| `pipeline.py` | OTLP 端点解析与导出管线：tracer provider、批处理器、计数导出器；导出用的 `requests` 会话 `trust_env=False`，环境变量与系统的代理设置不生效 |
| `spans.py` | 一个回合的 GenAI span 树 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `status()` | 配置（不返回密钥）、管线状态、导出计数 |
| `save()` | 把设置写入 profile，原地重启管线 |
| `test()` | 发送测试 span（连通性、负载、GenAI 形状），并在 Langfuse 上校验 |

| 配置 | 含义 |
|---|---|
| `enabled` | 导出回合；默认关闭 |
| `endpoint` | OTLP 基址；Langfuse 主机追加 `/api/public/otel` |
| `public_key` | Basic 认证的用户名（Langfuse `pk-lf-…`） |
| `secret_key` | Basic 认证密码的凭据引用（`OTEL_SECRET_KEY`） |
| `capture_content` | 把消息、系统提示词、工具定义、参数、结果写到 span 上 |
| `content_max_chars` | 单个属性的上限；超出的值变为 `{"truncated": true, …}` |
| `gzip` | 压缩 OTLP 请求 |
| `max_export_batch_size` | 每个导出请求的 span 数 |
| `service_name` | `service.name` 资源属性 |

## Span 树（`spans.py`）

一个回合一条 trace，在 `agent/turn-end` 之后由回合记录构建。

| span 名 | 类型 | 上级 |
|---|---|---|
| `enter_ai_application_system` | ENTRY | 无 |
| `invoke_agent <preset>` | AGENT | ENTRY |
| `react step` | STEP | AGENT |
| `chat <model>` | LLM | STEP |
| `execute_tool <name>` | TOOL | STEP |

| 属性 | 规则 |
|---|---|
| 名称 | dsh-otel 所用的 GenAI 语义约定 |
| Langfuse 别名 | `langfuse.session.id` |

## 路由

| 路径 | 方法 |
|---|---|
| `status` | GET |
| `settings` | PUT |
| `test` | POST |
| `verify` | POST |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 设置 →「可观测」 | 端点、密钥、开关、高级选项、发送测试、检查导出、状态与计数 |
