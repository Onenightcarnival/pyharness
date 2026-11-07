# pyharness-bundle-creator

`creator` bundle：新会话默认使用 `creator` 预设（插件编写 skills、plugin manager 与 inspect 工具）；`creator` profile 模板的第二个 bundle。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `BUNDLE`：`bundle.yaml` 的路径；entry point `pyharness.bundles` 下的 `creator` |
| `bundle.yaml` | `title: Creator`、`description`、一条 `merge` patch |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `BUNDLE` | 常量 | `Path`，指向包内 `bundle.yaml` |

## 服务

| 项 | 值 |
|---|---|
| bundle 名 | `creator` |
| `optional` | 否 |
| `builtin` | 否 |
| 所在模板 | `creator`（`pyh init --template creator`：`bundles: [base, creator]`） |
| 依赖 | `pyharness-plugin-manager` |

| 序 | 条目 id | 操作 | `config` |
|---|---|---|---|
| 1 | `agent-loop` | 已存在条目，`merge: true` | `default_preset: creator` |

| 效果 | 内容 |
|---|---|
| 预设 | `creator` 预设看到 `/skills/pyharness/`（`pyharness-plugin-manager` 的 `skills_presets` 默认 `["creator"]`） |
| 其他条目 | 不改；`plugin-manager` 的 `guidance` 仍默认 `true` |
