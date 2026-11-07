# pyharness-otel

`ctx.otel`：按 OpenTelemetry GenAI 语义约定（semantic conventions）把每一轮对话（turn）上报到 OTLP/HTTP 后端（如 Langfuse），并提供「设置 → 可观测」页面。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 包契约文档字符串；从子模块导出 `__all__` |
| `pipeline` | 端点解析（`normalize_endpoint`、`signal_url`、`basic_auth`、Langfuse 判定）；`CountingExporter`（批次 / span 计数、最近结果、根 span 的 trace id）；`Pipeline`（TracerProvider、BatchSpanProcessor、OTLP exporter） |
| `spans` | `build_turn_spans`：由 turn 记录与运行事件生成一轮的 span 树；`AGENT_SYSTEM`、`FINISH` |
| `service` | `Config`、`OtelService`：生命周期、`agent/turn-end` 监听、`status` / `save` / `test` / `verify_recent`、`/api/otel` 路由 |
| `client.js` | 浏览器模块 `otel`：设置页「可观测」分区（端点、密钥、开关、高级选项、发送测试、检查上报、状态与计数） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | 服务配置；字段见「服务」 |
| `OtelService` | 类 | `Service` 子类，key `otel`；entry point `pyharness-otel` |
| `Pipeline` | 类 | `Pipeline(config, secret, *, exporter=None)`：`tracer`、`flush(timeout_ms)`、`shutdown()`、`endpoint`、`trace_endpoint`、`langfuse`、`headers`、`exporter` |
| `build_turn_spans` | 函数 | `build_turn_spans(tracer, turn, *, session, events, capture, limit, system_prompt, tool_defs, user_input)` → trace id |
| `normalize_endpoint` | 函数 | `normalize_endpoint(raw, langfuse_hint=False)`：补 `https://`，Langfuse 主机追加 `/api/public/otel`，空串返回 `""` |
| `signal_url` | 函数 | `signal_url(base, signal)`：`<base>/v1/<signal>`；已含 `/v1/traces` 或 `/v1/metrics` 时替换 |

## 服务

| 项 | 值 |
|---|---|
| key | `otel` |
| inject | `http`、`webui` |
| `enabled` | `False`；是否上报 |
| `endpoint` | `""`；OTLP 基址 |
| `public_key` | `""`；Basic-auth 用户名（Langfuse `pk-lf-…`） |
| `secret_key` | `"OTEL_SECRET_KEY"`；Basic-auth 密码的凭据引用名 |
| `capture_content` | `True`；消息、系统提示、工具定义、参数与结果写入 span |
| `content_max_chars` | `128000`（100–10,000,000）；单属性上限，超出替换为 `{"truncated": true, …}` |
| `gzip` | `False`；压缩 OTLP 请求 |
| `max_export_batch_size` | `512`（1–4096）；每次导出的 span 数 |
| `max_queue_size` | `2048`；队列上限（不小于 `max_export_batch_size`） |
| `trace_export_interval_ms` | `5000`；批处理间隔 |
| `export_timeout_ms` | `30000`；导出超时 |
| `service_name` | `"pyharness"`；`service.name` 资源属性 |
| start | 监听 `agent/turn-end`；挂载 `/api/otel` 路由；注册 `client.js`；`apply()` 按当前配置启动管线（未启用或无端点时不启动） |
| stop | 在线程中关闭管线 |

## 事件 / 路由 / Web UI

| 事件 | 角色 | 行为 |
|---|---|---|
| `agent/turn-end` | 监听 | 取 `turn.extras["turn"]` 记录、会话、运行事件、系统提示与工具定义，在线程中构建 span；失败记录 `last_error` 并告警 |

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/otel/status` | `status()`：配置（不含密钥值）、`running`、导出计数、最近导出结果、`traceEndpoint`、`langfuse`、`lastError` |
| PUT | `/api/otel/settings` | `save(data)`：写入 profile 条目 `otel`（`manage.set_entry_config`，merge，无预检），`secretKey` 写入凭据库（空串删除），原地重启管线；启用而无端点 → 400，整数越界 → 400，预检拒绝 → 422 |
| POST | `/api/otel/test` | `test(data)`：临时管线依次发送连通性、900 KB 载荷、GenAI 轮次三组测试 span；Langfuse 端点再查询入库；无端点 → 400，导出失败 → 502 |
| POST | `/api/otel/verify` | `verify_recent()`：查询最近 8 个 trace 是否入库；未运行、非 Langfuse 或无导出 → 409 |

| Web UI slot | key | 位置 |
|---|---|---|
| `settings.sections` | `observability` | order 110 |

## 数据

| 项 | 内容 |
|---|---|
| 凭据 | profile 凭据库中 `config.secret_key` 引用名（默认 `OTEL_SECRET_KEY`）下的 Basic-auth 密码 |
| 配置 | profile patch 中条目 `otel` 的 `config` |
| trace 形状 | 一轮一条：`enter_ai_application_system`（ENTRY，SERVER）→ `invoke_agent <preset>`（AGENT，CLIENT）→ `react step`（STEP，INTERNAL）→ `chat <model>`（LLM，CLIENT）与 `execute_tool <name>`（TOOL，INTERNAL） |
| 公共属性 | `gen_ai.agent.system`、`gen_ai.agent.name`、`gen_ai.session.id`、`gen_ai.turn.id`、`pyharness.session.id`、`pyharness.turn`、`pyharness.agent.preset`、`langfuse.session.id`、`session.id`、`pyharness.session.workspace` |
| 用量属性 | `gen_ai.usage.input_tokens` / `output_tokens` / `cache_read.input_tokens` / `cache_creation.input_tokens` / `total_tokens` / `reasoning_tokens`；`gen_ai.response.time_to_first_token`（纳秒） |
| 正文属性 | `capture_content` 时：`gen_ai.input.messages`、`gen_ai.output.messages`、`gen_ai.system_instructions`、`gen_ai.tool.definitions`、`gen_ai.tool.call.arguments`、`gen_ai.tool.call.result`（JSON，受 `content_max_chars` 限制） |
| 资源属性 | `service.name`、`service.instance.id`（`<name>@<host>:<pid>`）、`telemetry.sdk.language`、`gen_ai.agent.system` |
| span 状态 | turn `completed` / `interrupted` → OK；`error` → `Error`，`cancelled` → `ABORTED`；工具 `error` → `ToolError`，`pending` → `INTERRUPTED` |
