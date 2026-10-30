# 与 dsh 的对照

[DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness)：TypeScript，Cordis 引擎。

| dsh | pyharness |
|---|---|
| Cordis：服务容器、`inject`、类型化事件、可逆副作用 | `pyharness-core`：`Context`、`inject`、`EventBus`、`on_dispose` / `effect` / `enter` |
| 事件模式 emit / parallel / serial / bail / waterfall | 同名模式，另有 `series`：按序运行全部监听者，异常抛出；用于生命周期 |
| `ctx.tools`、`ctx.llm`、`ctx.systemPrompt` | `ctx.tools`、`ctx.llm`、`ctx.prompt` |
| `core/agent` + `core/agent-loop` | `pyharness-agent` + `pyharness-agent-loop-deepagents` |
| profile + bundle + `cordis.patch.yml` | profile + bundle（entry point）+ `harness.patch.yaml`；按 id 寻址的分层 patch |
| `isolate` | 组条目的 `isolate: [key]` |
| HMR：进程内热替换 | 换代：supervisor + worker generation |
| Plugin Manager + 创造模式（`cordis` preset：`dsh-tool-cordis` + skills） | `plugin_manager` + `harness_inspect` + `creator` bundle：skills 挂载到 `/skills/pyharness/`，deepagents skills 中间件按需加载 |
| `dsh-harness-dev-context` | `pyharness-dev-context` 提示词段 |
| `dsh-skill` + `dsh-skill-filesystem` + `dsh-tool-skill` | deepagents `SkillsMiddleware`；`ctx.agentLoop.add_skills` |
| 插件的浏览器端（client slot） | 无；Web 界面是挂路由的插件 |

## 生效方式

| | dsh | pyharness |
|---|---|---|
| 副作用归属追踪 | 有 | 有 |
| 归属追踪的用途 | 热替换、卸载 | 有序关闭、失败插件清理 |
| 配置变更生效 | 进程内 | 新一代进程 |
| 组合时机 | 运行时 | 每代启动时一次 |
| 变更前检查 | — | 独立进程预检 |
| 启动失败 | — | 回滚到 last-known-good |
| 会话 | — | 跨代续跑 |

细节：[lifecycle.md](lifecycle.md)。

## FastAPI 的位置

FastAPI router / sub app 对应一个扩展点：`ctx.http.include_router()`、`ctx.http.mount()`。

| 插件能力 | 扩展点 |
|---|---|
| 提供服务 | `ctx.provide` / `Service` |
| 监听事件 | `ctx.on` |
| 包住工具调用 | `tools/execute`（waterfall） |
| 系统提示词片段 | `ctx.prompt.add` |
| 替换 agent loop | patch `agent-loop` |
| HTTP 路由 | `ctx.http` |

bundle 中条目的位置（`after` / `before` / `parent`）对应 mount 路径。

## 未覆盖

| dsh 能力 | pyharness |
|---|---|
| 插件的浏览器端（client slot） | 无；界面扩展仅限 HTTP 路由 |
| 每会话 agent preset（preset + isolate realm） | 无；全部会话共享一套组合。创造模式按 profile 启用（`creator` bundle），不按会话 |
| 进程内热替换 | 换代重启 |
