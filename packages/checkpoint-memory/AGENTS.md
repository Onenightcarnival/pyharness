# pyxis-harness-checkpoint-memory

进程内存中的持久化提供者，供临时会话使用：`ctx.temporary`。

| 项 | 值 |
|---|---|
| 条目 | `checkpoint-temporary`（`base` bundle） |
| 插件 | `apply`（函数插件） |
| 注入 | 无 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `plugin.py` | `Config`、`Temporary`、`apply` |

## 服务

| 服务 | 实现 |
|---|---|
| `ctx.temporary.checkpointer` | `InMemorySaver` |
| `ctx.temporary.store` | `InMemoryStore` |

## 契约

| 项 | 契约 |
|---|---|
| `ctx.temporary` | 一对 `checkpointer` 与 `store`，与 `ctx.checkpointer`、`ctx.store` 同形 |
| 使用者 | `ctx.agents`、`ctx.agentLoop`：临时会话的 thread 与记录 |
| 落盘 | 无 |
| 进程结束、重启换代 | 内容清空 |
| 多副本 | 不适用：各进程各有一份 |
| 替换 | 另一个提供者经 patch 替换本条目，提供同一个服务 |
