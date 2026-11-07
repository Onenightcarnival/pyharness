# pyharness-agent

`ctx.agents`：会话（session）与运行（run），跑在 `ctx.agentLoop` 构建的图上。

## 模块

| 模块 | 职责 |
|---|---|
| `pyharness_agent/__init__.py` | 契约文档；导出公开名称 |
| `pyharness_agent/service.py` | `AgentService`、`AgentConfig`、会话记录命名空间、运行驱动、重启后续跑 |
| `pyharness_agent/runs.py` | `RunHandle`（事件日志）、`Turn`、`TurnRecorder`（统计与轨迹）、`SessionBusy`、`RestartPending` |
| `pyharness_agent/messages.py` | 消息内容辅助（文本、图片、推理）与 `serialize_message` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `AgentService` | `Service` 子类 | `ctx.agents`：会话、运行、审批、重启后续跑 |
| `AgentConfig` | pydantic 模型 | 服务配置 |
| `RunHandle` | 类 | 一次运行的事件日志；每个订阅者从头收到全部事件 |
| `Turn` | dataclass | `agent/turn-start` / `agent/turn-end` 的参数 |
| `SessionBusy` | 异常（`RuntimeError`） | 会话已有运行中的回合 |
| `RestartPending` | 异常（`RuntimeError`） | 重启待处理；拒绝新运行 |
| `serialize_message` | 函数 | LangChain 消息 → API 字典（`id`、`role`、`content`、`images`、`reasoning`、`tool_calls`…） |

## 服务

| 项 | 值 |
|---|---|
| key | `agents` |
| name | `pyharness-agent` |
| inject | `agentLoop`、`store` |
| `resume_on_restart` | `True`；重启后向列出的会话发送续跑消息 |
| `resume_message` | `DEFAULT_RESUME`；`format_map` 字段 `generation`、`reasons`、`rollback` |
| `title_chars` | `60`；会话标题长度上限 |
| start | 定义 `agent/turn-start`、`agent/turn-end`；监听 `app/ready`（构建默认图）、`app/started`（重启续跑）、`app/stopping`（stop） |
| stop | 取消所有运行任务并等待结束 |

## 事件 / 工具 / 路由 / 提示段

### 定义的事件

| 事件 | 模式 | 监听器签名 |
|---|---|---|
| `agent/turn-start` | parallel | `(turn: Turn)`；运行开始 |
| `agent/turn-end` | parallel | `(turn: Turn)`；`turn.outcome` 已设置；`turn.extras` 进入 `done` 事件的 `extras` |

### 监听的事件

| 事件 | 动作 |
|---|---|
| `app/ready` | 构建默认图（`ctx.agentLoop.build()`） |
| `app/started` | 受监督代际：按交接状态向列出的会话发送续跑消息 |
| `app/stopping` | `stop` |

### 运行事件（`RunHandle` 流）

| 事件 | 内容 |
|---|---|
| `reasoning` | `text` |
| `token` | `text` |
| `image` | `url` |
| `tool_call` | `id`、`name`、`args` |
| `tool_result` | `id`、`name`、`status`、`content`（截至 4000 字符） |
| `compact` | `removed`、`before_tokens`、`after_tokens`、`trigger`、`summary` |
| `interrupt` | `interrupts: [{id, value}]` |
| `error` | `message` |
| `done` | `outcome`、`restart_pending`、`extras`（含 `turn`） |

## 数据

| 项 | 值 |
|---|---|
| 会话记录 | `ctx.store` 命名空间 `("pyharness", "sessions")`，键为会话 id |
| 会话记录形状 | `{id, title, created_at, updated_at, meta, model, workspace, mode, preset}` |
| 回合记录 | `ctx.store` 命名空间 `("pyharness", "turns", session_id)`，键为运行 id |
| 回合记录形状 | `{run_id, session_id, kind, model, at, after, outcome, seq, stats, records}` |
| `stats` | steps、tool_calls、input/output/cache_read/cache_write/reasoning tokens、llm/tool/ttft/decode 毫秒、duration_ms、compactions |
| `records` | 轨迹：`user`、`step`、`tool`、`compact`、`end` |
| 对话历史 | LangGraph 线程（`ctx.checkpointer`），`thread_id` 为会话 id |
| 图缓存 | 每个 `(workspace, mode, preset)` 一张图，首次使用时构建；`invalidate_graphs()` 清空 |
| 运行种类 | `message`、`approval`、`answer`、`continuation`、`compact` |
| 结果 | `completed`、`interrupted`、`cancelled`、`error` |
