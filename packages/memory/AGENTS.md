# pyharness-memory

agent 的分层职业记忆（profile → work → project → lesson），带版本历史。

| 项 | 值 |
|---|---|
| 条目 | `memory`（`toolkit` bundle） |
| 服务 | `MemoryService`，`ctx.memory` |
| 注入 | `tools`、`prompt`、`http` |
| 路由前缀 | `/api/memory` |
| 数据 | `<profile data>/toolkit/memory.sqlite` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `memory` 服务：存储、agent 的节点视图（`read`）与类型化变更批次（`save`）、工具注册、提示词段 |
| `store.py` | 职业记忆模型及其 SQLite 存储 |
| `tools.py` | `memory_get` / `memory_save` LangChain 工具、类型化变更的 schema |
| `routes.py` | 记忆页的 FastAPI 路由 |
| `prompts.toml` | 模型可见文本；`pyharness.package_prompts(__file__)` 加载 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `store` | `MemoryStore`：`state()`、`commit()`、`clear()`、`diff()` |
| `sync()` | agent 访问开启期间注册工具与提示词段 |

| 配置 | 含义 |
|---|---|
| `path` | SQLite 文件；默认 `<profile data>/toolkit/memory.sqlite` |
| `busy_timeout` | 等待被锁数据库的秒数 |

## 工具

| 项 | 契约 |
|---|---|
| 工具 | `memory_get`、`memory_save` |
| 形状与提示词 | 同 dsh-memory |
| 存在条件 | 记忆页的「允许 Agent 使用」开关开启 |
| 模型调用 | 无 |
| 写入方 | agent，在自己的回合中；用户，在记忆页上 |

## 路由

| 路径 | 方法 | 作用 |
|---|---|---|
| `/api/memory` | GET | 状态 |
| `/api/memory?diff=N` | GET | 差异 |
| `/api/memory` | POST | 提交 |
| `/api/memory` | PATCH | agent 访问 |
| `/api/memory` | DELETE | 清空 |

## 存储模型（`store.py`）

| 层 | 上级 |
|---|---|
| `profile` | 无；唯一的根 |
| `work` | `profile` |
| `project` | `fields.workId` 指向的 `work`；空 → 独立项目，挂在根下 |
| `lesson` | `fields.parentId` 指向的 `project` |

| 项 | 契约 |
|---|---|
| 写入 | 每次写入是一次提交 |
| 修订 | 内容有变化时新增一条：时间、actor、source、summary，附全部条目的完整快照 |
| blob | 按内容寻址；未变的条目只存一份 |
| `revision` | 单调的并发计数器（`stateToken`） |
| 显示的版本 | 修订的条数 |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「记忆」页 | 简历视图、目录视图、带差异的版本历史、编辑器、导入 / 导出、清空、agent 访问开关 |
