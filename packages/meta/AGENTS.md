# pyxis-harness

入口发行包：`pip install pyxis-harness` 装上内核与全部 bundle。

| 项 | 值 |
|---|---|
| 发行包 | `pyxis-harness` |
| 内容 | 只有依赖；不含模块，不含 entry point |
| wheel | `bypass-selection`：不选取任何文件 |
| PyPI 页面 | 本文件 |

## 使用

| 步骤 | 命令 |
|---|---|
| 安装 | `pip install pyxis-harness` 或 `uv tool install pyxis-harness`；Python 3.12 及以上 |
| 创建 profile | `pyh init` |
| 启动 | `pyh run`；浏览器打开 <http://127.0.0.1:8765> |
| 文档 | <https://github.com/Onenightcarnival/pyharness> |

## 依赖

| 包 | 带来 |
|---|---|
| `pyxis-harness-core` | 内核、`pyh` 命令 |
| `pyxis-harness-bundle-base` | `base` bundle 及其插件 |
| `pyxis-harness-bundle-toolkit` | `toolkit` bundle 及其插件 |
| `pyxis-harness-bundle-web` | `web` bundle 及其插件 |
| `pyxis-harness-bundle-creator` | `creator` bundle |

## 版本

与其余发行包同一个版本号；依赖以 `==` 锁定。
