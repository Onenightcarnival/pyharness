# pyharness-checkpoint-sqlite

SQLite 持久化提供方：`ctx.checkpointer` 与 `ctx.store`。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 函数插件（`apply`）、`Config` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | `path`、`store_path` |
| `apply` | 函数 | `async apply(ctx, config)`：建目录、打开两个连接、`setup()`、提供服务 |
| `name` | 常量 | `"pyharness-checkpoint-sqlite"` |

## 服务

| 项 | 值 |
|---|---|
| 形式 | 函数插件 |
| `name` | `pyharness-checkpoint-sqlite` |
| `inject` | 无 |
| `Config.path` | `"${data_dir}/checkpoints.sqlite"`；LangGraph 检查点 |
| `Config.store_path` | `"${data_dir}/store.sqlite"`；LangGraph store：会话元数据、agent 记忆 |
| `apply` | `AsyncSqliteSaver.from_conn_string(path)` 与 `AsyncSqliteStore.from_conn_string(store_path)` 经 `ctx.enter` 打开（插件停止时关闭）；各自 `setup()`；`ctx.provide("checkpointer", saver)`、`ctx.provide("store", store)` |

| 提供的服务 | 实现 |
|---|---|
| `checkpointer` | `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` |
| `store` | `langgraph.store.sqlite.aio.AsyncSqliteStore` |

替换为 PostgreSQL：同一条目 id `checkpoint`，`name: pyharness-checkpoint-postgres`，`config: {dsn: "${env:PYH_POSTGRES_DSN}"}`。

## 数据

| 文件 | 内容 |
|---|---|
| `<data_dir>/checkpoints.sqlite` | LangGraph 检查点（`AsyncSqliteSaver.setup()` 建表） |
| `<data_dir>/store.sqlite` | LangGraph store（`AsyncSqliteStore.setup()` 建表）；命名空间 `("pyharness", "sessions")` 等由使用方定义 |
