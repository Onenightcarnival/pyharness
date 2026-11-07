# pyharness-bundle-web

`web` bundle：`pyharness-web-tools` 的 `web_search`（DeepSeek 原生搜索）与 `web_fetch` 工具；`optional: true`，默认开启，插件页可关闭。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `BUNDLE`：`bundle.yaml` 的路径；entry point `pyharness.bundles` 下的 `web` |
| `bundle.yaml` | `title: Web`、`description`、`optional: true`、一个插入条目 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `BUNDLE` | 常量 | `Path`，指向包内 `bundle.yaml` |

## 服务

| 项 | 值 |
|---|---|
| bundle 名 | `web` |
| `optional` | 是：不必写进 `profile.yaml` 的 `bundles`，排在显式列表与 builtin 之后；`disabled` 列表关闭；插件页与 `PUT /api/plugins/bundles/web` 可开关，不可卸载 |
| `builtin` | 否 |
| 包依赖 | `pyharness-web-tools` |

| 序 | 条目 id | `name` | 位置 | `config` |
|---|---|---|---|---|
| 1 | `web-tools` | `pyharness-web-tools` | `after: mcp` | — |

| 条目 | 提供 |
|---|---|
| `web-tools` | `ctx.web`；工具 `web_search`、`web_fetch`；搜索密钥取 `DEEPSEEK_API_KEY` 凭据（设置 → 模型的 DeepSeek 路由）或环境变量，缺失时工具返回说明 |
