# pyharness-api

`ctx.http` 上 `/api` 前缀下的 REST 与 SSE 接口，面向 `ctx.agents`、工作区、插件与模型设置。

## 模块

| 模块 | 职责 |
|---|---|
| `pyharness_api/__init__.py` | 契约文档（路由表、状态码）；导出公开名称 |
| `pyharness_api/plugin.py` | `name`、`inject`、`Config`、路由组合 `build_router`、`apply` |
| `pyharness_api/models.py` | 各路由的请求体（pydantic 模型）与图片附件上限 |
| `pyharness_api/routes_harness.py` | 健康检查、插件安装/启停/卸载、重启、MCP 服务器设置、语法高亮 |
| `pyharness_api/routes_sessions.py` | 会话记录、消息/审批/回答/压缩的 SSE 运行、回合、变更、取消、删除、重连 |
| `pyharness_api/routes_workspaces.py` | 工作区注册表（最近、选择、添加、改名、忘记、浏览）与工作区内文件 |
| `pyharness_api/routes_settings.py` | agent 默认值、压缩设置、模型路由与凭据 |
| `pyharness_api/references.py` | 用户消息中的 `@path` 引用：解析、展开为附件块、工作区搜索 |
| `pyharness_api/highlight.py` | Pygments 服务端高亮：按行的 token span、主题 CSS |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | pydantic 模型 | 插件配置 |
| `apply` | 函数 `(ctx, config)` | 把两个路由器挂到 `ctx.http`，前缀 `config.prefix`，tag `pyharness` |
| `name` | 字符串 | `pyharness-api` |
| `inject` | 列表 | `http`、`agents`、`llm` |

`pyharness_api.references`（`expand`、`search`、`strip_attachments`、`tokens`）与 `pyharness_api.highlight` 以子模块方式供测试与路由使用。

## 服务

| 项 | 值 |
|---|---|
| 形态 | 函数插件（`apply`） |
| name | `pyharness-api` |
| inject | `http`、`agents`、`llm` |
| `prefix` | `/api` |
| `llm_entry` | `llm`；设置页编辑的模型注册表 entry id |
| apply | `build_router(ctx)`（harness + sessions + workspaces）与 `build_settings_router(ctx, llm_entry)` 挂到 `ctx.http` |

## 事件 / 工具 / 路由 / 提示段

### 路由

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/health` | | generation、重启状态、模型、工作区 |
| GET | `/plugins` | | loader 条目、已安装 bundle |
| POST | `/plugins/install` | `{"path"}` 或 `{"package", "index_url"?}` | 安装 bundle 目录或 PyPI 包；受监督时安排重启 |
| PUT | `/plugins/bundles/{name}` | `{"enabled"}` | 启用/停用 profile 安装的或可选 bundle；内建 409 |
| DELETE | `/plugins/bundles/{name}` | | 卸载 profile 安装的 bundle；内建 409 |
| PUT | `/plugins/entries/{id}` | `{"enabled"}` | 启用/停用 profile 安装 bundle 的条目；内建 409 |
| POST | `/restart` | | 运行中的回合结束后重启；未受监督 409 |
| GET | `/sessions` | | 会话列表 |
| POST | `/sessions` | `{"title"?, "model"?, "workspace"?, "mode"?, "preset"?}` | 会话记录 |
| GET | `/sessions/{id}` | | 会话、busy、messages、pending、changes、turns、context_window |
| PUT | `/sessions/{id}` | `{"title"}` | 改名 |
| PUT | `/sessions/{id}/model` | `{"model"}` | 为会话选择 `route:model` |
| PUT | `/sessions/{id}/mode` | `{"mode"}` | 权限模式；下次运行生效 |
| PUT | `/sessions/{id}/preset` | `{"preset"}` | agent 预设；下次运行生效 |
| POST | `/sessions/{id}/messages` | `{"content", "images"?}` | SSE 运行事件；`images` 为 data URL；`@path` 引用展开 |
| POST | `/sessions/{id}/approvals` | `{"decisions": [decision]}` | SSE 运行事件 |
| POST | `/sessions/{id}/compact` | | 手动压缩运行的 SSE（`compact`、`done`） |
| POST | `/sessions/{id}/answers` | `{"answers", "interrupt_id"?}` | 回答待处理的 ask_user_question；恢复运行的 SSE |
| POST | `/sessions/{id}/cancel` | | `{"cancelled"}` |
| DELETE | `/sessions/{id}` | | `{"deleted"}` |
| GET | `/sessions/{id}/stream` | | 运行中回合的 SSE；空闲 204 |
| GET | `/sessions/{id}/turns` | | 每回合统计与轨迹记录 |
| GET | `/sessions/{id}/changes` | | 每回合变更文件摘要 |
| GET | `/sessions/{id}/changes/{run}/diff` | `?index=` | 单个文件的 hunk，行已高亮 |
| GET | `/agent` | | 预设、模式、新会话默认值 |
| PUT | `/settings/agent` | `{"default_preset"?, "default_mode"?}` | 新会话默认值；持久化到 profile patch |
| GET | `/settings/compaction` | | 压缩插件设置 |
| PUT | `/settings/compaction` | `{"auto"?, "threshold_ratio"?, "retain_ratio"?, "default_context_window"?, "summary_model"?}` | 就地生效并持久化 |
| GET | `/workspaces` | | 默认与最近工作区、选择器类型 |
| POST | `/workspaces/pick` | `{"path"?: prompt}` | 本机 OS 目录对话框；取消为 null |
| POST | `/workspaces` | `{"path"}` | 校验并记住工作区 |
| PUT | `/workspaces` | `{"path", "name"}` | 工作区显示名 |
| DELETE | `/workspaces?path=` | | 忘记工作区 |
| POST | `/workspaces/browse` | `{"path"?}` | 选择器用的一层目录 |
| GET | `/workspaces/files` | `?path=&root=` | 工作区内目录条目 |
| GET | `/workspaces/search` | `?q=&root=&limit=` | 匹配 `q` 的工作区路径，供 `@` 引用 |
| GET | `/workspaces/file` | `?path=&root=&limit=` | 工作区内文件文本；二进制标记 `binary` |
| GET | `/workspaces/file/raw` | `?path=&root=` | 工作区内文件字节（图片预览）；上限 20 MB |
| GET | `/settings/mcp` | | MCP 服务器（密文遮蔽）与连接状态 |
| PUT | `/settings/mcp` | `{"servers": {name: server}}` | 替换 MCP 服务器列表；安排重启 |
| POST | `/highlight` | `{"items": [{code, lang?, filename?}]}` | 每项的 Pygments token span |
| GET | `/highlight.css` | | 明暗主题的 token 颜色 |
| GET | `/models` | | 选择器目录：路由、模型、默认 |
| GET | `/settings/models` | | 带凭据状态的路由、目录 |
| PUT | `/settings/models` | `{"default"}` | 新会话默认模型 |
| PUT | `/settings/models/{route}` | route settings | 新建或编辑路由；立即生效 |
| DELETE | `/settings/models/{route}` | | 删除路由及其存储的凭据 |
| POST | `/settings/models/{route}/discover` | route settings | 端点提供的模型 id |
| POST | `/settings/models/{route}/test` | route settings | 用 `model` 做一次短补全 |

| 状态码 | 条件 |
|---|---|
| 404 | 未知会话 |
| 409 | 回合运行中；审批待处理或不存在；内建插件；无 profile |
| 413 | `/workspaces/file/raw` 文件超过 20 MB |
| 422 | 请求体校验失败；向不接受图片的模型发送图片 |
| 503 | 重启待处理（`Retry-After: 2`）；依赖的服务未挂载 |

| 术语 | 值 |
|---|---|
| `decision` | `{"type": "approve"}` 或 `{"type": "reject"}` |
| `route settings` | `{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?, "model"?}` |
| `api_key` | 存入 profile 凭据库 `<ROUTE>_API_KEY`，配置只存引用；`""` 删除；缺省保留；从不返回 |
| 图片 | data URL（png、jpeg、gif、webp）；每条消息至多 8 张，每张至多 8 MB |
| SSE | 每个事件一行 `data: <json>`，`Cache-Control: no-cache` |
