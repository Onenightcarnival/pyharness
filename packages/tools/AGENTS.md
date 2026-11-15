# pyharness-tools

工具注册表与执行管线。

| 项 | 值 |
|---|---|
| 条目 | `tools`（`base` bundle） |
| 服务 | `ToolsService`，`ctx.tools` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | `ToolsService`、`ToolCall`、`ToolRecord`、`ToolError` |

## 服务

| 成员 | 契约 |
|---|---|
| `ToolsService.register` | 工具归调用方插件所有；插件停止时移除 |
| `ToolsService.require_approval` | 给不属于该插件的工具加审批门 |
| `ToolsService.interrupt_on` | 供 agent loop 的人工审批配置 |
| `ToolsService.execute` | 每次工具调用的管线，含 loop 内置工具 |

## 管线

| 事件 | 模式 | 监听者 |
|---|---|---|
| `tools/execute` | waterfall | `(call, next)` |
| `tools/result` | parallel | `(call, result)`；每次调用之后 |

`tools/execute` 监听者：

| 写法 | 效果 |
|---|---|
| `await next()` | 运行工具，返回其结果 |
| 不调用 `next`，返回 `ToolMessage` | 取代这次调用 |
