# pyxis-harness

入口发行包：`pip install pyxis-harness` 装上内核、全部插件，以及挂载它们的 `base` bundle。

| 项 | 值 |
|---|---|
| 发行包 | `pyxis-harness` |
| 模块 | `pyxis_harness_bundle_base` |
| bundle | `base` |
| entry point | `pyxis_harness.bundles`：`base = pyxis_harness_bundle_base:BUNDLE` |
| PyPI 页面 | 本文件 |

## 使用

| 步骤 | 命令 |
|---|---|
| 安装 | `pip install pyxis-harness` 或 `uv tool install pyxis-harness`；Python 3.12 及以上 |
| 创建 profile | `pyh init` |
| 启动 | `pyh run`；浏览器打开 <http://127.0.0.1:8765> |
| 文档 | <https://github.com/Onenightcarnival/pyharness> |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `bundle.py` | `BUNDLE`：`bundle.yaml` 的路径 |
| `bundle.yaml` | bundle 的 patch |

## 依赖

`pyxis-harness-core` 与 workspace 的每个插件包；与其余发行包同一个版本号，以 `==` 锁定。

## `base` bundle

harness 自带的插件组合：`web` 与 `creator` profile 模板都列入它。

| 规则 | 内容 |
|---|---|
| 加载 | 条目全部加载 |
| 停用 | Web UI 与 `/plugins` 接口不提供；`plugin_manager`、profile patch 可写 `disabled` |
| agent 的工具 | 各插件自己的开关：`memory`、`rdb`、`s3`、`http-client`、`web-tools` |
| 对外行为 | 各插件自己的设置：`gateway` 的监听、`otel` 的上报 |

## 条目

按 `bundle.yaml` 的顺序：

| 条目 | 包 | 内容 |
|---|---|---|
| `llm` | `pyxis-harness-llm` | 模型提供方 |
| `tools` | `pyxis-harness-tools` | 工具注册表 |
| `prompt` | `pyxis-harness-prompt` | 系统提示词分区 |
| `mcp` | `pyxis-harness-mcp` | MCP 服务器的工具 |
| `web-tools` | `pyxis-harness-web-tools` | `web_search`、`web_fetch` |
| `ask-user` | `pyxis-harness-ask-user` | 向用户提问 |
| `checkpoint` | `pyxis-harness-checkpoint-sqlite` | 持久化 |
| `checkpoint-temporary` | `pyxis-harness-checkpoint-memory` | 临时对话的内存持久化 |
| `workspace` | `pyxis-harness-workspace` | 工作区文件 |
| `agent-loop` | `pyxis-harness-agent-loop-deepagents` | agent loop |
| `agents` | `pyxis-harness-agent` | 会话与运行 |
| `auto-review` | `pyxis-harness-auto-review` | 自动审查权限模式 |
| `compaction` | `pyxis-harness-compaction` | 上下文压缩 |
| `workspace-changes` | `pyxis-harness-workspace-changes` | 每轮的文件变更 |
| `inspect` | `pyxis-harness-inspect` | `harness_inspect` |
| `plugin-manager` | `pyxis-harness-plugin-manager` | `plugin_manager`、插件编写 skills |
| `dev-context` | `pyxis-harness-dev-context` | 提示词分区：harness 的位置 |
| `http` | `pyxis-harness-http` | HTTP 服务 |
| `api` | `pyxis-harness-api` | REST 与 SSE；`required` |
| `web-ui` | `pyxis-harness-web-ui` | Web UI；`required` |
| `memory` | `pyxis-harness-memory` | 记忆 |
| `rdb` | `pyxis-harness-rdb` | 关系数据库 |
| `s3` | `pyxis-harness-s3` | S3 |
| `config-center` | `pyxis-harness-config-center` | 技能、MCP 页 |
| `otel` | `pyxis-harness-otel` | OpenTelemetry 导出 |
| `subscriptions` | `pyxis-harness-subscriptions` | 订阅 |
| `gateway` | `pyxis-harness-gateway` | API 网关 |
| `http-client` | `pyxis-harness-http-client` | HTTP 客户端 |
| `terminal` | `pyxis-harness-terminal` | shell 工具、后台任务、终端 |

`pyxis-harness-checkpoint-postgres` 随包安装，不在条目中：`checkpoint` 条目的 `name` 改为它即换用 PostgreSQL。

## 条目配置

| 条目 | 配置 | 效果 |
|---|---|---|
| `agent-loop` | `default_mode: auto-review` | 新会话的权限模式：自动审查 |
