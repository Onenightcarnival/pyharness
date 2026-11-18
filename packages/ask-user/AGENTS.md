# pyxis-harness-ask-user

`ask_user_question` 工具：agent 向用户提问并等待回答。

| 项 | 值 |
|---|---|
| 条目 | `ask-user`（`base` bundle） |
| 服务 | `AskUserService`，`ctx.askUser` |
| 注入 | `tools` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `AskUserService`、`Config`、问题与回答的模型、`normalize_answers` |
| `prompts.toml` | 模型可见的文本 |

## 流程

| 步骤 | 契约 |
|---|---|
| 提问 | 工具发起 LangGraph interrupt，值为 `{"kind": "ask_user", "questions": [...]}` |
| 运行 | 以 `interrupted` 结束；Web UI 显示问题卡片 |
| 回答 | `POST /sessions/{id}/answers` 恢复运行：`agents.start_run(resume={interrupt_id: {"answers": [...]}})` |
| 工具返回 | JSON：`{"answers": [{"id", "selected", "custom"?}]}` |
| 跳过的问题 | `selected` 为空，无 `custom` |
| 问题与回答的形状 | 与 dsh 的 `ask_user_question` 相同 |

## `prompts.toml`

| 项 | 契约 |
|---|---|
| 表 | `[tools]`：工具描述，键为工具名 |
| 读取 | `pyharness.package_prompts`；每个字符串值去掉首尾空白 |
| 占位符 | `string.Template` 语法（`${name}`） |
