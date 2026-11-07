# pyharness-tools

`ctx.tools`：工具注册表（tool registry）、`tools/execute` → `tools/result` 执行管线、审批闸门（approval gate）。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `ToolCall`、`ToolRecord`、`ToolError`、`ToolsService`；`_strictest` 取最严格闸门 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `ToolCall` | 类 | dataclass：`name`、`args`、`id`、`session_id`、`request`（LangChain `ToolCallRequest`）、`owner`（注册条目；loop 内置工具为 `None`）、`meta` |
| `ToolError` | 类 | 重复注册同名工具 |
| `ToolRecord` | 类 | dataclass：`tool`、`owner`、`approval`、`tags`；`describe()` → `name`、`owner`、`description` 首行、`approval`、`tags` |
| `ToolsService` | 类 | `Service`，key `tools` |

## 服务

| 项 | 值 |
|---|---|
| key | `tools` |
| name | `pyharness-tools` |
| inject | 无 |
| Config | 无 |
| `start()` | 声明 `tools/execute`（waterfall）与 `tools/result`（parallel） |
| `stop()` | 无 |
| `register(tool, *, approval=False, tags=())` | 可调用对象经 `langchain_core.tools.tool` 包装；同名 → `ToolError`；归属 `caller`，返回 disposer |
| `require_approval(tool_name, config=True)` | 给非本插件工具加闸门；按所有者累加，disposer 只移除本所有者的闸门；`config` 为假时无操作 |
| `list()` | `BaseTool` 列表 |
| `records()` | `ToolRecord` 列表 |
| `owner_of(name)` | 注册条目 id 或 `None` |
| `interrupt_on()` | `tool name → gate`：每个工具一个最严格闸门 |
| `execute(call, handler)` | `call.owner` 缺省时补 `owner_of`；waterfall `tools/execute`，`final` 为 `handler(call.request)`；随后 parallel `tools/result`；返回结果 |

| `approval` | 效果 |
|---|---|
| `False` | 无闸门 |
| `True` | 每次调用等待人工决定 |
| `dict` | LangChain `InterruptOnConfig`：`allowed_decisions`、`description`、`when` |

| 最严格规则 | 顺序 |
|---|---|
| 1 | 无 `when` 的无条件闸门优先于有 `when` 的 |
| 2 | 候选中无 dict → `True` |
| 3 | 否则 `allowed_decisions` 最少的 dict（缺省视为 4 项：`approve`、`edit`、`reject`、`respond`） |

## 事件

| 事件 | 模式 | 监听者签名 | 时机 |
|---|---|---|---|
| `tools/execute` | waterfall | `(call: ToolCall, next) -> ToolMessage \| Command`；`await next()` 运行工具；不调 `next` 返回的 `ToolMessage` 替换调用 | 每次工具调用，含 agent loop 内置工具与子 agent |
| `tools/result` | parallel | `(call: ToolCall, result)` | 每次工具调用结束 |
