# pyharness-memory

Agent 的分层职业记忆（career memory）：profile → work → project → lesson 的树与版本历史，`memory_get` / `memory_save` 工具与 Memory 页面。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__.py` | 契约文档；从 `service` 与 `store` 导出公开名；`__all__` |
| `service.py` | `MemoryService`、`Config`、提示段 `GUIDANCE`、节点视图（标题、摘要、祖先链）、`read()` 与 `save()`、工具与提示段的注册同步 |
| `tools.py` | `memory_get` / `memory_save` LangChain 工具；按 kind 生成的变更模型 `ProfileChange` / `WorkChange` / `ProjectChange` / `LessonChange` / `RemoveChange` |
| `routes.py` | `/api/memory` 下的 FastAPI 路由 |
| `store.py` | 记忆模型与 SQLite 存储：kind 与字段定义、校验、排序、`MemoryStore`（状态、提交、清空、差异） |
| `client.js` | 浏览器模块 `memory`：侧栏「Memory」入口与页面（简历视图、目录视图、版本历史与差异、编辑器、导入导出、清空、Agent 开关） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `MemoryService` | `Service` 子类 | 服务键 `memory`；entry point `pyharness-memory = "pyharness_memory:MemoryService"` |
| `Config` | pydantic 模型 | 服务配置：`path`、`busy_timeout` |
| `GUIDANCE` | `str` | 提示段文本，工具开启时注入系统提示 |
| `MemoryStore` | 类 | SQLite 存储：`state()`、`commit()`、`clear()`、`diff()`、`set_agent_tools()` |
| `MemoryError` | 异常 | `code`、`detail`、`message`、`retryable` |
| `sort_entries` | 函数 | 按经历日期稳定排序；无日期的条目按插入顺序排在最后 |

## 服务

| 项 | 值 |
|---|---|
| 服务键 | `memory`，名称 `pyharness-memory` |
| 注入 | `tools`、`prompt`、`http` |
| `Config.path` | SQLite 文件路径；默认 `<profile data>/toolkit/memory.sqlite`，无 profile 时 `~/.pyharness/data/toolkit/memory.sqlite` |
| `Config.busy_timeout` | 等待数据库锁的秒数；默认 `5.0` |
| `start()` | 打开 `MemoryStore`；挂载路由；`sync()`；向 `webui` 注册 `client.js` |
| `stop()` | 注销工具与提示段；关闭存储 |
| `sync()` | 依据存储中的 `agentTools` 注册或注销两个工具与提示段；返回当前是否已注册 |
| `read(id, offset, limit)` | 一个节点、祖先链、子节点摘要分页（默认 10，上限 20）；错误以 `{ok: false, error}` 返回 |
| `save(stateToken, summary, changes, source)` | 校验 `stateToken`、解析 ref 与 `@ref`、以 actor `agent` 提交；错误以 `{ok: false, error}` 返回 |

## 事件 / 工具 / 路由 / 提示段

### 工具

无审批、无标签；工具只在 Agent 开关打开时存在。

| 工具 | 作用 |
|---|---|
| `memory_get` | 读一个节点：完整内容、祖先路径、子节点摘要分页；省略 `id` 从根 profile 开始 |
| `memory_save` | 原子应用 1–100 条类型化变更；需最近一次读取的 `stateToken`；来源记为 `session:<thread_id>/call:<tool_call_id>` |

### 路由

前缀 `/api`，标签 `pyharness-memory`；请求体上限 2 MiB；`conflict` / `protected` / `busy` 返回 409，其余错误 400。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/memory` | 完整状态 |
| GET | `/memory?diff=N` | 第 N 个修订前后的条目快照；不存在时 404 |
| POST | `/memory` | 以 actor `human`、source `ui` 提交（变更、恢复、导入） |
| PATCH | `/memory` | 设置 `agentTools` 后 `sync()` |
| DELETE | `/memory` | 清空全部条目与历史；需 `baseRevision` |

### 提示段

| id | order | 文本 |
|---|---|---|
| `plugin:memory` | 155 | `GUIDANCE`：记录种类说明 + 工具用法 + 记录规则 |

### Web UI

| 槽位 | 值 |
|---|---|
| `sidebar.panellist` | id `memory`，图标 `book`，order 55 |
| `main` | key `memory`，Memory 页面 |

## 数据

| 项 | 值 |
|---|---|
| 文件 | `<profile data>/toolkit/memory.sqlite`；`foreign_keys` 与 `secure_delete` 开启；schema 版本 1 |
| 表 `meta` | `key`、`value`：`schemaVersion`、`revision`、`agentTools`（`"1"` / `"0"`，初始 `"1"`） |
| 表 `blobs` | `hash`（SHA-256）、`body`：内容寻址的条目 JSON |
| 表 `entries` | `seq`、`id`、`hash`：当前快照 |
| 表 `revisions` | `revision`、`time`、`actor`、`source`、`summary` |
| 表 `revision_entries` | `revision`、`seq`、`id`、`hash`：每个修订的完整快照 |
| 条目 | `{id, kind, fields, createdAt}`；`id` 匹配 `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$`；根条目固定 `id = "profile"` |
| kind 与字段 | `profile`: name, position, specialties, abilities；`work`: organization, startDate, endDate, jobTitle, highlights；`project`: title, startDate, endDate, role, highlights, workId；`lesson`: parentId, lesson |
| 树 | `project.fields.workId` 指向 work（空为独立项目，挂在根下）；`lesson.fields.parentId` 指向 project |
| 限额 | 1000 条目；字段 12000 字符，`highlights` 50000；一次提交 100 条变更；`summary` 500；`source` 2000 |
| 状态 | `{schemaVersion, revision, entries, agentTools, history}`；`stateToken` 为 `r:<revision>`；显示版本为修订数 |
| 日期 | `YYYY-MM-DD`；`endDate` 可为 `present`；`endDate` 不早于 `startDate` |
| 错误码 | `date`、`dateRange`、`invalid`、`missing`、`conflict`、`protected`、`reference`、`content`、`disabled`、`busy`、`storage`；`conflict` 与 `busy` 可重试 |
