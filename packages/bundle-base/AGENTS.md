# pyxis-harness-bundle-base

`base` bundle：`web` profile 模板的插件集合。

| 项 | 值 |
|---|---|
| bundle | `base` |
| entry point | `pyxis_harness.bundles`：`base = pyxis_harness_bundle_base:BUNDLE` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `bundle.py` | `BUNDLE`：`bundle.yaml` 的路径 |
| `bundle.yaml` | bundle 的 patch |

## 条目

| 条目 | 包 |
|---|---|
| `llm` | `pyxis-harness-llm` |
| `tools` | `pyxis-harness-tools` |
| `prompt` | `pyxis-harness-prompt` |
| `mcp` | `pyxis-harness-mcp` |
| `ask-user` | `pyxis-harness-ask-user` |
| `checkpoint` | `pyxis-harness-checkpoint-sqlite` |
| `workspace` | `pyxis-harness-workspace` |
| `agent-loop` | `pyxis-harness-agent-loop-deepagents` |
| `agents` | `pyxis-harness-agent` |
| `auto-review` | `pyxis-harness-auto-review` |
| `compaction` | `pyxis-harness-compaction` |
| `workspace-changes` | `pyxis-harness-workspace-changes` |
| `inspect` | `pyxis-harness-inspect` |
| `plugin-manager` | `pyxis-harness-plugin-manager` |
| `dev-context` | `pyxis-harness-dev-context` |
| `http` | `pyxis-harness-http` |
| `api` | `pyxis-harness-api` |
| `web-ui` | `pyxis-harness-web-ui` |
| `terminal` | `pyxis-harness-terminal` |

## 条目配置

| 条目 | 配置 | 效果 |
|---|---|---|
| `agent-loop` | `default_mode: auto-review` | 新会话的权限模式：自动审查 |
