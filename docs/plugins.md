# 插件

## 内核插件

| 包 | 条目 id | 服务 | 职责 |
|---|---|---|---|
| `pyharness-core` | — | `loader`、`lifecycle`、`profile`、`events` | 内核：容器、事件、组合、Loader、worker、supervisor、预检、CLI |
| `pyharness-llm` | `llm` | `llm` | 模型提供方注册表；`resolve("provider:model")`；内置 `echo` |
| `pyharness-tools` | `tools` | `tools` | 工具注册表、执行管线、审批闸门 |
| `pyharness-mcp` | `mcp` | `mcp` | MCP 服务器的工具注册进 `ctx.tools`（stdio 或 HTTP / SSE），工具名加服务器前缀；连接失败不影响启动，`status()` 可查；stdio 命令为裸 `bun` / `bunx` 且配置中心装了受管 bun 时改走它（`managed_bun`）；`probe()` 给配置中心的连接测试 |
| `pyharness-prompt` | `prompt` | `prompt` | 有序的系统提示词片段 |
| `pyharness-ask-user` | `ask-user` | `askUser` | `ask_user_question` 工具：agent 提问（可带选项、多选、标题），运行以 LangGraph interrupt 暂停，Web UI 显示问题卡片；`POST /sessions/{id}/answers` 回答后续跑，工具返回 `{"answers": [{"id", "selected", "custom"?}]}`，问答结构与 dsh 一致 |
| `pyharness-checkpoint-sqlite` | `checkpoint` | `checkpointer`、`store` | SQLite 持久化 |
| `pyharness-checkpoint-postgres` | `checkpoint` | `checkpointer`、`store` | Postgres 持久化；共享连接池 |
| `pyharness-workspace` | `workspace` | `workspace`、`backend` | 工作区注册表：默认工作区、每会话工作区、最近列表、目录浏览；deepagents `FilesystemBackend` / `LocalShellBackend` |
| `pyharness-agent-loop-deepagents` | `agent-loop` | `agentLoop` | deepagents 图，按工作区 × 权限模式 × 预设构建；`add_subagent`、`add_middleware`、`add_skills`、`add_preset` |
| `pyharness-agent` | `agents` | `agents` | 会话、后台运行、审批、重启续跑；每轮记录（stats + 轨迹）写入 store，`turns(session_id)` |
| `pyharness-compaction` | `compaction` | `compaction` | 上下文压缩：模型调用前，上下文达到阈值（`threshold_ratio` × 窗口）时把较早的历史换成一份结构化检查点（保留 `retain_ratio` × 窗口的最近内容）；`/compact` 手动压缩整段历史；度量取最近一次模型回复的用量加之后消息的估算；窗口取模型声明的 `context_window`，否则 `default_context_window` |
| `pyharness-workspace-changes` | `workspace-changes` | `workspaceChanges` | 每轮改动的文件：轮次起止各做一次 git 工作树快照（私有对象目录，不碰仓库），摘要写入 `done` 事件与 store；逐文件 diff |
| `pyharness-http` | `http` | `http` | FastAPI 根应用 + uvicorn；`include_router`、`mount` |
| `pyharness-api` | `api` | — | `/api`：REST + SSE |
| `pyharness-web-ui` | `web-ui` | `webui` | `/`：Web 界面；`register_client(path, calls=)` 登记插件的浏览器模块，`/plugins/{entry}/client.js` 与 `/plugins/{entry}/call/{method}` |
| `pyharness-terminal` | `terminal` | `terminal` | `bash` 工具：每个会话一个常驻 bash（工作目录与环境变量跨调用保留，从工作区根目录开始，stdin 为 /dev/null，超时则杀掉并重启）；`run_in_background` / `job_output` / `job_list` / `job_kill` 后台任务（输出写日志文件）；右侧栏「终端」tab 的 PTY（WebSocket `/api/terminals/{id}/ws`）与「后台任务」tab；`shell` 标签的工具在只读模式下不给 agent，`bash` 与 `run_in_background` 在工作区写入模式下需审批 |
| `pyharness-inspect` | `inspect` | — | `harness_inspect` 工具 |
| `pyharness-plugin-manager` | `plugin-manager` | — | `plugin_manager` 工具；插件编写 skills（`skills: true`）；三行提示词片段（`guidance`） |
| `pyharness-plugin-manager` | `dev-context` | — | `pyharness-dev-context`：harness 位置提示词段 |
| `pyharness-bundle-base` | — | — | `base` bundle：以上条目的组合 |
| `pyharness-bundle-creator` | — | — | `creator` bundle：`plugin-manager` 的 `skills: true`、`guidance: false` |
| `pyharness-web-tools` | `web-tools` | `web` | `web_search`（DeepSeek 原生搜索：一次 Anthropic 格式的 Messages 调用带 `web_search_20250305` 服务端工具，返回回答与来源）与 `web_fetch`（HTTP 抓取，HTML 转成文本）；搜索密钥取 `DEEPSEEK_API_KEY` 凭据（环境或 profile 凭据库），缺失时工具返回说明而不是让轮次出错 |
| `pyharness-bundle-web` | — | — | `web` bundle：上面两个工具；`optional: true`，默认开启，插件页可关闭 |
| `pyharness-memory` | `memory` | `memory` | agent 的职业履历记忆（对齐 dsh-memory）：`profile → work → project → lesson` 四层树，SQLite 存储（`<profile data>/toolkit/memory.sqlite`），每次改动记一条修订并保存整份快照（内容寻址去重）；`memory_get`（读一个节点：内容、祖先、分页子节点摘要）与 `memory_save`（一次原子应用 1–100 条带类型的改动，`stateToken` 并发校验，`ref` / `@ref` 批内引用）；提示词段 `plugin:memory`（order 155）；两者只在记忆页「允许 Agent 使用」开着时注册；`/api/memory` 路由；左侧栏「记忆」全页 |
| `pyharness-rdb` | `rdb` | `rdb` | 关系数据库工作台（对齐 dsh-rdb）：SQLite（标准库）/ PostgreSQL 与 GaussDB（psycopg 3）/ MySQL 与 MariaDB（PyMySQL）；连接配置存 `<profile data>/toolkit/rdb.json`，密码存 profile 凭据库（`RDB_<ID>`）；多主机按 `targetSessionAttrs`（libpq 语义）挑节点；每个连接一个常驻驱动（空闲 10 分钟关闭）；`db_connections` / `db_schema` / `db_query`（单条只读语句，服务端分类拒绝写入）/ `db_explain` / `db_execute`（一个事务，仅对勾选「允许 Agent 写入」的连接，且须 `confirm=true`）；提示词段 `plugin:rdb`（order 153）；工具与提示词只在数据库页「允许 Agent 使用」开着时注册；`/api/rdb/*` 路由（连接、测试、schema / 表 / 列 / DDL、分页行、query、execute、网格改动预览与应用、CSV 导出）；左侧栏「数据库」全页 |
| `pyharness-s3` | `s3` | `s3` | S3 兼容对象存储浏览器（对齐 dsh-s3）：boto3 客户端（path-style / virtual-host、`when_required` 校验和、3 次重试）；一个 profile 对应一个桶（endpoint、region、AK/SK、限定前缀），配置存 `<profile data>/toolkit/s3.json`，Secret Key 存 profile 凭据库（`S3_<ID>`），所有 key 相对前缀；`s3_buckets` / `s3_list`（按层级或递归、分页）/ `s3_stat` / `s3_get`（文本，二进制拒绝）/ `s3_put` / `s3_upload` / `s3_download` / `s3_copy` / `s3_presign` / `s3_mkdir` / `s3_delete`（前缀递归，须 `confirm=true`）；提示词段 `plugin:s3`（order 152）；工具只在 S3 页「允许 Agent 使用」开着时注册；`/api/s3/*` 路由（配置、测试、列表、stat、下载 / 内联预览、文本、流式上传、删除、文件夹、预签名、复制）；左侧栏「S3」全页 |
| `pyharness-config-center` | `config-center` | `configCenter` | 配置中心（对齐 dsh-config-center）：左侧栏「MCP」全页（服务器列表与状态、编辑器、连接测试 `POST /api/config-center/mcp/test`（真正连上并列出工具）、启动等待 `connect_timeout`、粘贴 `mcpServers` JSON 导入；保存仍走 `PUT /api/settings/mcp`，重启生效）；左侧栏「技能」全页：`<profile data>/toolkit/skills/<name>/SKILL.md`（启用，`ctx.agentLoop.add_skills` 挂载为 `/skills/user/`）与 `disabled-skills/`（停用），ZIP 安装（根 SKILL.md、`<dir>/SKILL.md`、顶层 `*.md`；冲突时询问 / 跳过 / 覆盖）、启停（移动目录）、删除、文件预览、打开目录；设置 →「环境依赖」：受管 bun（固定版本，按发布的 `SHASUMS256.txt` 校验，装在 `<profile data>/toolkit/bun/`），MCP 服务器命令写裸 `bun` / `bunx` 时 `pyharness-mcp` 自动改用它并注入 `BUN_INSTALL` 等环境变量，PATH 不改 |
| `pyharness-otel` | `otel` | `otel` | OpenTelemetry 上报（对齐 dsh-otel）：监听 `agent/turn-end`，按本轮记录构建一条 trace：`enter_ai_application_system`（ENTRY）→ `invoke_agent <preset>`（AGENT）→ `react step`（STEP）→ `chat <model>`（LLM）与 `execute_tool <name>`（TOOL），属性用 GenAI 语义约定（`gen_ai.operation.name` / `gen_ai.usage.*` / `gen_ai.tool.*` / `gen_ai.response.time_to_first_token` 等）外加 `langfuse.session.id`；采集正文时放入输入输出消息、系统提示、工具定义、工具参数与结果（超过 `content_max_chars` 的值换成 `{"truncated": true, …}`）；OTLP/HTTP protobuf，`BatchSpanProcessor`，Langfuse 主机或 `pk-lf-` / `sk-lf-` 密钥自动补 `/api/public/otel`，Basic 认证，可选 gzip；Secret Key 存凭据库 `OTEL_SECRET_KEY`；`/api/otel/status`、`PUT /api/otel/settings`（写 profile 补丁并就地重启管线，无需重启 harness）、`POST /api/otel/test`（连通性、900 KB 大载荷、GenAI 形状三组测试，Langfuse 时再查询 trace 是否入库）、`POST /api/otel/verify`（最近 8 条 trace）；设置 →「可观测」 |
| `pyharness-subscriptions` | `subscriptions` | `subscriptions` | AI 订阅（对齐 dsh-subscriptions）：Codex（OpenAI）、ChatGPT、Google Antigravity、Grok（xAI）四个提供方；本机回环 OAuth（PKCE S256、state / nonce、端口占用时手动粘贴回调 URL、超时与取消）；会话存 `<profile data>/toolkit/subscriptions/auth.json`（0600），令牌管理器提前 5 分钟刷新、并发共享一次刷新、永久性错误时删除账号；模型目录（Codex 目录接口 + npm 查 client 版本、ChatGPT `/v1/models`、Antigravity 两个 origin 合并、Grok 两个接口合并）缓存 5 分钟并落盘；注册 `ctx.llm` 提供方类型 `subscription`，按账号把可见模型发布成路由 `codex` / `chatgpt` / `antigravity` / `grok`（Responses 协议与 Antigravity `v1internal` 的流式翻译：文本、推理、工具调用、用量）；工具 `codex_web_search`、`codex_image_generate`、`antigravity_web_search`、`antigravity_image_generate`、`grok_x_search`、`grok_image_generate`、`grok_video_generate`，开关存 `provider-settings.json`（搜索类立即生效，生成类按会话创建时刻），生成的媒体放 `images/` / `videos/` 并由 `/api/subscriptions/media/{name}` 提供预览；`/api/subscriptions/*` 路由；左侧栏「AI 订阅」全页 |
| `pyharness-bundle-toolkit` | — | — | `toolkit` bundle：工具箱各模块（memory、rdb、s3、config-center、otel、subscriptions）；`builtin: true`，每个 profile 必含、不可关闭、不可卸载；左侧栏入口可在设置 → 通用里隐藏 |

条目 id 与配置：`packages/bundle-base/src/pyharness_bundle_base/bundle.yaml`。

可选 bundle：bundle 定义里 `optional: true` 的 bundle 不必写进 profile 的 `bundles` 列表就会生效（排在显式列表之后），profile 清单的 `disabled` 列表把它关掉；插件页与 `PUT /plugins/bundles/{name}` 对这类 bundle 允许开关，不允许卸载。内置 bundle（`base`）仍然只读。

内置 bundle：bundle 定义里 `builtin: true` 的 bundle（`toolkit`）随环境安装、每个 profile 必含（排在显式列表之后、可选 bundle 之前），`set_bundle_enabled(…, False)` 抛 `ConfigError`，插件页与 API 返回 409；要少看一个模块就隐藏它的左侧栏入口。

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
  name: pyharness-checkpoint-postgres
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

安装来源有两种：本地 bundle 目录（`pyh plugin install ./my-bundle`，Web 界面可用系统对话框选目录），或 PyPI 包（`pyh plugin install pyh-example==0.1.0`，`--index-url` 指定其他索引）。两种都装进 profile 的 `site/`，先预检再重启；包必须声明 `pyharness.bundles` 入口点，否则拒绝并回滚。

| 部分 | 内容 |
|---|---|
| `pyproject.toml` | entry point `pyharness.plugins`（代码）、`pyharness.bundles`（bundle 文件） |
| `bundle.yaml` | `title`、`description`、`patch`；`after` / `before` / `parent` 决定条目在配置树中的位置 |

```yaml
title: Audit log
description: Tool-call JSONL log, tool denylist, GET /audit.
patch:
  - id: audit
    name: pyharness-audit
    after: tools
    config:
      path: ${data_dir}/audit.jsonl
      deny: []
```

示例：[`examples/pyharness-audit`](../examples/pyharness-audit)。

```bash
uv run pyh plugin install examples/pyharness-audit
```
