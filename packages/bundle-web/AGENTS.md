# pyharness-bundle-web

`web` bundle：`web_search` 与 `web_fetch` 工具（`pyharness-web-tools`）。

| 项 | 值 |
|---|---|
| bundle | `web` |
| entry point | `pyharness.bundles`：`web = pyharness_bundle_web:BUNDLE` |
| `optional: true` | 默认开启；在插件页关闭 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `bundle.py` | `BUNDLE`：`bundle.yaml` 的路径 |
| `bundle.yaml` | bundle 的 patch |

## 条目

| 条目 | 包 |
|---|---|
| `web-tools` | `pyharness-web-tools` |
