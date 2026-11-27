# pyxis-harness-agent-loop-deepagents

默认的 agent loop，基于 deepagents。

| 项 | 值 |
|---|---|
| 条目 | `agent-loop`（`base` bundle） |
| 服务 | `DeepAgentsLoop`，`ctx.agentLoop` |
| 注入 | `llm`、`tools`、`prompt`、`checkpointer` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 公开名称 |
| `service.py` | `DeepAgentsLoop`：`agentLoop` 服务；扩展点、预设与模式、`build()` |
| `graph.py` | 图的构建：带技能与挂载的 backend、写入拒绝规则、子 agent 解析、`create_deep_agent` |
| `middleware.py` | `HarnessMiddleware`：LangChain middleware，模型调用与工具调用经 harness 走；`RequestScope`、`ContextMeter`：上下文各部分的估算 |
| `config.py` | 权限模式、agent 预设、loop 配置 |
| `config.toml` | 权限模式与内置 agent 预设 |
| `prompts.toml` | 模型可见的文本 |

## 与 `ctx.agents` 的契约

| 项 | 契约 |
|---|---|
| `build()` 的返回值 | LangGraph 图，带 `astream` 与 `aget_state` |
| `build(workspace, mode, preset)` | 构建一张图 |
| `build()` | 默认图；在 `app/ready` 构建 |
| 会话 | 选择 workspace（根目录）、权限模式、agent 预设 |
| `ctx.agents` | 每种组合保留一张图 |
| 替换 | 另一个 loop 经 patch 替换本条目 |

## 服务（`service.py`）

| 成员 | 契约 |
|---|---|
| `build()` | `pyxis_harness_agent_loop_deepagents.graph.build` |
| `add_subagent()` | 声明式子 agent spec，归调用方插件所有；返回 disposer |
| `add_middleware()` | LangChain `AgentMiddleware`，排在 `HarnessMiddleware` 之后；返回 disposer |
| `add_skills()` | 技能目录，只读挂载到 `/skills/<label>/`；返回 disposer |
| `add_mount()` | 目录，挂载到给定的虚拟路径；只读，`writable=True` 时可写；挂载点之上的各级目录列出其下的挂载，不含其他内容；返回 disposer |
| `add_preset()` | agent 预设，归调用方插件所有；返回 disposer |
| `add_mode()` | 权限模式，归调用方插件所有；`base`：沿用其规则的内置模式；`build`：编辑该模式下 `create_deep_agent` 的关键字参数；返回 disposer |
| `preset()` | 给定预设 id 或默认预设的 `(id, config)`；未知 id 抛出 `ValueError` |
| `default_mode()` | `config.default_mode`；该模式不存在时 `workspace-write` |
| `mode()` | 给定的权限模式 id 或默认模式；未知 id 抛出 `ValueError` |
| `set_defaults()` | 新会话的默认值（即时生效）；默认模式是任一已有模式；持久化由 settings API 完成 |
| `presets()` | 供选择器的名单：`id`、`title`、`description`、`order`、`default`、`owner` |
| `modes()` | 供选择器的名单：`id`、`title`、`description`、`default`、`builtin`、`owner` |
| `skills()` | 已挂载的技能目录：`label`、`path`、`mount`、`owner`、`presets` |
| `mounts()` | 挂载：`mount`、`path`、`owner`、`presets`、`writable` |
| `mounted(path)` | 磁盘路径在挂载内对应的虚拟路径；不在任何挂载内：`None` |
| `mount_target(path)` | 虚拟路径在挂载内对应的磁盘路径；不在任何挂载内：`None` |
| `subagents()` | 每个已添加子 agent 的 `name` 与 `owner` |
| `recursion_limit` | `config.recursion_limit`：一次运行的 LangGraph 步数，默认 10000；`ctx.agents` 的 `max_steps` 之后的兜底 |
| `set_parallel_tool_calls(limit)` | `config.max_parallel_tool_calls`（默认 10）；即时生效 |

系统提示词的身份 section（order 0）：`config.system_prompt`。

## 事件

启动时定义：

| 事件 | 模式 | 监听者收到 |
|---|---|---|
| `agent/model-request` | waterfall | `ModelCall` |
| `agent/model-retry` | parallel | `ModelRetry` |
| `agent-loop/build` | waterfall | `create_deep_agent` 的关键字参数 |

## 权限模式

| 权限模式 | 效果 |
|---|---|
| `read-only` | 拒绝文件写入；无 `execute` 工具；去掉带 `shell` 标签的工具；审批按配置 |
| `workspace-write` | 可写 workspace 内；审批按配置 |
| `full-access` | 可写 workspace 内；无审批门 |
| 插件添加的模式 | `base` 的效果，再经它的 `build` |

| 构建顺序 | 内容 |
|---|---|
| 1 | `base` 的文件规则、shell 工具、审批门 |
| 2 | 模式的 `build(kwargs)` |
| 3 | `agent-loop/build` |

## 预设

| 维度 | 效果 |
|---|---|
| `tools` | 预设保留的已注册工具名（`None`：全部） |
| `exclude_tools` | 预设去掉的已注册工具名 |
| 技能 | `add_skills(..., presets=[...])`：为预设挂载的技能目录 |
| 挂载 | `add_mount(..., presets=[...])`：为预设挂载的目录 |
| 提示词 section | `ctx.prompt.add(..., presets=[...])`：section 只对这些预设生效 |

## `build()` 的输入

| 输入 | 来源 |
|---|---|
| 模型 | `ctx.llm` |
| 工具 | `ctx.tools` |
| 系统提示词 | `ctx.prompt` |
| 持久化 | `ctx.checkpointer`；`ctx.store`（存在时） |
| 文件、shell | `ctx.backend` 与 `ctx.workspace` 的权限（存在时） |
| 审批 | `ctx.tools.interrupt_on()` 与 `config.interrupt_on` |
| 子 agent | `config.subagents` 与 `DeepAgentsLoop.add_subagent` |
| 技能 | `config.skills` 与 `DeepAgentsLoop.add_skills` |
| 挂载 | `DeepAgentsLoop.add_mount` |

## 图的构建（`graph.py`）

| 函数 | 契约 |
|---|---|
| `backend_and_skills()` | workspace 与模式对应的 backend（技能目录与挂载已路由进去）、技能来源、写入拒绝规则：技能与只读挂载拒绝写入，可写挂载只在只读模式下拒绝 |
| `mount_tree()` | 挂载的 backend：每个目录在其路径上，其上的各级目录为 `MountDirectory` |
| `resolve_subagent()` | 一个子 agent spec 内：工具名 → 已注册的工具，model spec → 模型 |
| `built_model()` | 构建图所用的 `(spec, model)`；默认模型在启动时不可用：`echo:echo` |
| `build()` | 编译好的 deepagents 图，取自 loop 的 context、配置与扩展状态 |

### 技能挂载

| 项 | 契约 |
|---|---|
| 对象 | 插件添加的技能目录 |
| 挂载 | 只读，`/skills/<label>/`；`ctx.backend` 之上的 `CompositeBackend` 路由 |
| 系统提示词 | deepagents 列出这些技能 |
| 读取 | 模型用 `read_file` 读技能 |

### 默认模型不可用

| 项 | 契约 |
|---|---|
| 条件 | 默认模型在启动时无法初始化：缺包或缺凭据 |
| 启动 | 预检之外不失败 |
| 图 | 以 `echo:echo` 构建 |
| 请求 | 每个请求解析配置的模型；错误到达会话 |
| 设置页 | 保持可用 |

## `HarnessMiddleware`（`middleware.py`）

运行于主 agent 与每个声明式子 agent。

| 钩子 | 路由 |
|---|---|
| 模型调用 | 模型取自 `configurable.model_spec` 或 `ctx.llm.default`，与构建图所用的不同时替换；然后 `agent/model-request`（waterfall） |
| 工具调用 | `ctx.tools.execute`；同一会话在该 agent 内同时执行的调用不超过 `max_parallel_tool_calls` |

`ModelCall`：`agent/model-request` 监听者收到的载荷；`meta`：`model_spec`、`subagent`（该调用来自子 agent）。

并行上限按 agent 各自计数：子 agent 运行在父 agent 的一次工具调用之内。

## 上下文的估算（`middleware.py`）

| 对象 | 契约 |
|---|---|
| `RequestScope` | 主 agent 的 middleware，排在插件的之后（最内层）：标记主 agent 的模型调用正在进行 |
| `ContextMeter` | 图的回调：模型调用开始时，量取发出的请求，经 `ctx.agents.publish` 发布 `context` 运行事件 |
| 量取的请求 | 实际发出的那一份：系统消息已含全部 middleware 的追加 |
| 不量取 | `RequestScope` 之外的模型调用：子 agent、审查模型、压缩的摘要模型 |

| `context_sizes()` 的部分 | 估算 |
|---|---|
| `system` | 系统消息的字符数 / 4，加 4 |
| `tools` | 工具 schema 的 JSON 字符数 / 4，加 4 |
| `messages` | 其余消息的 `count_tokens_approximately` |

### 模型调用的重试

| 项 | 契约 |
|---|---|
| 策略 | 调用所属路由的重试策略：`ctx.llm.retry_policy` |
| 重跑 | 策略的等待之后 handler 再运行一次 |
| 位置 | waterfall 之内；监听者只看到一次调用 |
| `agent/model-retry` | 每次等待之前分发，携带 `ModelRetry` |
| 取消 | 从不重试 |

## 配置（`config.py`、`config.toml`）

| 名称 | 契约 |
|---|---|
| `SKILLS_MOUNT` | 只读技能挂载的根：`/skills/<label>/` |
| `MODES` | 按 id 的内置权限模式：`title`、`description` |
| `Mode` | 一个权限模式：`id`、`title`、`description`、`base`、`build` |
| `DEFAULT_SYSTEM_PROMPT` | 系统提示词的身份 section（order 0） |
| `PresetConfig` | 一个 agent 预设：标题、描述、保留 / 去掉的工具、顺序 |
| `DEFAULT_PRESETS` | `standard` 与 `creator` |
| `LoopConfig` | 服务的配置 |

| `config.toml` | 契约 |
|---|---|
| 内容 | 权限模式、内置 agent 预设 |
| 加载 | `config.py`：`package_toml(__file__)` |
| 顺序 | 表保持文档顺序；选择器按此顺序显示 |

## 提示词（`prompts.toml`）

| 项 | 契约 |
|---|---|
| 表名 | 使用该表的模块名 |
| 加载 | `pyxis_harness.package_prompts`；每个字符串值去除首尾空白 |
| 占位符 | `string.Template` 语法：`${name}` |
