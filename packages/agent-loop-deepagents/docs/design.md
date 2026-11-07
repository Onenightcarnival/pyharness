# pyharness-agent-loop-deepagents

`ctx.agentLoop`：基于 deepagents 的默认代理循环（agent loop），按工作区（workspace）、权限模式（permission mode）与代理预设（preset）构建 LangGraph 图。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__.py` | 包契约文档字符串；导出公开名称 |
| `config.py` | `SKILLS_MOUNT`、`MODES`、`DEFAULT_SYSTEM_PROMPT`、`PresetConfig`、`DEFAULT_PRESETS`、`LoopConfig` |
| `middleware.py` | `HarnessMiddleware`：模型调用与工具调用经由 harness；`ModelCall` 事件载荷 |
| `graph.py` | 构图：工作区 backend 与 skills 挂载、写禁止规则、子代理解析、启动时的模型回退、`create_deep_agent` |
| `service.py` | `DeepAgentsLoop`：生命周期、扩展点（子代理、中间件、skills、预设）、预设与模式查询、`build()` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `DeepAgentsLoop` | `Service` 子类 | 服务键 `agentLoop`；entry point `pyharness-agent-loop-deepagents` |
| `LoopConfig` | pydantic 模型 | 服务配置 |
| `PresetConfig` | pydantic 模型 | 一个代理预设：`title`、`description`、`tools`、`exclude_tools`、`order` |
| `HarnessMiddleware` | `AgentMiddleware` 子类 | 主代理与每个声明式子代理中的 harness 中间件 |
| `ModelCall` | dataclass | `agent/model-request` 监听者看到的一次模型调用：`session_id`、`request`、`meta` |
| `MODES` | `dict[str, dict[str, str]]` | 权限模式：`read-only`、`workspace-write`、`full-access` 的 `title`、`description` |
| `DEFAULT_PRESETS` | `dict[str, PresetConfig]` | `standard`、`creator` |
| `SKILLS_MOUNT` | `str` | `/skills`：skills 只读挂载根 |

## 服务

| 项 | 值 |
|---|---|
| 服务键 | `agentLoop` |
| 注入 | `llm`、`tools`、`prompt`、`checkpointer` |
| `Config.model` | `None`；模型 spec，`None` 取 `ctx.llm` 默认 |
| `Config.default_preset` | `"standard"`；新会话的预设 |
| `Config.default_mode` | `"workspace-write"`；新会话的权限模式，非法值在构造时抛 `ValueError` |
| `Config.presets` | `DEFAULT_PRESETS` 的副本；按 id 的预设 |
| `Config.system_prompt` | `DEFAULT_SYSTEM_PROMPT`；系统提示的 identity 段（order 0） |
| `Config.interrupt_on` | `{}`；按工具名的额外审批门 |
| `Config.subagents` | `[]`；声明式 deepagents SubAgent spec，`tools` 项为已注册工具名或工具对象 |
| `Config.skills` | `None`；backend 中的 skill 来源路径（如 `/skills/mine/`） |
| `Config.memory` | `None`；AGENTS.md 风格记忆文件，相对 backend 根 |
| `Config.recursion_limit` | `200` |
| `start()` | 定义 `agent/model-request`、`agent-loop/build`；`ctx.prompt.add("identity", system_prompt, order=0)` |
| `stop()` | 无 |

### 权限模式

| 模式 | 效果 |
|---|---|
| `read-only` | 文件写入被禁止（`FilesystemPermission` deny `/`、`/**`），backend 不带 shell，标签 `shell` 的工具剔除；审批门按配置 |
| `workspace-write` | 工作区内写入；审批门按配置 |
| `full-access` | 工作区内写入；无审批门 |

### 预设

| 字段 | 效果 |
|---|---|
| `tools` | 保留的已注册工具名（`None`：全部） |
| `exclude_tools` | 剔除的已注册工具名 |
| `add_skills(presets=[...])` | skills 目录只对这些预设挂载 |
| `ctx.prompt.add(..., presets=[...])` | 提示段只对这些预设渲染 |

`build(workspace, mode, preset)` 读取：`ctx.llm`（模型）、`ctx.tools`（工具、`interrupt_on()`、`records()` 的标签）、`ctx.prompt.render(preset)`、`ctx.checkpointer`、`ctx.store`（可选）、`ctx.workspace.backend_for / open / permissions`（可选，否则 `ctx.backend`）。系统提示末尾追加 `## Session policy` 段：权限模式、预设、工作区根。启动时默认模型不可用（缺包或凭证）且非 preflight 且存在 `echo` 提供方时，图以 `echo:echo` 构建，每次请求再解析配置的模型。

## 事件 / 工具 / 路由 / 提示段

### 事件

| 事件 | 类型 | 载荷 |
|---|---|---|
| `agent/model-request` | waterfall（定义） | `ModelCall`；`await next()` 返回 ModelResponse；模型取 `configurable.model_spec` 或 `ctx.llm.default`，与构建模型不同时替换 |
| `agent-loop/build` | waterfall（定义） | `create_deep_agent` 的关键字参数 dict；监听者修改后 `return await next()` |

### 提示段

| id | order | 内容 |
|---|---|---|
| `identity` | 0 | `config.system_prompt` |

## 数据

| 项 | 所有者 | 形状 |
|---|---|---|
| 子代理 | `DeepAgentsLoop._subagents` | 内存：`(spec, owner entry_id)`；随调用方插件 dispose 移除 |
| 中间件 | `DeepAgentsLoop._middleware` | 内存：`(AgentMiddleware, owner)`；排在 `HarnessMiddleware` 之后 |
| skills 挂载 | `DeepAgentsLoop._skills` | 内存：`(label, directory, owner, presets)`；模型侧只读挂载于 `/skills/<label>/`（`CompositeBackend` 路由，`FilesystemBackend(virtual_mode=True)`），每个挂载一条写禁止规则 |
| 插件预设 | `DeepAgentsLoop._presets` | 内存：`id -> (PresetConfig, owner)`；与 `config.presets` 重名时 `ValueError` |
| 默认值 | `config.default_preset`、`config.default_mode` | `set_defaults()` 即时修改；持久化由 settings API 负责 |

本包不拥有文件、store 或凭证引用。
