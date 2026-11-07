# pyharness-checkpoint-postgres

PostgreSQL 持久化提供方：`ctx.checkpointer` 与 `ctx.store`，共享一个异步连接池。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 函数插件（`apply`）、`Config` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | `dsn`、`pool_min`、`pool_max` |
| `apply` | 函数 | `async apply(ctx, config)`：开池、校验编码、`setup()`、提供服务 |
| `name` | 常量 | `"pyharness-checkpoint-postgres"` |

## 服务

| 项 | 值 |
|---|---|
| 形式 | 函数插件 |
| `name` | `pyharness-checkpoint-postgres` |
| `inject` | 无 |
| `Config.dsn` | 必填；libpq 连接串 `postgresql://user:pass@host:5432/db` |
| `Config.pool_min` | `1` |
| `Config.pool_max` | `10` |
| `apply` | `AsyncConnectionPool(conninfo=dsn, min_size, max_size, open=False, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})`；`open(wait=True, timeout=15)`；`ctx.on_dispose(pool.close)`；`SHOW server_encoding` 为 `SQL_ASCII` → `RuntimeError`（插件 `FAILED`）；`AsyncPostgresSaver(pool).setup()`、`AsyncPostgresStore(pool).setup()`；提供 `checkpointer`、`store` |

| 提供的服务 | 实现 |
|---|---|
| `checkpointer` | `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` |
| `store` | `langgraph.store.postgres.aio.AsyncPostgresStore` |

| 要求 | 值 |
|---|---|
| 数据库编码 | UTF8 |
| 启用方式 | patch 条目 `checkpoint` 换 `name`（`examples/patches/postgres.yaml`） |

## 数据

| 项 | 内容 |
|---|---|
| 数据库表 | 由 `AsyncPostgresSaver.setup()` 与 `AsyncPostgresStore.setup()` 创建（LangGraph 迁移） |
| DSN | 配置经 `${env:PYH_POSTGRES_DSN}` 引用；`harness_inspect` 对 `dsn` 字段脱敏 |
