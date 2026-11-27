# 插件

## 内核插件

| 包 | 条目 id | 服务 | 职责 |
|---|---|---|---|
| `pyxis-harness-core` | — | `loader`、`lifecycle`、`profile`、`events` | 内核：容器、事件、组合、Loader、worker、supervisor、预检、CLI |
| `pyxis-harness-llm` | `llm` | `llm` | 模型提供方注册表；`resolve("provider:model")`；内置 `echo`；插件用 `publish(routes)` 发布路由（可解析、进模型菜单，不进配置、不出现在「设置 → 模型」、不被保存）；自定义端点协议（OpenAI Chat / Responses、Anthropic Messages、Gemini）；失败代码（`failure_code(exc)`）与重试策略（`retry_policy(spec)`：路由自己的，否则全局的，否则不重试） |
| `pyxis-harness-tools` | `tools` | `tools` | 工具注册表、执行管线、审批闸门 |
| `pyxis-harness-mcp` | `mcp` | `mcp` | MCP 服务器的工具注册进 `ctx.tools`（stdio 或 HTTP / SSE），工具名加服务器前缀；连接失败不影响启动，`status()` 可查；stdio 命令为裸 `bun` / `bunx` 且配置中心装了受管 bun 时改走它（`managed_bun`）；`probe()` 给配置中心的连接测试；命令、参数、环境变量、工作目录、地址、请求头里可以写 `${credential:REF}`，连接时从环境变量 `REF` 或 profile 凭据文件取值，缺值的服务器状态为 `waiting-credentials`、不连接，已解析的值在状态 / 测试 / 日志的错误文本里显示为 `[redacted]` |
| `pyxis-harness-prompt` | `prompt` | `prompt` | 有序的系统提示词片段 |
| `pyxis-harness-ask-user` | `ask-user` | `askUser` | `ask_user_question` 工具：agent 提问（可带选项、多选、标题），运行以 LangGraph interrupt 暂停，Web UI 显示问题卡片；`POST /sessions/{id}/answers` 回答后续跑，工具返回 `{"answers": [{"id", "selected", "custom"?}]}`，问答结构与 dsh 一致 |
| `pyxis-harness-checkpoint-sqlite` | `checkpoint` | `checkpointer`、`store` | SQLite 持久化 |
| `pyxis-harness-checkpoint-postgres` | `checkpoint` | `checkpointer`、`store` | Postgres 持久化；共享连接池 |
| `pyxis-harness-checkpoint-memory` | `checkpoint-temporary` | `temporary` | 临时会话的持久化：进程内存中的 checkpointer 与 store |
| `pyxis-harness-workspace` | `workspace` | `workspace`、`backend` | 工作区注册表：默认工作区、每会话工作区、最近列表、目录浏览；deepagents `FilesystemBackend` / `LocalShellBackend` |
| `pyxis-harness-agent-loop-deepagents` | `agent-loop` | `agentLoop` | deepagents 图，按工作区 × 权限模式 × 预设构建；`add_subagent`、`add_middleware`、`add_skills`、`add_preset`、`add_mode` |
| `pyxis-harness-agent` | `agents` | `agents` | 会话、后台运行、审批、重启续跑；每轮记录（stats + 轨迹）写入 store，`turns(session_id)`；失败轮次记下失败代码，`failure(session_id)` 与 `retry_run(session_id)`（从失败的那一步继续，不加消息） |
| `pyxis-harness-auto-review` | `auto-review` | — | 权限模式「自动审查」（`auto-review`）：带审批门的工具调用先由模型按固定的三档风险策略审查，放行的直接执行，拒绝或审查失败的照常弹出审批；结论记在 AI 消息上并作为 `tool_review` 运行事件发布 |
| `pyxis-harness-compaction` | `compaction` | `compaction` | 上下文压缩：模型调用前，上下文达到阈值（`threshold_ratio` × 窗口）时把较早的历史换成一份结构化检查点（保留 `retain_ratio` × 窗口的最近内容）；`/compact` 手动压缩整段历史；度量取最近一次模型回复的用量加之后消息的估算；窗口取模型声明的 `context_window`，否则 `default_context_window` |
| `pyxis-harness-workspace-changes` | `workspace-changes` | `workspaceChanges` | 每轮改动的文件：轮次起止各做一次 git 工作树快照（私有对象目录，不碰仓库），摘要写入 `done` 事件与 store；逐文件 diff |
| `pyxis-harness-http` | `http` | `http` | FastAPI 根应用 + uvicorn；`include_router`、`mount` |
| `pyxis-harness-api` | `api` | — | `/api`：REST + SSE |
| `pyxis-harness-web-ui` | `web-ui` | `webui` | `/`：Web 界面；`register_client(path, calls=)` 登记插件的浏览器模块，`/plugins/{entry}/client.js` 与 `/plugins/{entry}/call/{method}` |
| `pyxis-harness-terminal` | `terminal` | `terminal` | shell 工具（`bash`；Windows 上为 `pwsh`）：每次调用一个新进程，从工作区根目录或 `workdir` 开始，stdin 为空，超时则转为后台任务；`run_in_background` 参数与 `job_output` / `job_list` / `job_kill` 后台任务（输出写日志文件）；右侧栏「终端」tab 的 PTY（WebSocket `/api/terminals/{id}/ws`）与「后台任务」tab；`shell` 标签的工具在只读模式下不给 agent，shell 工具在工作区写入模式下需审批 |
| `pyxis-harness-inspect` | `inspect` | — | `harness_inspect` 工具 |
| `pyxis-harness-plugin-manager` | `plugin-manager` | — | `plugin_manager` 工具；插件编写 skills（`skills: true`）；三行提示词片段（`guidance`） |
| `pyxis-harness-plugin-manager` | `dev-context` | — | `pyxis-harness-dev-context`：harness 位置提示词段 |
| `pyxis-harness-bundle-base` | — | — | `base` bundle：以上条目的组合 |
| `pyxis-harness-bundle-creator` | — | — | `creator` bundle：`plugin-manager` 的 `skills: true`、`guidance: false` |
| `pyxis-harness-web-tools` | `web-tools` | `web` | `web_search`（DeepSeek Search API：每次搜索一次直连请求 `POST /v1/tools/search`，返回来源的标题、URL、摘要与日期，按每秒 5 次限速；`search_provider: deepseek-legacy` 保留旧路径，即一次 Anthropic 格式的 Messages 调用带 `web_search_20250305` 服务端工具，返回回答与来源）与 `web_fetch`（HTTP 抓取，HTML 转成文本）；搜索密钥取 `DEEPSEEK_API_KEY` 凭据（环境或 profile 凭据库），缺失时工具返回说明而不是让轮次出错 |
| `pyxis-harness-bundle-web` | — | — | `web` bundle：上面两个工具；`optional: true`，默认开启，插件页可关闭 |
| `pyxis-harness-memory` | `memory` | `memory` | agent 的职业履历记忆（对齐 dsh-memory）：`profile → work → project → lesson` 四层树，SQLite 存储（`<profile data>/toolkit/memory.sqlite`），每次改动记一条修订并保存整份快照（内容寻址去重）；`memory_get`（读一个节点：内容、祖先、分页子节点摘要）与 `memory_save`（一次原子应用 1–100 条带类型的改动，`stateToken` 并发校验，`ref` / `@ref` 批内引用）；提示词段 `plugin:memory`（order 155）；两者只在记忆页「允许 Agent 使用」开着时注册；`/api/memory` 路由；左侧栏「记忆」全页 |
| `pyxis-harness-rdb` | `rdb` | `rdb` | 关系数据库工作台（对齐 dsh-rdb）：SQLite（标准库）/ PostgreSQL 与 GaussDB（psycopg 3）/ MySQL 与 MariaDB（PyMySQL）；连接配置存 `<profile data>/toolkit/rdb.json`，密码存 profile 凭据库（`RDB_<ID>`）；多主机按 `targetSessionAttrs`（libpq 语义）挑节点；每个连接一个常驻驱动（空闲 10 分钟关闭）；`db_connections` / `db_schema` / `db_query`（单条只读语句，服务端分类拒绝写入）/ `db_explain` / `db_execute`（一个事务，仅对勾选「允许 Agent 写入」的连接，且须 `confirm=true`）；提示词段 `plugin:rdb`（order 153）；工具与提示词只在数据库页「允许 Agent 使用」开着时注册；`/api/rdb/*` 路由（连接、测试、schema / 表 / 列 / DDL、分页行、query、execute、网格改动预览与应用、CSV 导出）；左侧栏「数据库」全页 |
| `pyxis-harness-s3` | `s3` | `s3` | S3 兼容对象存储浏览器（对齐 dsh-s3）：boto3 客户端（path-style / virtual-host、`when_required` 校验和、3 次重试）；一个 profile 对应一个桶（endpoint、region、AK/SK、限定前缀），配置存 `<profile data>/toolkit/s3.json`，Secret Key 存 profile 凭据库（`S3_<ID>`），所有 key 相对前缀；`s3_buckets` / `s3_list`（按层级或递归、分页）/ `s3_stat` / `s3_get`（文本，二进制拒绝）/ `s3_put` / `s3_upload` / `s3_download` / `s3_copy` / `s3_presign` / `s3_mkdir` / `s3_delete`（前缀递归，须 `confirm=true`）；提示词段 `plugin:s3`（order 152）；工具只在 S3 页「允许 Agent 使用」开着时注册；`/api/s3/*` 路由（配置、测试、列表、stat、下载 / 内联预览、文本、流式上传、删除、文件夹、预签名、复制）；左侧栏「S3」全页 |
| `pyxis-harness-config-center` | `config-center` | `configCenter` | 配置中心（对齐 dsh-config-center）：左侧栏「MCP」全页（服务器列表与状态、编辑器、连接测试 `POST /api/config-center/mcp/test`（真正连上并列出工具）、启动等待 `connect_timeout`、粘贴 `mcpServers` JSON 导入；保存仍走 `PUT /api/settings/mcp`，重启生效；`PUT` / `DELETE /api/config-center/mcp/credentials` 存取 `${credential:REF}` 引用的值，被启用的服务器引用时请求重启）；左侧栏「技能」全页：`<profile data>/toolkit/skills/<name>/SKILL.md`（启用，`ctx.agentLoop.add_skills` 挂载为 `/skills/user/`）与 `disabled-skills/`（停用），ZIP 安装（`.zip` / `.skill`；原样解压，每个顶层条目是一个安装单位、名称取条目名，顶层 `*.md` 存为 `<name>/SKILL.md`；按归档记录保留可执行位，不解压 `__MACOSX`；冲突时询问 / 跳过 / 覆盖）、启停（移动目录）、删除、文件预览、打开目录；设置 →「环境依赖」：受管 bun（固定版本，按发布的 `SHASUMS256.txt` 校验，装在 `<profile data>/toolkit/bun/`），MCP 服务器命令写裸 `bun` / `bunx` 时 `pyxis-harness-mcp` 自动改用它并注入 `BUN_INSTALL` 等环境变量，PATH 不改 |
| `pyxis-harness-otel` | `otel` | `otel` | OpenTelemetry 上报（对齐 dsh-otel）：监听 `agent/turn-end`，按本轮记录构建一条 trace：`enter_ai_application_system`（ENTRY）→ `invoke_agent <preset>`（AGENT）→ `react step`（STEP）→ `chat <model>`（LLM）与 `execute_tool <name>`（TOOL），属性用 GenAI 语义约定（`gen_ai.operation.name` / `gen_ai.usage.*` / `gen_ai.tool.*` / `gen_ai.response.time_to_first_token` 等）外加 `langfuse.session.id`；采集正文时放入输入输出消息、系统提示、工具定义、工具参数与结果（超过 `content_max_chars` 的值换成 `{"truncated": true, …}`）；OTLP/HTTP protobuf，`BatchSpanProcessor`，Langfuse 主机或 `pk-lf-` / `sk-lf-` 密钥自动补 `/api/public/otel`，Basic 认证，可选 gzip；Secret Key 存凭据库 `OTEL_SECRET_KEY`；`/api/otel/status`、`PUT /api/otel/settings`（写 profile 补丁并就地重启管线，无需重启 harness）、`POST /api/otel/test`（连通性、900 KB 大载荷、GenAI 形状三组测试，Langfuse 时再查询 trace 是否入库）、`POST /api/otel/verify`（最近 8 条 trace）；设置 →「可观测」 |
| `pyxis-harness-subscriptions` | `subscriptions` | `subscriptions` | AI 订阅（对齐 dsh-subscriptions）：Codex（OpenAI）、ChatGPT、Google Antigravity、Grok（xAI）四个提供方；本机回环 OAuth（PKCE S256、state / nonce、端口占用时手动粘贴回调 URL、超时与取消）；会话存 `<profile data>/toolkit/subscriptions/auth.json`（0600），令牌管理器提前 5 分钟刷新、并发共享一次刷新、永久性错误时删除账号；模型目录（Codex 目录接口 + npm 查 client 版本、ChatGPT `/v1/models`、Antigravity 两个 origin 合并、Grok 两个接口合并）缓存 5 分钟并落盘；注册 `ctx.llm` 提供方类型 `subscription`，按账号把可见模型发布成路由 `codex` / `chatgpt` / `antigravity` / `grok`（Responses 协议与 Antigravity `v1internal` 的流式翻译：文本、推理、工具调用、用量）；工具 `codex_web_search`、`codex_image_generate`、`antigravity_web_search`、`antigravity_image_generate`、`grok_x_search`、`grok_image_generate`、`grok_video_generate`，开关存 `provider-settings.json`（搜索类立即生效，生成类按会话创建时刻），生成的媒体放 `images/` / `videos/` 并由 `/api/subscriptions/media/{name}` 提供预览；`/api/subscriptions/*` 路由；左侧栏「AI 订阅」全页 |
| `pyxis-harness-gateway` | `gateway` | `gateway` | API 网关（对齐 dsh-gateway）：把 `ctx.llm` 的模型路由通过 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 三种协议对外提供，独立监听（默认 `127.0.0.1:8766`，`app/serve` 时绑定，绑定失败不影响启动）；`GET /v1/models`、`POST /v1/chat/completions`、`POST /v1/responses`、`POST /v1/messages`，流式与非流式；每个请求带 API key（`Authorization: Bearer` 或 `x-api-key`），key 全文存 `<profile data>/toolkit/gateway/keys.json`（0600，首次启动生成 `default`），可限定可用模型；模型 id 为 `route:model`，`aliases` 做请求名映射，没有默认模型；图片输入（data URL 或 http(s) URL）转成 data URL 交给模型；每个通过鉴权的协议请求写一行到 `usage.sqlite`（token、首字节、耗时、状态、错误码，保留 400 天），按 `pricing` 计费用；`/api/gateway/*` 管理路由；左侧栏「API 网关」全页（概览、API key、用量） |
| `pyxis-harness-http-client` | `http-client` | `httpClient` | HTTP API 请求工具（对齐 dsh-http）：API 目标（Base URL、认证 bearer / basic / header / query、固定 header、`{{变量}}`、密钥变量、允许的额外 host、变更开关、内网开关、超时），密钥只留在宿主、交给页面与 agent 的内容里一律遮罩；保存的请求（每个目标 500 个；可带提取规则：从响应里取值存成变量，带有效期，缺失、过期或 401 时由 harness 自动重发来源请求续期）与不绑定目标的请求（完整 URL，仅页面可用，agent 不可调用也不可见）；请求历史由页面与 agent 共用（默认保留 200 条，正文各截 32 KiB）；配置导出与导入（目标、保存的请求、历史上限为一个 JSON 文件，不含密钥；整份文件先校验，同名目标选覆盖或跳过，覆盖时保留已存密钥，也接受 dsh-http 的导出文件；缺密钥的目标显示「密钥未填写」，其请求不发送）；应答正文、已发送正文与事件数据语法高亮（宿主页的 `/api/highlight`）；重定向最多 5 跳、逐跳检查允许的 host、跨 origin 去掉凭证；`text/event-stream` 逐事件读取，停止、超时、1 MiB 上限都保留已收到的内容；工具 `http_targets`、`http_request`（非 GET / HEAD / OPTIONS 需目标开启变更且 `confirm=true`）、`http_history`，「允许 Agent 使用」开启时注册；数据在 `<profile data>/toolkit/http-client/`（`targets.json`、`requests.json`、`values.json`、`history.jsonl`，0600）；`/api/http-client/*` 路由；左侧栏「HTTP」全页 |
| `pyxis-harness-bundle-toolkit` | — | — | `toolkit` bundle：工具箱各模块（memory、rdb、s3、config-center、otel、subscriptions、gateway、http-client）；`builtin: true`，每个 profile 必含、不可关闭、不可卸载；左侧栏入口可取消固定，收进「更多」菜单 |

条目 id 与配置：`packages/bundle-base/pyxis_harness_bundle_base/bundle.yaml`。

可选 bundle：bundle 定义里 `optional: true` 的 bundle 不必写进 profile 的 `bundles` 列表就会生效（排在显式列表之后），profile 清单的 `disabled` 列表把它关掉；插件页与 `PUT /plugins/bundles/{name}` 对这类 bundle 允许开关，不允许卸载。内置 bundle（`base`）仍然只读。

内置 bundle：bundle 定义里 `builtin: true` 的 bundle（`toolkit`）随环境安装、每个 profile 必含（排在显式列表之后、可选 bundle 之前），`set_bundle_enabled(…, False)` 抛 `ConfigError`，插件页与 API 返回 409；要少看一个模块就取消固定它的左侧栏入口。

## 事件

| 事件 | 模式 | 声明方 | 时机 |
|---|---|---|---|
| `app/ready` | series | 内核 | 全部插件已 apply；组装，不绑定外部资源；预检运行它；出错 → 启动失败 |
| `app/serve` | series | 内核 | 绑定端口、接收外部输入；出错 → 启动失败 |
| `app/started` | parallel | 内核 | 本代已提交：last-known-good 已保存，交接文件已消费；后台工作 |
| `app/stopping` | parallel | 内核 | 卸载之前：取消运行中的轮次，停止 HTTP |
| `tools/execute` | waterfall | tools | 每次工具调用，含 agent loop 内置工具与子 agent；可短路 |
| `tools/result` | parallel | tools | 每次工具调用结束 |
| `agent/model-request` | waterfall | agent-loop | 每次模型调用 |
| `agent/model-retry` | parallel | agent-loop | 重试策略即将重跑一次失败的模型调用；参数 `ModelRetry`（`attempt`、`max_retries`、`code`、`delay_ms`） |
| `agent-loop/build` | waterfall | agent-loop | `create_deep_agent(**kwargs)` 之前；参数为 kwargs |
| `agent/turn-start`、`agent/turn-end` | parallel | agents | 每轮开始、结束；`turn.outcome` 在结束时设置 |

运行时清单与监听者：`harness_inspect topic=events`。

## 工具

| 成员 | 契约 |
|---|---|
| `ctx.tools.register(tool, approval=...)` | 工具归属调用方插件，插件停止时移除 |
| `ctx.tools.require_approval(name, ...)` | 给非本插件的工具加审批闸门 |
| `ctx.tools.interrupt_on()` | agent loop 的人工审批配置 |
| `ctx.tools.execute(...)` | 每次工具调用的管线入口 |

| `approval` | 效果 |
|---|---|
| `False` | 无闸门 |
| `True` | 每次调用审批 |
| `{"allowed_decisions": [...], "description": ..., "when": fn}` | `when(request)` 为真时审批 |

多个闸门作用于同一工具时：最严格者生效；一个插件撤不掉另一个插件的闸门。

## 扩展方式

| 目标 | 做法 |
|---|---|
| 新工具 | `ctx.tools.register` |
| 包住工具调用 | `tools/execute` 监听者 |
| 观察工具结果 | `tools/result` 监听者 |
| 包住模型调用 | `agent/model-request` 监听者 |
| 改 agent 构建参数 | `agent-loop/build` 监听者 |
| 子 agent、中间件 | `ctx.agentLoop.add_subagent`、`add_middleware` |
| 系统提示词片段 | `ctx.prompt.add(id, content, order)` |
| 模型提供方 | `ctx.llm.register(provider, factory)` |
| HTTP 路由、子应用 | `ctx.http.include_router`、`ctx.http.mount` |
| 替换服务 | patch：同一条目 id，换 `name` |

### 持久化：Postgres

`examples/patches/postgres.yaml`：

```yaml
- id: checkpoint
  name: pyxis-harness-checkpoint-postgres
  config:
    dsn: ${env:PYH_POSTGRES_DSN}
```

| 要求 | 值 |
|---|---|
| 数据库编码 | UTF8；`SQL_ASCII` → 插件 `FAILED` |
| 连接池 | `pool_min` 1，`pool_max` 10 |

```bash
PYH_POSTGRES_DSN=postgresql://user:pass@127.0.0.1:5432/pyh uv run pyh run --patch examples/patches/postgres.yaml
```

### shell：`execute` 工具

`examples/patches/shell.yaml`：

```yaml
- id: workspace
  config: {shell: true}
  merge: true
```

每次 `execute` 调用需审批；`shell_approval: false` 取消审批。

### agent loop

`ctx.agents` 的要求：`ctx.agentLoop.build()` 返回带 `astream`、`aget_state` 的 LangGraph 图。

```python
class MyLoop(Service):
    key = "agentLoop"

    async def build(self):
        return create_agent(...)
```

```yaml
- id: agent-loop
  name: my-agent-loop
```

## 第三方 bundle

安装来源有两种：本地 bundle 目录（`pyh plugin install ./my-bundle`，Web 界面可用系统对话框选目录），或 PyPI 包（`pyh plugin install pyh-example==0.1.0`，`--index-url` 指定其他索引）。两种都装进 profile 的 `site/`，先预检再重启；包必须声明 `pyxis_harness.bundles` 入口点，否则拒绝并回滚。

| 部分 | 内容 |
|---|---|
| `pyproject.toml` | entry point `pyxis_harness.plugins`（代码）、`pyxis_harness.bundles`（bundle 文件） |
| `bundle.yaml` | `title`、`description`、`patch`；`after` / `before` / `parent` 决定条目在配置树中的位置 |

```yaml
title: Audit log
description: Tool-call JSONL log, tool denylist, GET /audit.
patch:
  - id: audit
    name: pyxis-harness-audit
    after: tools
    config:
      path: ${data_dir}/audit.jsonl
      deny: []
```

示例：[`examples/pyxis-harness-audit`](../examples/pyxis-harness-audit)。

```bash
uv run pyh plugin install examples/pyxis-harness-audit
```
