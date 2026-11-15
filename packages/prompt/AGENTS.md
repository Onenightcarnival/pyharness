# pyharness-prompt

系统提示词：由有序的 section 拼成。

| 项 | 值 |
|---|---|
| 条目 | `prompt`（`base` bundle） |
| 服务 | `PromptService`，`ctx.prompt` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `PromptService`、`Section` |

## 服务

| 成员 | 契约 |
|---|---|
| `add` | section 归调用方插件所有；插件停止时移除；`presets` 把它限定到这些 agent 预设 |
| `render` | section 按 `order` 排，其次按插入顺序；以空行分隔；`preset` 选出适用的 section |
| `sections` | 每个 section 的 `id`、`order`、`owner`、`chars`、`presets` |
