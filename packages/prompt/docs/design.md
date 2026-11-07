# pyharness-prompt

`ctx.prompt`：由有序片段（section）拼装的系统提示词（system prompt）。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `Section`、`PromptService` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `PromptService` | 类 | `Service`，key `prompt` |
| `Section` | 类 | dataclass：`id`、`content`（文本或零参可调用）、`order`、`owner`、`seq`、`presets`；`applies(preset)`、`render()` |

## 服务

| 项 | 值 |
|---|---|
| key | `prompt` |
| name | `pyharness-prompt` |
| inject | 无 |
| Config | 无 |
| `start()` / `stop()` | 无 |
| `add(id, content, order=100, presets=None)` | 片段归属 `caller`；重复 `id` → `ValueError`；返回 disposer |
| `sections()` | 按 `(order, seq)` 排序的 `id`、`order`、`owner`、`chars`、`presets` |
| `render(preset=None)` | 按 `(order, seq)` 排序，取 `applies(preset)` 的片段，`strip()` 后以空行连接，跳过空片段 |

| `presets` 规则 | 结果 |
|---|---|
| 片段 `presets` 为 `None` | 适用于全部预设 |
| `render(preset=None)` | 全部片段适用 |
| 两者都给出 | `preset in presets` 时适用 |

## 提示段

本包不添加片段；片段由其他插件经 `ctx.prompt.add` 登记（例：`plugin-authoring` order 50、`dev-context` order 60）。
