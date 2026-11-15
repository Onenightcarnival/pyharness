# pyharness-bundle-creator

`creator` bundle：新会话默认使用 `creator` agent 预设（`creator` profile 模板）。

| 项 | 值 |
|---|---|
| bundle | `creator` |
| entry point | `pyharness.bundles`：`creator = pyharness_bundle_creator:BUNDLE` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | `BUNDLE`：`bundle.yaml` 的路径 |
| `bundle.yaml` | bundle 的 patch |

## 条目

| 条目 | 操作 | 配置 |
|---|---|---|
| `agent-loop` | `merge: true` | `default_preset: creator` |
