# pyharness-bundle-toolkit

`toolkit` bundle：内置工具箱模块（记忆、关系数据库、S3、配置中心、OpenTelemetry、AI 订阅）；`builtin: true`，每个 profile 必含、不可关闭、不可卸载。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `BUNDLE`：`bundle.yaml` 的路径；entry point `pyharness.bundles` 下的 `toolkit` |
| `bundle.yaml` | `title: Toolkit`、`description`、`builtin: true`、六个 `after` 定位的插入条目 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `BUNDLE` | 常量 | `Path`，指向包内 `bundle.yaml` |

## 服务

| 项 | 值 |
|---|---|
| bundle 名 | `toolkit` |
| `optional` | 否 |
| `builtin` | 是：排在清单 `bundles` 之后、可选 bundle 之前；`Profile.set_bundle_enabled(..., False)` → `ConfigError`；插件页与 API 返回 409 |
| 隐藏方式 | 左侧栏入口在设置 → 通用里隐藏 |
| 包依赖 | 仅 `pyharness-core`；各模块包由环境安装 |

| 序 | 条目 id | `name` | 位置 | `config` |
|---|---|---|---|---|
| 1 | `memory` | `pyharness-memory` | `after: web-ui` | — |
| 2 | `rdb` | `pyharness-rdb` | `after: memory` | — |
| 3 | `s3` | `pyharness-s3` | `after: rdb` | — |
| 4 | `config-center` | `pyharness-config-center` | `after: s3` | — |
| 5 | `otel` | `pyharness-otel` | `after: config-center` | — |
| 6 | `subscriptions` | `pyharness-subscriptions` | `after: otel` | — |

| 条目 | 提供 |
|---|---|
| `memory` | `ctx.memory`、`memory_get` / `memory_save`、「记忆」页 |
| `rdb` | `ctx.rdb`、`db_*` 工具、「数据库」页 |
| `s3` | `ctx.s3`、`s3_*` 工具、「S3」页 |
| `config-center` | `ctx.configCenter`、「MCP」页、「技能」页、受管 bun |
| `otel` | `ctx.otel`、设置 →「可观测」 |
| `subscriptions` | `ctx.subscriptions`、订阅模型路由与工具、「AI 订阅」页 |

## 数据

| 路径 | 所有者 |
|---|---|
| `<profile data>/toolkit/` | 各模块的数据根（`memory.sqlite`、`rdb.json`、`s3.json`、`skills/`、`bun/`、`subscriptions/`） |
