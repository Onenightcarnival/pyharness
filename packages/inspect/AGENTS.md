# pyharness-inspect

`harness_inspect` 工具：运行中 harness 的只读视图。

| 项 | 值 |
|---|---|
| 条目 | `inspect`（`base` bundle） |
| 插件 | `apply`（函数插件） |
| 注入 | `tools` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | `Config`、`Inspector`、`apply` |
| `prompts.toml` | 模型可见的文本 |

## 主题

| `topic` | 内容 | 带 `name` |
|---|---|---|
| `overview` | generation、profile、条目计数、服务键、事件 | |
| `services` | 服务键 | 类型、所有者、方法 |
| `events` | 名称、模式、声明方、监听方 | |
| `plugins` | Loader 条目与状态 | |
| `config` | 条目 | 配置的 JSON Schema、生效配置、包目录 `package_dir`、包的 `AGENTS.md` 路径 `docs` |
| `tools` | 已注册的工具与审批门 | 参数 schema |
| `routes` | HTTP 路由及贡献它们的插件 | |
| `prompt` | 系统提示词的段 | |
| `ui` | Web UI 扩展槽与已注册的客户端模块（`ctx.webui`） | |

| `package_dir`、`docs`（`config`、带 `name` 的 `plugins`） | 值 |
|---|---|
| 包在 `ctx.agentLoop` 的只读挂载内 | 挂载内的路径，文件工具可读 |
| 其余 | 磁盘路径 |

## 脱敏

| 生效配置中的值 | 输出 |
|---|---|
| 来自 `${env:...}` | 脱敏 |
| 字段名形似密钥 | 脱敏 |

## `prompts.toml`

| 项 | 契约 |
|---|---|
| 表 | `[tools]`：工具描述，键为工具名 |
| 读取 | `pyharness.package_prompts`；每个字符串值去掉首尾空白 |
| 占位符 | `string.Template` 语法（`${name}`） |
