# pyharness-bundle-base

`base` bundle：`web` profile 模板的插件集合。

| 项 | 值 |
|---|---|
| bundle | `base` |
| entry point | `pyharness.bundles`：`base = pyharness_bundle_base:BUNDLE` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `bundle.py` | `BUNDLE`：`bundle.yaml` 的路径 |
| `bundle.yaml` | bundle 的 patch |

## 条目

| 条目 | 包 |
|---|---|
| `llm` | `pyharness-llm` |
| `tools` | `pyharness-tools` |
| `prompt` | `pyharness-prompt` |
| `mcp` | `pyharness-mcp` |
| `ask-user` | `pyharness-ask-user` |
| `checkpoint` | `pyharness-checkpoint-sqlite` |
| `workspace` | `pyharness-workspace` |
| `agent-loop` | `pyharness-agent-loop-deepagents` |
| `agents` | `pyharness-agent` |
| `auto-review` | `pyharness-auto-review` |
| `compaction` | `pyharness-compaction` |
| `workspace-changes` | `pyharness-workspace-changes` |
| `inspect` | `pyharness-inspect` |
| `plugin-manager` | `pyharness-plugin-manager` |
| `dev-context` | `pyharness-dev-context` |
| `http` | `pyharness-http` |
| `api` | `pyharness-api` |
| `web-ui` | `pyharness-web-ui` |
| `terminal` | `pyharness-terminal` |
