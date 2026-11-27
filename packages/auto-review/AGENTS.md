# pyxis-harness-auto-review

权限模式「自动审查」：带审批门的工具调用先由模型审查，放行的直接执行，其余的交给用户审批。

| 项 | 值 |
|---|---|
| 条目 | `auto-review`（`base` bundle） |
| 注入 | `agentLoop`、`llm` |
| 权限模式 | `auto-review`；基于 `workspace-write` |
| 来源 | dsh 的 `dsh-experimental-auto-review` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `plugin.py` | `apply`、`Config`、`MODE`：向 agent loop 贡献权限模式 |
| `middleware.py` | `ReviewMiddleware`、`reviewed`、`review_of`、`note` |
| `review.py` | `Review`、`parse`、`history`、`prompt`、`tool_schema` |
| `config.toml` | `MODE`、`NOTES`、`HISTORY` |
| `prompts.toml` | 审查者的 system prompt |

## 配置

| 键 | 默认 | 内容 |
|---|---|---|
| `model` | `None` | 审查用的模型；`None`：被审调用所在请求的模型 |
| `timeout` | `60.0` | 一次审查的时限（秒） |

`ctx.autoReview`：生效中的配置对象；settings API 就地修改 `model`，下一次审查起生效。

## 流程

| 步骤 | 契约 |
|---|---|
| 模型回复 | `ReviewMiddleware.awrap_model_call`：逐个审查回复里带审批门的工具调用 |
| 审查范围 | 工具有审批门，且审批门自己的 `when` 为真；其余调用不审 |
| 审查请求 | 每个调用一次模型请求，顺序执行，标记 `nostream` |
| 记录 | AI 消息的 `additional_kwargs["pyharness"] = {"kind": "auto-review", "reviews": {调用 id: 记录}}` |
| 运行事件 | `tool_review`：`id`、`name` 与记录的字段 |
| 审批门 | `reviewed`：记录为 `allow` 时不中断；其余照常中断 |
| 审批卡片 | 描述以审查结论开头（`NOTES`），其后是审批门自己的描述 |
| 恢复运行 | 审批门重新求值时读同一条记录 |

## 记录

| 结果 | 字段 |
|---|---|
| 放行 | `decision: allow`、`risk` |
| 拒绝 | `decision: deny`、`risk`、`reason`？ |
| 失败 | `decision: deny`、`error`：超时、模型错误、回复不是合法结论 |

| `risk` | `decision` |
|---|---|
| `low` | `allow` |
| `medium` | `allow`、`deny` |
| `high` | `deny` |

## 审查输入

一个 JSON 对象：`environment`、`history`、`tool`、`pending`。

| 会话消息 | `history` 的条目 |
|---|---|
| 用户输入的消息 | `user-instruction`；去掉附件块 |
| 子 agent 的第一条消息 | `parent-instruction` |
| harness 写入的消息（压缩检查点、重启续跑） | `checkpoint` |
| AI 消息的工具调用 | `fact` |
| AI 消息的正文与推理、工具结果、system prompt | 无 |

| `HISTORY` | 内容 |
|---|---|
| `items` | 条目数上限；保留最近的 |
| `text_chars` | 一条文本的字符上限 |
| `args_chars` | 一次历史调用参数的字符上限 |

## 图

| 对象 | 处理 |
|---|---|
| 主 agent | 审批门换成 `reviewed`；加入 `ReviewMiddleware` |
| 声明式子 agent | 继承主 agent 的审批门；加入 `ReviewMiddleware(subagent=True)` |
| 自带 `interrupt_on`、已编译或远程的子 agent | 不变 |
| 没有审批门的图 | 不变 |

## 边界

| 项 | 契约 |
|---|---|
| 没有审查记录的调用 | 照常中断 |
| 新会话的默认模式 | 不提供；按会话选择 |
| 无人值守 | `pyh exec --mode auto-review --approvals reject`：未放行的调用被拒绝，运行继续 |
| 审批时限 | `agents` 的 `approval_timeout`：未放行的调用到期被拒绝 |
| 轮次统计 | 不含审查的模型请求 |
