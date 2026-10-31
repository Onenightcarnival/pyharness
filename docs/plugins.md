# 插件

## 内核插件

| 包 | 条目 id | 服务 | 职责 |
|---|---|---|---|
| `pyharness-core` | — | `loader`、`lifecycle`、`profile`、`events` | 内核：容器、事件、组合、Loader、worker、supervisor、预检、CLI |
| `pyharness-llm` | `llm` | `llm` | 模型提供方注册表；`resolve("provider:model")`；内置 `echo` |
| `pyharness-tools` | `tools` | `tools` | 工具注册表、执行管线、审批闸门 |
| `pyharness-prompt` | `prompt` | `prompt` | 有序的系统提示词片段 |
| `pyharness-checkpoint-sqlite` | `checkpoint` | `checkpointer`、`store` | SQLite 持久化 |
| `pyharness-checkpoint-postgres` | `checkpoint` | `checkpointer`、`store` | Postgres 持久化；共享连接池 |
| `pyharness-workspace` | `workspace` | `workspace`、`backend` | 工作区注册表：默认工作区、每会话工作区、最近列表、目录浏览；deepagents `FilesystemBackend` / `LocalShellBackend` |
| `pyharness-agent-loop-deepagents` | `agent-loop` | `agentLoop` | deepagents 图，按工作区 × 权限模式 × 预设构建；`add_subagent`、`add_middleware`、`add_skills`、`add_preset` |
| `pyharness-agent` | `agents` | `agents` | 会话、后台运行、审批、重启续跑；每轮记录（stats + 轨迹）写入 store，`turns(session_id)` |
| `pyharness-workspace-changes` | `workspace-changes` | `workspaceChanges` | 每轮改动的文件：轮次起止各做一次 git 工作树快照（私有对象目录，不碰仓库），摘要写入 `done` 事件与 store；逐文件 diff |
| `pyharness-http` | `http` | `http` | FastAPI 根应用 + uvicorn；`include_router`、`mount` |
| `pyharness-api` | `api` | — | `/api`：REST + SSE |
| `pyharness-web-ui` | `web-ui` | `webui` | `/`：Web 界面；`register_client(path, calls=)` 登记插件的浏览器模块，`/plugins/{entry}/client.js` 与 `/plugins/{entry}/call/{method}` |
| `pyharness-inspect` | `inspect` | — | `harness_inspect` 工具 |
| `pyharness-plugin-manager` | `plugin-manager` | — | `plugin_manager` 工具；插件编写 skills（`skills: true`）；三行提示词片段（`guidance`） |
| `pyharness-plugin-manager` | `dev-context` | — | `pyharness-dev-context`：harness 位置提示词段 |
| `pyharness-bundle-base` | — | — | `base` bundle：以上条目的组合 |
| `pyharness-bundle-creator` | — | — | `creator` bundle：`plugin-manager` 的 `skills: true`、`guidance: false` |

条目 id 与配置：`packages/bundle-base/src/pyharness_bundle_base/bundle.yaml`。

## 事件

| 事件 | 模式 | 声明方 | 时机 |
|---|---|---|---|
| `app/ready` | series | 内核 | 全部插件已 apply；组装，不绑定外部资源；预检运行它；出错 → 启动失败 |
| `app/serve` | series | 内核 | 绑定端口、接收外部输入；出错 → 启动失败 |
| `app/started` | parallel | 内核 | 本代已提交：last-known-good 已保存，交接文件已消费；后台工作 |
| `app/stopping` | parallel | 内核 | 卸载之前：取消运行中的轮次，停止 HTTP |
| `tools/execute` | waterfall | tools | 每次工具调用，含 agent loop 内置工具与子 agent；可短路 |
| `tools/result` | parallel | tools | 每次工具调用结束 |
| `agent/model-request` | waterfall | agent-loop | 每次模型调用 |
| `agent-loop/build` | waterfall | agent-loop | `create_deep_agent(**kwargs)` 之前；参数为 kwargs |
| `agent/turn-start`、`agent/turn-end` | parallel | agents | 每轮开始、结束；`turn.outcome` 在结束时设置 |

运行时清单与监听者：`harness_inspect topic=events`。

## 工具

| 成员 | 契约 |
|---|---|
| `ctx.tools.register(tool, approval=...)` | 工具归属调用方插件，插件停止时移除 |
| `ctx.tools.require_approval(name, ...)` | 给非本插件的工具加审批闸门 |
| `ctx.tools.interrupt_on()` | agent loop 的人工审批配置 |
| `ctx.tools.execute(...)` | 每次工具调用的管线入口 |

| `approval` | 效果 |
|---|---|
| `False` | 无闸门 |
| `True` | 每次调用审批 |
| `{"allowed_decisions": [...], "description": ..., "when": fn}` | `when(request)` 为真时审批 |

多个闸门作用于同一工具时：最严格者生效；一个插件撤不掉另一个插件的闸门。

## 扩展方式

| 目标 | 做法 |
|---|---|
| 新工具 | `ctx.tools.register` |
| 包住工具调用 | `tools/execute` 监听者 |
| 观察工具结果 | `tools/result` 监听者 |
| 包住模型调用 | `agent/model-request` 监听者 |
| 改 agent 构建参数 | `agent-loop/build` 监听者 |
| 子 agent、中间件 | `ctx.agentLoop.add_subagent`、`add_middleware` |
| 系统提示词片段 | `ctx.prompt.add(id, content, order)` |
| 模型提供方 | `ctx.llm.register(provider, factory)` |
| HTTP 路由、子应用 | `ctx.http.include_router`、`ctx.http.mount` |
| 替换服务 | patch：同一条目 id，换 `name` |

### 持久化：Postgres

`examples/patches/postgres.yaml`：

```yaml
- id: checkpoint
  name: pyharness-checkpoint-postgres
  config:
    dsn: ${env:PYH_POSTGRES_DSN}
```

| 要求 | 值 |
|---|---|
| 数据库编码 | UTF8；`SQL_ASCII` → 插件 `FAILED` |
| 连接池 | `pool_min` 1，`pool_max` 10 |

```bash
PYH_POSTGRES_DSN=postgresql://user:pass@127.0.0.1:5432/pyh uv run pyh run --patch examples/patches/postgres.yaml
```

### shell：`execute` 工具

`examples/patches/shell.yaml`：

```yaml
- id: workspace
  config: {shell: true}
  merge: true
```

每次 `execute` 调用需审批；`shell_approval: false` 取消审批。

### agent loop

`ctx.agents` 的要求：`ctx.agentLoop.build()` 返回带 `astream`、`aget_state` 的 LangGraph 图。

```python
class MyLoop(Service):
    key = "agentLoop"

    async def build(self):
        return create_agent(...)
```

```yaml
- id: agent-loop
  name: my-agent-loop
```

## 第三方 bundle

| 部分 | 内容 |
|---|---|
| `pyproject.toml` | entry point `pyharness.plugins`（代码）、`pyharness.bundles`（bundle 文件） |
| `bundle.yaml` | `title`、`description`、`patch`；`after` / `before` / `parent` 决定条目在配置树中的位置 |

```yaml
title: Audit log
description: Tool-call JSONL log, tool denylist, GET /audit.
patch:
  - id: audit
    name: pyharness-audit
    after: tools
    config:
      path: ${data_dir}/audit.jsonl
      deny: []
```

示例：[`examples/pyharness-audit`](../examples/pyharness-audit)。

```bash
uv run pyh plugin install examples/pyharness-audit
```
