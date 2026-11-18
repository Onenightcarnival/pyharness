# pyxis-harness-bundle-toolkit

`toolkit` bundle：内置的 toolkit 模块。

| 项 | 值 |
|---|---|
| bundle | `toolkit` |
| entry point | `pyharness.bundles`：`toolkit = pyharness_bundle_toolkit:BUNDLE` |
| `builtin: true` | 属于每个 profile；不可关闭 |
| Web UI | 左侧栏入口可取消固定，收进「更多」菜单 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `bundle.py` | `BUNDLE`：`bundle.yaml` 的路径 |
| `bundle.yaml` | bundle 的 patch |

## 条目

| 条目 | 包 | 模块 |
|---|---|---|
| `memory` | `pyxis-harness-memory` | 记忆 |
| `rdb` | `pyxis-harness-rdb` | 关系数据库 |
| `s3` | `pyxis-harness-s3` | S3 |
| `config-center` | `pyxis-harness-config-center` | 技能、MCP 页 |
| `otel` | `pyxis-harness-otel` | OpenTelemetry 导出 |
| `subscriptions` | `pyxis-harness-subscriptions` | 订阅 |
| `gateway` | `pyxis-harness-gateway` | API 网关 |
| `http-client` | `pyxis-harness-http-client` | HTTP 客户端 |
