# pyharness-checkpoint-postgres

PostgreSQL 上的持久化提供者：`ctx.checkpointer` 与 `ctx.store`。

| 项 | 值 |
|---|---|
| 条目 | `checkpoint`（patch：`examples/patches/postgres.yaml`） |
| 插件 | `apply`（函数插件） |
| 注入 | 无 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | `Config`、`apply` |

## 服务

| 服务 | 实现 |
|---|---|
| `ctx.checkpointer` | `AsyncPostgresSaver` |
| `ctx.store` | `AsyncPostgresStore` |

## 连接

| 项 | 契约 |
|---|---|
| 连接池 | 一个异步连接池；autocommit、dict 行、`prepare_threshold=0` |
| 数据库编码 | UTF8；`SQL_ASCII` → 插件失败 |
