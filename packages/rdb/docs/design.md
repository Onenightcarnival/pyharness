# pyharness-rdb

关系数据库（relational database）工作台：SQLite / PostgreSQL / GaussDB / MySQL（MariaDB）的连接配置、`db_*` 工具与 Database 页面。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__.py` | 契约文档；从 `service` 导出公开名；`__all__` |
| `service.py` | `RdbService`、`Config`、提示段 `GUIDANCE`、连接池持有、空闲连接清扫任务、工具与提示段的注册同步 |
| `tools.py` | 5 个 `db_*` LangChain 工具；结果为模型可读文本 |
| `routes.py` | `/api/rdb` 下的 FastAPI 路由；CSV 导出 |
| `engine.py` | 门面（facade）：重导出 `sql`、`driver`、`sqlite`、`postgres`、`mysql`、`pool`、`query` 的公开名；测试以 `pyharness_rdb.engine` 引用 |
| `sql.py` | 语句文本：去注释与字面量的骨架、按顶层分号拆分、只读判定、命令名、SQL 字面量、JSON 安全值 |
| `driver.py` | 驱动契约：限额常量、`EngineError`、`QueryResult`、`SessionState`、主机列表解析、`Driver` 基类、共享游标执行 |
| `sqlite.py` | `SQLiteDriver`：标准库 `sqlite3`；进度回调实现语句超时 |
| `postgres.py` | `PgDriver`：psycopg 3；PostgreSQL 与 GaussDB 共用，`kind` 区分；`statement_timeout` |
| `mysql.py` | `MySQLDriver`：PyMySQL；`max_execution_time` / `max_statement_time` |
| `pool.py` | `connect()`：按主机顺序与 `targetSessionAttrs` 选节点；`Pool`：每配置一条活动连接，空闲关闭 |
| `query.py` | 引擎级操作：单条受控语句、表描述、分页行、网格编辑生成 SQL、CSV 与模型可读表格渲染 |
| `store.py` | `ProfileStore`：`rdb.json` 的读写、归一化、校验、名称去重；密码存凭据库 |
| `client.js` | 浏览器模块 `rdb`：侧栏「Database」入口与页面（连接、对象树、数据网格、结构、SQL 编辑器、CSV 导出、Agent 开关） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `RdbService` | `Service` 子类 | 服务键 `rdb`；entry point `pyharness-rdb = "pyharness_rdb:RdbService"` |
| `Config` | pydantic 模型 | 服务配置：`path`、`approval`、`idle_close_seconds` |
| `GUIDANCE` | `str` | 提示段文本，工具开启时注入系统提示 |

## 服务

| 项 | 值 |
|---|---|
| 服务键 | `rdb`，名称 `pyharness-rdb` |
| 注入 | `tools`、`prompt`、`http` |
| `Config.path` | 配置文件路径；默认 `<profile data>/toolkit/rdb.json`，无 profile 时 `~/.pyharness/data/toolkit/rdb.json` |
| `Config.approval` | `db_execute` 的审批门槛；默认 `False` |
| `Config.idle_close_seconds` | 连接空闲多久后关闭；默认 `600.0` |
| `start()` | 建 `ProfileStore`（凭据来自 `ctx.profile.credentials`，缺省为内存实现）；挂载路由；`sync()`；启动每 60 秒一次的清扫任务；向 `webui` 注册 `client.js` |
| `stop()` | 取消清扫任务；注销工具与提示段；关闭全部连接 |
| `sync()` | 依据 `settings.agentTools` 注册或注销全部工具与提示段；返回当前是否已注册 |
| 配置变更 | 文件每次写入后 `sync()`；PATCH / DELETE 配置后丢弃该配置的连接 |
| `driver(profile)` | 从 `Pool` 取连接；配置 `updatedAt` 变化或连接失活时重开 |
| `run(id_or_name, fn)` | 在工作线程中以该配置的驱动调用 `fn` |
| `test(pid)` | 连接测试：延迟、服务器版本、节点 |

## 事件 / 工具 / 路由 / 提示段

### 工具

工具只在 Agent 开关打开时存在。

| 工具 | 标签 | 审批 | 作用 |
|---|---|---|---|
| `db_connections` | `db` | 无 | 列出连接（名称、类型、目标、是否允许写） |
| `db_schema` | `db` | 无 | 列 schema 与表，或一张表的列、索引、DDL |
| `db_query` | `db` | 无 | 一条只读语句；默认 200 行，上限 500 |
| `db_explain` | `db` | 无 | 执行计划；SQLite 用 `EXPLAIN QUERY PLAN` |
| `db_execute` | `db`、`db-write` | `Config.approval` | 一个事务内执行写语句；需 `confirm=true` 且连接 `allowWrite` |

### 路由

前缀 `/api`，标签 `pyharness-rdb`；JSON 请求体默认上限 64 KiB。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/rdb/profiles` | 配置摘要列表（不含密码） |
| POST | `/rdb/profiles` | 新建配置；201 |
| PATCH | `/rdb/profiles?id=` | 更新配置并丢弃其连接 |
| DELETE | `/rdb/profiles?id=` | 删除配置、凭据与连接 |
| GET | `/rdb/settings` | `{agentTools}` |
| POST | `/rdb/settings` | 设置 `agentTools` 后 `sync()` |
| POST | `/rdb/test` | 连接测试 |
| GET | `/rdb/schemas?id=` | schema 列表与默认 schema |
| GET | `/rdb/tables?id=&schema=` | 表与视图 |
| GET | `/rdb/columns?id=&schema=&table=&kind=` | 列、索引、主键、估算行数 |
| GET | `/rdb/ddl?id=&schema=&table=&kind=` | DDL |
| POST | `/rdb/rows` | 分页行：offset、limit（默认 100，上限 1000）、排序、过滤；请求体上限 256 KiB |
| POST | `/rdb/query` | 一条语句（允许写）；`maxRows`、`timeoutMs`；请求体上限 1 MiB |
| POST | `/rdb/execute` | 事务内执行多条语句；请求体上限 1 MiB |
| POST | `/rdb/changes` | 网格编辑生成 SQL；`apply` 为真时执行；请求体上限 4 MiB |
| GET | `/rdb/export.csv?id=&sql=&name=` | 只读查询导出 CSV（带 BOM；上限 100000 行、120 秒） |

### 提示段

| id | order | 文本 |
|---|---|---|
| `plugin:rdb` | 153 | `GUIDANCE` |

### Web UI

| 槽位 | 值 |
|---|---|
| `sidebar.panellist` | id `rdb`，图标 `database`，order 40 |
| `main` | key `rdb`，Database 页面 |

## 数据

| 项 | 值 |
|---|---|
| 配置文件 | `<profile data>/toolkit/rdb.json`；权限 0600；临时文件替换写入；损坏时改名 `rdb.json.corrupt-<ms>` |
| 文件结构 | `{version: 1, settings: {agentTools: bool}, profiles: [...]}` |
| 配置记录 | `id`（12 位十六进制）、`name`（唯一，不区分大小写）、`kind`（`sqlite` / `postgres` / `gaussdb` / `mysql`）、`file`、`host`（逗号分隔多节点，不带端口）、`port`、`database`、`user`、`ssl`、`targetSessionAttrs`、`loadBalanceHosts`、`allowWrite`、`createdAt`、`updatedAt`（毫秒） |
| 默认端口 | `postgres` 5432、`gaussdb` 8000、`mysql` 3306、`sqlite` 0 |
| `targetSessionAttrs` | `any`、`read-write`、`read-only`、`primary`、`standby`、`prefer-standby` |
| 凭据引用 | `RDB_<ID 大写>`：密码，存于 profile 凭据库；`sqlite` 不写凭据 |
| 引擎限额 | 默认 1000 行、上限 100000 行；语句超时默认 30000 ms、上限 600000 ms；计数超时 10000 ms；连接超时 15 s |
| 查询结果 | `QueryResult`：`columns[{name,type}]`、`rows`、`rowCount`、`truncated`、`durationMs`、`command` |
| 表描述 | `TableInfo`：`table{schema,name,kind}`、`columns`、`indexes`、`primaryKey`、`estimatedRows` |
| 网格变更 | `{kind: update\|insert\|delete, key, values, nulls}` → `{statements, applied, affected?, error?}` |
