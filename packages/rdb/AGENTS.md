# pyxis-harness-rdb

关系数据库工作台：SQLite / PostgreSQL / GaussDB / MySQL（MariaDB）。

| 项 | 值 |
|---|---|
| 条目 | `rdb`（`toolkit` bundle） |
| 服务 | `RdbService`，`ctx.rdb` |
| 注入 | `tools`、`prompt`、`http` |
| 路由前缀 | `/api/rdb` |
| 数据 | `<profile data>/toolkit/rdb.json`；密码在 profile 凭据库 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `rdb` 服务：profile、连接池、`db_*` 工具注册、提示词段 |
| `store.py` | 连接 profile 与 agent 访问设置 |
| `tools.py` | `db_*` LangChain 工具 |
| `routes.py` | 数据库页的 FastAPI 路由 |
| `engine.py` | 数据库引擎门面：再导出 `sql`、`driver`、`sqlite`、`postgres`、`mysql`、`pool`、`query` |
| `driver.py` | 驱动契约：上限、结果形状、主机列表、`Driver` 基类、共用的 cursor 运行器 |
| `sqlite.py` | SQLite 驱动（标准库 `sqlite3`）；语句超时经 progress handler |
| `postgres.py` | PostgreSQL 与 GaussDB 驱动，经 psycopg 3 |
| `mysql.py` | MySQL 与 MariaDB 驱动，经 PyMySQL |
| `pool.py` | 连接的打开（主机顺序、`target_session_attrs`）与按 profile 的 `Pool` |
| `sql.py` | 语句文本：分类、切分、SQL 字面量、JSON 安全的值 |
| `query.py` | 驱动之上的引擎级操作：一条受保护的语句、表描述、分页行、表格编辑转 SQL、结果的 CSV 渲染与面向模型的渲染 |
| `config.toml` | 包数据；`pyxis_harness.package_toml(__file__)` 加载 |
| `prompts.toml` | 模型可见文本；`pyxis_harness.package_prompts(__file__)` 加载 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `store` | `ProfileStore`：连接 profile（密码在凭据库）、agent 访问设置 |
| `pool` | `Pool`：每个 profile 一个活动连接；空闲连接关闭 |
| `sync()` | agent 访问开启期间注册 `db_*` 工具与提示词段 |

| 配置 | 含义 |
|---|---|
| `path` | profile 文件；默认 `<profile data>/toolkit/rdb.json` |
| `approval` | `db_execute` 的审批门；默认无 |

## 工具

| 项 | 契约 |
|---|---|
| 工具 | `db_connections`、`db_schema`、`db_query`、`db_explain`、`db_execute` |
| 形状 | 同 dsh-rdb |
| 结果 | 给模型的文本 |
| `db_query` | 一条只读语句 |
| `db_execute` | 写入，在一个事务中；需要 `confirm=true`；只在标记为「允许 Agent 写入」的连接上 |

## 路由

| 项 | 内容 |
|---|---|
| 使用方 | 数据库页 |
| 路径 | `profiles`、`settings`、`test`、`schemas`、`tables`、`columns`、`ddl`、`rows`、`query`、`execute`、`changes`、`export.csv` |
| `rows` | 分页、过滤、排序 |
| `changes` | 表格编辑转成 SQL；先预览，后应用 |

## 存储（`store.py`）

| 项 | 位置 |
|---|---|
| 连接 profile、agent 访问设置 | `<profile data>/toolkit/rdb.json` |
| 密码 | profile 凭据库，引用 `RDB_<ID>` |

## 引擎

| 项 | 契约 |
|---|---|
| 驱动 | 同步的 DB-API 连接 |
| 执行 | 服务在工作线程中运行驱动 |
| 并发 | 每个连接同一时刻一条语句 |
| 门面（`engine.py`） | 驱动（SQLite、PostgreSQL / GaussDB、MySQL / MariaDB）、语句分类、分页、表格变更、CSV |

| `sql.py` | 契约 |
|---|---|
| 分类 | 只读与否 |
| 切分 | 按顶层分号 |
| `mysql` | 选用 MySQL 方言：反引号标识符、反斜杠转义、`#` 注释 |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「数据库」页 | 连接、对象树、数据表格（行内编辑以 SQL 应用）、结构、SQL 编辑器、CSV 导出、agent 访问开关 |
