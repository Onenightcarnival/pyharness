# pyxis-harness-checkpoint-sqlite

SQLite 上的持久化提供者：`ctx.checkpointer` 与 `ctx.store`。

| 项 | 值 |
|---|---|
| 条目 | `checkpoint`（`base` bundle） |
| 插件 | `apply`（函数插件） |
| 注入 | 无 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `plugin.py` | `Config`、`apply` |

## 服务

| 服务 | 实现 | 文件 |
|---|---|---|
| `ctx.checkpointer` | `AsyncSqliteSaver` | `config.path` |
| `ctx.store` | `AsyncSqliteStore` | `config.store_path` |

## PostgreSQL 提供者

条目 id 相同：

```yaml
- id: checkpoint
  name: pyxis-harness-checkpoint-postgres
  config: {dsn: "${env:PYH_POSTGRES_DSN}"}
```
