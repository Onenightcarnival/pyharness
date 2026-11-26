# pyxis-harness-agent

会话与运行：跑在 `ctx.agentLoop` 构建的图之上。

| 项 | 值 |
|---|---|
| 条目 | `agents`（`base` bundle） |
| 服务 | `AgentService`，`ctx.agents` |
| 注入 | `agentLoop`、`store` |
| 数据 | `ctx.store`：`("pyharness", "sessions")`、`("pyharness", "turns", session_id)`；`ctx.checkpointer`：LangGraph thread |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 公开名称 |
| `service.py` | `AgentService`、`AgentConfig`、会话记录的命名空间：会话记录、每个会话的图、运行、重启后的续跑 |
| `runs.py` | 一次运行：`RunHandle`、`Turn`、`TurnRecorder`、`SessionBusy`、`RestartPending`、`NotContinuable` |
| `messages.py` | 消息内容辅助函数：LangChain 消息的文本、图片、推理；`serialize_message`：供 API 的序列化 |
| `prompts.toml` | 模型可见的文本 |

## 概念

| 概念 | 契约 |
|---|---|
| 会话 | LangGraph thread（`ctx.checkpointer`）+ 元数据记录（`ctx.store`） |
| 运行 | 后台任务；事件写入 `RunHandle` |
| 订阅者 | 从头回放；断开连接后运行继续 |
| hold | 每个运行持有 lifecycle 的 hold；挂起的重启等待它 |
| 拒绝 | 重启挂起 → `AgentService.start_run` 抛出 `RestartPending` |
| 续跑 | 受 supervisor 管理的一代在 `app/started` 时：向每个列出的会话发送一条续跑消息 |
| 模型 | `session.model`（`route:model`）以 `configurable.model_spec` 到达 loop |
| 图 | 会话的每组（`workspace`、`mode`、`preset`）一张图，首次使用时构建 |

## 运行（`runs.py`）

| 名称 | 契约 |
|---|---|
| `RunHandle` | 一次运行的事件日志；每个订阅者从头收到全部事件 |
| `Turn` | `agent/turn-start` 与 `agent/turn-end` 的参数 |
| `TurnRecorder` | 一轮的统计与轨迹，取自运行事件与图的 update |
| `SessionBusy` | 会话有运行中的轮次 |
| `NotContinuable` | 会话的最后一轮不可继续 |
| `RestartPending` | 重启挂起；新运行被拒绝 |

## 运行事件

类型：`reasoning`、`token`、`image`、`tool_call`、`tool_result`、`context`、`compact`、`retry`、`interrupt`、`error`、`done`，以及插件经 `publish` 发布的类型。

| 类型 | 契约 |
|---|---|
| `context` | 主 agent 的一次模型请求按部分估算的 token 数；先于该请求的应答 |
| `context` 的字段 | `system`、`tools`、`messages` |
| `compact` | 压缩检查点取代了较早的历史 |
| `compact` 的字段 | `removed`、`before_tokens`、`after_tokens`、`trigger`、`summary` |
| `retry` | 路由的重试策略重跑失败的模型调用；失败那次已流出的文本作废 |
| `retry` 的字段 | `attempt`、`max_retries`、`code`、`message`、`delay_ms` |
| `error` 的字段 | `code`（`pyxis_harness_llm` 的失败代码）、`message`、`continuable` |
| `done` 的 `extras` | `agent/turn-end` 的 `turn.extras` |
| `done` 的 `extras.turn` | 新的每轮记录 |
| `publish(session_id, event)` | 把 `event` 发布到会话正在运行的轮次；没有运行中的轮次时返回 `False` |

## 审批时限

| 项 | 契约 |
|---|---|
| `config.approval_timeout` | 工具审批等待决定的秒数；`None`（默认）：不超时 |
| 适用 | 待处理的中断只有一个工具审批，且其中每个调用都允许 `reject` |
| 期限 | 审批发起时刻 + 时限；`interrupt` 事件的 `deadline`，`approval_deadline(session_id)` |
| 到期 | 一次 kind 为 `approval` 的运行：每个调用以 `prompts.toml` 的 `approval_timeout` 为理由被拒绝，agent 继续 |
| 先有决定 | 会话的下一次运行开始时期限作废 |
| 持久化 | `ctx.store` 的 `("pyharness", "approvals")`：会话 id → `{"deadline"}`；`app/started` 时恢复 |
| 重启挂起时到期 | 下一代恢复期限后拒绝 |
| 时限关闭后启动 | 清除留存的期限；待处理的审批继续等待 |
| `set_approval_timeout(seconds)` | 即时生效，作用于此后发起的审批；持久化由 settings API 完成 |
| 提问（`ask_user_question`） | 不适用 |

## 总线事件

| 事件 | 模式 | 监听者 |
|---|---|---|
| `agent/turn-start` | parallel | `(turn: Turn)` |
| `agent/turn-end` | parallel | `(turn: Turn)`；`turn.outcome` 已设置 |

## 失败的轮次

| 项 | 契约 |
|---|---|
| 每轮记录 | outcome 为 `error` 的轮次保留 `error: {code, message}` |
| `failure(session_id)` | 该轮是最后一轮时，报告这次失败 |
| `retry_run(session_id)` | 失败代码属于 `CONTINUABLE_CODES` 时继续这次失败：一次 kind 为 `retry` 的运行 |
| `retry` 运行 | 图从失败的那一步恢复；不加消息 |

## 图片

| 消息 | 契约 |
|---|---|
| 用户消息 | 文本之外带 `image_url` 内容块（data URL） |
| 序列化后的消息 | 图片列在 `images` 下 |
| 带图片块的 AI 消息 | 发出 `image` 事件；图片同样列在 `images` 下 |

## 每轮记录

| 项 | 契约 |
|---|---|
| 范围 | 每一轮都记录 |
| 位置 | `ctx.store`，命名空间 `("pyharness", "turns", session_id)`，key 为 run id |
| `stats` | 步骤数、工具调用数、token 用量、llm / tool / ttft / decode 的墙钟时间、时长、压缩次数 |
| `stats.context` | 该轮最后一次 `context` 事件：`{"system", "tools", "messages"}`；没有时为 `null` |
| `records` | 轨迹：user、step、tool、compact、retry、end |
| `turns(session_id)` | 列出记录 |
| `done` 事件 | `extras.turn`：新的记录 |

## 提示词（`prompts.toml`）

| 项 | 契约 |
|---|---|
| 表名 | 使用该表的模块名 |
| 加载 | `pyxis_harness.package_prompts`；每个字符串值去除首尾空白 |
| 占位符 | `string.Template` 语法：`${name}` |
