# pyharness-ask-user

`ask_user_question` 工具：agent 向用户提问，运行以 LangGraph interrupt 暂停，用户回答后续跑。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `Option` / `Question` / `Answer` 模型、`Config`、`normalize_answers`、`AskUserService`、`DESCRIPTION` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `KIND` | 常量 | `"ask_user"`；interrupt 值的 `kind` |
| `Answer` | 模型 | `id`、`selected`（默认 `[]`）、`custom`（默认 `None`） |
| `AskUserService` | 类 | `Service`，key `askUser` |
| `Config` | 模型 | `approval` |
| `Option` | 模型 | `label`、`description` |
| `Question` | 模型 | `id`、`question`、`header`、`options`、`multi_select`（默认 `False`） |
| `normalize_answers` | 函数 | `normalize_answers(questions, raw)` → 按问题顺序每题一条；未知 `id` → `ValueError`；`raw` 为 dict 时取其 `answers` |

## 服务

| 项 | 值 |
|---|---|
| key | `askUser` |
| name | `pyharness-ask-user` |
| inject | `tools` |
| `Config.approval` | `False`；工具的审批闸门 |
| `start()` | 注册工具 `ask_user_question` |
| `stop()` | 无 |

## 工具

| 工具 | 审批 | 标签 | 参数 | 行为 |
|---|---|---|---|---|
| `ask_user_question` | `config.approval` | `ask-user` | `questions: list[Question]` | 空列表或 `id` 重复 → `ValueError`；`interrupt({"kind": "ask_user", "questions": [...]})`；恢复后返回 JSON `{"answers": [{"id", "selected", "custom"?}]}`；跳过的问题 `selected` 为空且无 `custom` |

| 续跑 | 路径 |
|---|---|
| 回答入口 | `POST /api/sessions/{id}/answers`（`pyharness-api`）→ `agents.start_run(resume={interrupt_id: {"answers": [...]}})` |
| 问答结构 | 与 dsh 的 `ask_user_question` 一致 |
