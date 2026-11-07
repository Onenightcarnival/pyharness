# pyharness-compaction

`ctx.compaction`：上下文压缩（context compaction）——一条检查点摘要（checkpoint summary）替换较早的历史。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 包契约文档字符串；从子模块导出 `__all__` |
| `checkpoint` | 标记常量 `CHECKPOINT_KIND` / `COMMAND_KIND`、摘要定界 `SUMMARY_OPEN` / `SUMMARY_CLOSE`、提示文本 `PREAMBLE` / `SUMMARY_SYSTEM` / `INSTRUCTION`；`marker_of`、`is_checkpoint`、`command_of`、`summary_of`、`measure`、`cut_index`、`transcript`、`checkpoint_message`、`_text` |
| `service` | `Config`、`CompactionError`、`_configurable`；`CompactionMiddleware`（模型调用前的 `/compact` 与自动压缩）；`CompactionService`：`settings` / `update` / `window` / `compact_if_needed` / `compact_messages` / `summarize` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | 服务配置；字段见「服务」 |
| `CompactionService` | 类 | `Service` 子类，key `compaction`；entry point `pyharness-compaction`；`last` 为最近一次压缩的标记（诊断） |
| `CompactionMiddleware` | 类 | `AgentMiddleware`，名称 `PyHarnessCompaction`；`abefore_model` 可跳到 `end` |
| `CompactionError` | 类 | 摘要为空，或不小于被替换的历史；`RuntimeError` 子类 |
| `CHECKPOINT_KIND` | 常量 | `"compact-checkpoint"` |
| `COMMAND_KIND` | 常量 | `"command"` |
| `is_checkpoint` | 函数 | 带 `{"kind": "compact-checkpoint"}` 标记的 `HumanMessage` |
| `command_of` | 函数 | user 消息携带的斜杠命令名（`{"kind": "command", "name": …}`），否则 `None` |
| `summary_of` | 函数 | 检查点内容中 `<compacted-summary>` 块内的摘要文本；无块时返回全文 |
| `measure` | 函数 | `measure(messages)`：最近一次模型响应的用量（输入 + 输出）加其后消息的估算；最近检查点之后无用量时估算全部 |
| `cut_index` | 函数 | `cut_index(messages, retain_tokens)`：首条保留原文的消息下标；尾部至少 `retain_tokens`（`0`：不保留），不拆开工具调用与结果；头部为空或仅为检查点时 `None` |
| `transcript` | 函数 | `transcript(messages, tool_result_chars)`：给摘要模型的纯文本转写（`[user]`、`[assistant]`、`[tool call]`、`[tool result: …]`、`[system]`），工具结果超长时取首尾 |
| `checkpoint_message` | 函数 | `checkpoint_message(summary, marker)` → `HumanMessage`：`PREAMBLE` + 定界摘要；`additional_kwargs["pyharness"]` 为 `{"kind": "compact-checkpoint", **marker}` |

## 服务

| 项 | 值 |
|---|---|
| key | `compaction` |
| inject | `agentLoop`、`llm` |
| `auto` | `True`；模型调用前上下文达到 `threshold_ratio` × 窗口时压缩 |
| `threshold_ratio` | `0.8`（(0, 1]） |
| `retain_ratio` | `0.16`（[0, 1)）；自动压缩时保留原文的尾部占窗口的比例 |
| `default_context_window` | `128000`（> 0）；模型未声明上下文窗口时的窗口 |
| `summary_model` | `None`；摘要调用的 `route:model`，`None` 为会话模型 |
| `tool_result_chars` | `4000`（> 0）；转写中工具结果与调用参数的最长字符数 |
| start | `ctx.agentLoop.add_middleware(CompactionMiddleware(self))` |
| stop | 无 |

| 触发 | 时机 | 保留原文 | 失败 |
|---|---|---|---|
| auto | 模型调用前，`measure` ≥ `threshold_ratio` × 窗口 | 尾部 `retain_ratio` × 窗口 | 记录告警，本轮继续 |
| manual | 最后一条 user 消息为 `/compact` 命令（`POST /sessions/{id}/compact` 的 `compact` 运行） | 无：整段历史被摘要 | 运行失败 |

| 项 | 值 |
|---|---|
| 窗口 | `ctx.llm.context_window(spec)`，否则 `default_context_window` |
| `spec` | `configurable["model_spec"]`，否则 `ctx.llm.default` |

## 数据

| 项 | 内容 |
|---|---|
| 检查点消息 | `HumanMessage`，内容 `PREAMBLE\n\n<compacted-summary>\n<摘要>\n</compacted-summary>`，`id` 为新 uuid |
| 检查点标记 | `additional_kwargs["pyharness"]`：`kind`、`id`、`trigger`（`auto` / `manual`）、`at`、`removed`、`before_tokens`、`model`、`after_tokens` |
| 命令标记 | user 消息的 `additional_kwargs["pyharness"]`：`{"kind": "command", "name": …}` |
| 状态更新 | `[RemoveMessage(REMOVE_ALL_MESSAGES), 检查点, *尾部]`；尾部消息缺 `id` 时补 uuid；手动压缩无可压缩内容时仅移除命令消息 |
| 摘要调用 | `SystemMessage(SUMMARY_SYSTEM)` + `HumanMessage("Conversation transcript:\n\n<转写>\n\n---\n\n" + INSTRUCTION)`；模型为 `summary_model` 或会话模型 |
| 可见副作用 | Web UI 以标记展示检查点；运行流携带 `compact` 事件；turn 记录含 `compact` 条目 |
