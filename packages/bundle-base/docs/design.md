# pyharness-bundle-base

`base` bundle：`web` profile 模板的插件集合——内核服务、deepagents loop、SQLite 持久化、工作区文件、HTTP API 与 Web UI。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `BUNDLE`：`bundle.yaml` 的路径；entry point `pyharness.bundles` 下的 `base` |
| `bundle.yaml` | `title: Base`、`description`、`patch` 条目列表 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `BUNDLE` | 常量 | `Path`，指向包内 `bundle.yaml` |

## 服务

| 项 | 值 |
|---|---|
| bundle 名 | `base` |
| `optional` | 否 |
| `builtin` | 否；只读的内置 bundle，插件页不可开关 |
| 所在模板 | `web`（默认）、`creator` |

| 序 | 条目 id | `name` | `config` |
|---|---|---|---|
| 1 | `llm` | `pyharness-llm` | `default: ${env:PYH_MODEL:-echo:echo}` |
| 2 | `tools` | `pyharness-tools` | — |
| 3 | `prompt` | `pyharness-prompt` | — |
| 4 | `mcp` | `pyharness-mcp` | —（服务器来自设置 → MCP 或 profile patch） |
| 5 | `ask-user` | `pyharness-ask-user` | — |
| 6 | `checkpoint` | `pyharness-checkpoint-sqlite` | `path: ${data_dir}/checkpoints.sqlite`、`store_path: ${data_dir}/store.sqlite` |
| 7 | `workspace` | `pyharness-workspace` | `root: ${env:PYH_WORKSPACE:-${cwd}}`、`shell: false` |
| 8 | `agent-loop` | `pyharness-agent-loop-deepagents` | — |
| 9 | `agents` | `pyharness-agent` | — |
| 10 | `compaction` | `pyharness-compaction` | — |
| 11 | `workspace-changes` | `pyharness-workspace-changes` | — |
| 12 | `inspect` | `pyharness-inspect` | — |
| 13 | `plugin-manager` | `pyharness-plugin-manager` | — |
| 14 | `dev-context` | `pyharness-dev-context` | — |
| 15 | `http` | `pyharness-http` | `host: ${env:PYH_HOST:-127.0.0.1}`、`port: ${env:PYH_PORT:-8765}` |
| 16 | `api` | `pyharness-api` | — |
| 17 | `web-ui` | `pyharness-web-ui` | — |
| 18 | `terminal` | `pyharness-terminal` | — |

| 替换示例 | patch |
|---|---|
| Postgres 持久化 | `id: checkpoint`、`name: pyharness-checkpoint-postgres`、`config: {dsn: ${env:PYH_POSTGRES_DSN}}`（`examples/patches/postgres.yaml`） |
| `execute` shell 工具 | `id: workspace`、`config: {shell: true}`、`merge: true`（`examples/patches/shell.yaml`） |
