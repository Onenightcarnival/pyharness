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
| 插件的浏览器端（client slot） | 有：`ctx.webui.register_client` + 页面槽位（侧边栏行、更多菜单、主区面板、输入框停靠位、设置分区、右侧栏 tab）；模块为无打包的 JS，`window.__PyhModules__.load({id, factory})` |
| `dsh-sandbox-policy` + `dsh-permission-presets`（read-only / workspace-write / danger-full-access） | `agent-loop` 的权限模式 `read-only` / `workspace-write` / `full-access`：deepagents 文件权限规则、shell 工具有无、审批闸门有无；每会话可切换 |
| `dsh-workspace` + directory picker | `pyharness-workspace` 注册表：每会话工作区根目录、最近列表（`ctx.store`）、目录浏览 |

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
| 插件的浏览器端（client slot） | 有；槽位种类对齐 dsh（list / keyed），未做 chain 类型与独立构建链 |
| 右侧栏 | 每会话标签布局、开始页、文件树、文档预览（Markdown / 代码 / 纯文本 / 图片）、终端 tab（PTY + xterm.js）、后台任务 tab、全屏形态；未做分栏、浮窗与浏览器 tab |
| 代码高亮 | dsh 用 Shiki（浏览器端 TextMate grammar）；pyharness 用服务端 Pygments，回复定稿后高亮 |
| 改动文件卡片与 review | 有：git 快照摘要、轮末卡片、右侧栏 diff tab（单栏 / 左右）；未做文件工具编辑的兜底捕获，非 git 工作区不记录 |
| 轮次过程折叠 | 有：过程组 + 四档展示模式 + 收起时机；dsh 的滚动跟随与折叠动画未做 |
| 会话统计 / token 用量 | 有：每轮 stats 持久化、统计条与弹层、每轮用量行、上下文占用圆环（需模型声明上下文窗口）；dsh 的 token-meter 做逐节点估算，pyharness 只按最近用量加估算 |
| 斜杠命令（`dsh-commands` + `dsh-client-ui-commands`）与 `@` 引用（`dsh-client-ui-reference` + `dsh-file-references`） | 有：页面侧命令注册表（内置 compact / new / model / mode / files / terminal / jobs / clear / settings / help，插件 `ctx.commands.register`）与 `/` 菜单；`@` 文件菜单（`/workspaces/search`）与 host 侧展开成附件块；未做 dsh 的 host 命令注册表与会话日志记录、`@session` 引用、原子引用胶囊 |
| 常驻 shell（`dsh-tool-bash-persistent` + `dsh-terminals`）、后台任务（`dsh-tool-jobs` + `dsh-api-job-controller`）、终端 tab（`dsh-api-terminal-controller`） | 有：`pyharness-terminal`，`bash` 每会话常驻（管道 + 结束标记，不用 tmux）、`run_in_background` / `job_output` / `job_list` / `job_kill`、PTY 终端 WebSocket；dsh 的沙箱策略（`dsh-bash-sandbox`）与 headless xterm 回放未做（这里保留字节缓冲） |
| `ask_user_question`（`dsh-tool-ask-user` + `dsh-user-questions` + 问题卡片） | 有：`pyharness-ask-user`，同样的问题 / 答案结构（id、options、multi_select、selected、custom）；用 LangGraph interrupt 暂停，`POST /sessions/{id}/answers` 续跑；未做 dsh 的 timed 模式（超时后继续工作、稍后补答） |
| Web 工具（`dsh-web` seam + `dsh-web-search-deepseek` / `dsh-web-fetch-http` + `dsh-tool-web`） | 有：`pyharness-web-tools` 的 `web_search`（只有 DeepSeek 原生搜索，同样的 Anthropic 格式请求；密钥取 `DEEPSEEK_API_KEY` 凭据）与 `web_fetch`（stdlib HTML → 文本，dsh 用 turndown 转 Markdown）；作为可选的 `web` bundle 预置，插件页可关闭；未做多 provider seam、搜索设置页与结果卡片 |
| 上下文压缩（`dsh-compaction-basic` + `/compact`） | 有：`pyharness-compaction`，自动（阈值 / 保留比例）与 `/compact`，dsh 同款结构化检查点提示词；摘要调用用纯文本转写而非复用请求前缀缓存；未做工具结果裁剪与图片卸载（`dsh-compaction-tool-result-pruner` / `image-offload`） |
| 记忆（dsh-toolkit memory） | 有：`pyharness-memory`，同样的四层树、工具形状与提示词、版本历史与页面；内置于 `toolkit` bundle |
| 数据库（dsh-toolkit rdb） | 有：`pyharness-rdb`，同样的四种引擎、工具形状、分页 / 网格改动 / CSV；读语句分类放宽了 `CASE…END`、`SHOW CREATE`、`PRAGMA x(...)`；行上限用游标 fetchmany 而不是整表取回；SQLite 也有语句超时 |
| S3（dsh-toolkit s3） | 有：`pyharness-s3`，同样的 profile 模型、11 个工具、页面；boto3 而不是 AWS SDK for JS |
| 配置中心（dsh-toolkit config-center） | 有：`pyharness-config-center`，MCP 页 + 连接测试 + JSON 导入、技能页（SKILL.md 包，挂载为 `/skills/user/`）、环境依赖页（受管 bun 替代 dsh 的受管 uv，覆盖 JS MCP 服务器） |
| 可观测（dsh-toolkit otel） | 有：`pyharness-otel`，同样的 trace 结构与属性名、Langfuse 端点处理与测试流程；由本轮记录生成 span 而不是在调用链里实时打点，没有指标导出 |
| AI 订阅（dsh-toolkit subscriptions） | 有：`pyharness-subscriptions`，四个提供方的登录、目录、用量、聊天与七个工具；未做多账号配额感知的池化路由与出站代理设置，每个提供方用默认账号 |
| API 网关（dsh-toolkit gateway） | 有：`pyharness-gateway`，同样的三种协议端点、参数取舍、错误形状、API key、用量账本与页面；模型请求走 LangChain `astream` 而不是 dsh 的流式块协议，图片不经附件存储而是直接以 data URL 传给模型；`reasoning_effort` 只传给 `openai`、`azure_openai`、`subscription` 类型的路由；管理路由没有 dsh 的浏览器会话与回环校验 |
| HTTP 请求工具（dsh-toolkit http） | 有：`pyharness-http-client`，同样的目标、保存的请求、历史、host 与内网策略、重定向规则、遮罩、事件流读取和三个 agent 工具；包名与路由前缀换成 `http-client`（`pyharness-http` 已是 FastAPI 服务）；管理路由没有 dsh 的浏览器会话与回环校验；出站请求走 httpx，遵循环境变量里的代理设置 |
| MCP 客户端 | 有：`pyharness-mcp`，stdio / HTTP / SSE，左侧栏 MCP 页配置，`${credential:REF}` 凭据模板（连接时解析、缺值时「等待凭据」、错误文本遮罩）；未做 MCP resources 与 prompts |
| 左侧栏入口固定 / 取消固定（服务端保存） | 有：`GET` / `PUT /api/webui/prefs`，取消固定的入口进「更多」菜单 |
| 文件页搜索 | 有：右侧栏文件页的搜索框，结果为裁剪后的树；用服务端遍历（最多 30000 项、返回 500 条）而不是 dsh 的索引 |
| 回复里的 diff 着色与数学公式 | 有：diff 围栏按行着色；公式用随包分发的 KaTeX 输出 MathML（不带 KaTeX 的 CSS 与字体，排版交给浏览器的 MathML） |
| 模型重试策略（全局 + 每提供方）与失败代码 | 有：`pyharness-llm` 的 `RetryPolicy`（瞬时错误 / 所有错误、次数、失败代码、退避）与 `failure_code`，重试在 `agent/model-request` 的最内层执行并发出 `agent/model-retry`；失败代码由异常的 HTTP 状态与类型归类，不像 dsh 由各 provider 插件在流式块里给出，所以 `EMPTY_RESPONSE`、`STREAM_CLOSED` 只有订阅类提供方会产生 |
| 失败轮次「继续生成」 | 有：`POST /sessions/{id}/retry`，LangGraph 从失败那一步的检查点续跑；可继续的失败代码与 dsh 相同（限流、服务端、超时、网络、空响应、流中断） |
| 自定义端点的 Gemini 协议 | 有：`gemini` 协议走 `langchain-google-genai`，模型列表取 `/v1beta/models` |
| 轨迹视图 | 有：按轮次的记录表、时间概览、详情面板；dsh 的虚拟滚动、分页加载与完整输入输出检查未做（记录只存摘要尺寸） |
| 每会话 agent preset（preset + isolate realm） | 预设是 `agent-loop` 的配置（工具子集、skills、提示词片段），每会话一张图；没有 realm 级的服务隔离 |
| 进程内热替换 | 换代重启 |
