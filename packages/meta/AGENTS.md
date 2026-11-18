# pyxis-harness

入口发行包：`pip install pyxis-harness` 装上内核与全部 bundle。

| 项 | 值 |
|---|---|
| 发行包 | `pyxis-harness` |
| 内容 | 只有依赖；不含模块，不含 entry point |
| wheel | `bypass-selection`：不选取任何文件 |

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
