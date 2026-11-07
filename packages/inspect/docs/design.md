# pyharness-inspect

`harness_inspect` 工具：运行中 harness 的只读视图。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 函数插件（`apply`）、`Inspector`、`Config`、`_redact` 脱敏 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | `max_chars` |
| `Inspector` | 类 | 每个 topic 一个方法：`overview`、`services`、`events`、`plugins`、`config`、`tools`、`routes`、`prompt`、`ui`，签名 `(name: str \| None)` |
| `REDACTED` | 常量 | `"<from environment: redacted>"` |
| `Topic` | 类型别名 | `Literal["overview", "services", "events", "plugins", "config", "tools", "routes", "prompt", "ui"]` |
| `apply` | 函数 | `apply(ctx, config)`：注册工具 |
| `inject` | 常量 | `["tools"]` |
| `name` | 常量 | `"pyharness-inspect"` |

## 服务

| 项 | 值 |
|---|---|
| 形式 | 函数插件 |
| `name` | `pyharness-inspect` |
| `inject` | `tools` |
| `Config.max_chars` | `12000`；超出时截断并提示用 `name` 缩小范围 |
| `apply` | `ctx.tools.register(StructuredTool.from_function(harness_inspect, name="harness_inspect"))`，无审批 |

## 工具

| 工具 | 审批 | 参数 | 返回 |
|---|---|---|---|
| `harness_inspect` | 无 | `topic: Topic = "overview"`、`name: str \| None` | JSON 文本（`indent=1`） |

| topic | 内容 |
|---|---|
| `overview` | `generation`、`supervised`、`profile`、`entries` 计数、`services`、`events`（`name (mode)`）、`topics` |
| `services` | 可见服务 `key`、`owner`、`type`、`doc` 首行；带 `name`：`scope`、完整 `doc`、`methods`（签名、`async`、文档） |
| `events` | `name`、`mode`、`doc`、`declared_by`、`listeners`；带 `name` 过滤，无匹配时列出 `available` |
| `plugins` | Loader 快照 `id`、`name`、`state`、`kind`、`provides`、`inject`、`missing`、`error`；带 `name` 按 id 或插件名匹配 |
| `config` | 条目 `id`、`name`、`state`、`has_schema`；带 `name`（条目 id）：`raw_config`、`schema`、`package_dir`、`doc`、`effective_config`（脱敏） |
| `tools` | `registered`（`ToolRecord.describe()`）与 `approval_gates`；带 `name`：完整 `description`、`args_schema` |
| `routes` | `ctx.http.contributions()` 与 `routes()`；无 `http` → `error` |
| `prompt` | `ctx.prompt.sections()`；无 `prompt` → `error` |
| `ui` | `ctx.webui.slots()`、`clients()`、浏览器模块契约；带 `name` 取一个槽位 |

| 脱敏 | 规则 |
|---|---|
| 原始值含 `${env:` | `REDACTED` |
| 字段名含 `key`、`secret`、`token`、`password`、`passwd`、`dsn`、`credential` 且值非空 | `"<redacted>"` |
