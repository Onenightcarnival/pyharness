# pyharness-compaction

上下文压缩：一条检查点摘要替换较早的历史。

| 项 | 值 |
|---|---|
| 条目 | `compaction`（`base` bundle） |
| 服务 | `CompactionService`，`ctx.compaction` |
| 注入 | `agentLoop`、`llm` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `CompactionService` 及其中间件：压力下的自动压缩、`/compact` 命令 |
| `checkpoint.py` | 检查点消息：标记、摘要提示词、上下文测量、切点选择、对话记录渲染 |
| `prompts.toml` | 模型可见的文本 |

## 触发

| 方式 | 时机 | 原样保留 |
|---|---|---|
| 自动 | 模型调用之前；测得的上下文达到 `threshold_ratio` × 窗口 | 尾部，量为 `retain_ratio` × 窗口 |
| 手动 | `/compact`：一次 `compact` 类型的运行（`POST /sessions/{id}/compact`） | 无；整段历史进入摘要 |

| 失败 | 结果 |
|---|---|
| 自动压缩 | 记入日志；该轮继续 |
| 手动压缩 | 运行失败 |

## 测量

| 情况 | 上下文 token 数 |
|---|---|
| 有 usage | 最近一次模型应答的 usage（输入 + 输出 token）+ 其后消息的估算 |
| 无 usage（最初几步、刚压缩之后） | 全部消息的估算 |

| 窗口 | 来源 |
|---|---|
| 首选 | 模型声明的 `context_window`（设置 → 模型） |
| 否则 | `default_context_window` |

## 检查点

| 项 | 契约 |
|---|---|
| 切点 | 不拆开一次工具调用与它的结果 |
| 摘要模型 | 会话的模型；`summary_model` 覆盖 |
| 摘要提示词 | 结构化的检查点模板 |
| 替换消息 | 用户消息；`additional_kwargs["pyharness"]` 为 `{"kind": "compact-checkpoint", ...}` |
| Web UI | 显示为标记 |
| 运行流 | `compact` 事件 |
| 轮次记录 | `compact` 条目 |

## `prompts.toml`

| 项 | 契约 |
|---|---|
| 表 | 以使用它的模块命名：`[checkpoint]`、`[service]` |
| 读取 | `pyharness.package_prompts`；每个字符串值去掉首尾空白 |
| 占位符 | `string.Template` 语法（`${name}`） |
