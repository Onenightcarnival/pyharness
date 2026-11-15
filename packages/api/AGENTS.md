# pyharness-api

`ctx.agents` 之上的 REST 与 SSE API：`ctx.http` 的 `/api` 下。

| 项 | 值 |
|---|---|
| 条目 | `api`（`base` bundle） |
| 插件 | `apply`（函数插件） |
| 注入 | `http`、`agents`、`llm` |
| 路由前缀 | `/api` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `plugin.py` | `Config`、路由器组合、`apply` |
| `models.py` | 请求体（pydantic 模型）、图片附件的上限 |
| `routes_harness.py` | health、插件、重启、MCP 设置、高亮 |
| `routes_sessions.py` | 会话、SSE 运行、轮次、变更 |
| `routes_workspaces.py` | 工作区注册表与文件 |
| `routes_settings.py` | agent 默认值、压缩、模型路由与凭据 |
| `references.py` | `@path` 引用 |
| `highlight.py` | Pygments 高亮 |
| `config.toml` | `pyharness_api` 的数据；每个模块一张表；`package_toml(__file__)` 读取 |

## 插件入口（`plugin.py`）

| 路由器 | 路由 |
|---|---|
| `build_router` | harness、会话、工作区路由（一个 `APIRouter`） |
| `build_settings_router` | agent 默认值、压缩、模型路由 |

`apply`：两个路由器都挂到 `ctx.http`。

| 配置 | 含义 |
|---|---|
| `llm_entry` | 模型注册表的条目 id；设置路由持久化的是它的配置 |

## Harness 路由（`routes_harness.py`）

| 方法 | 路径 | 请求 | 应答 | 处理函数 |
|---|---|---|---|---|
| GET | `/health` | | generation、重启状态、模型、工作区 | `health` |
| GET | `/plugins` | | Loader 条目、已安装的 bundle | `plugins` |
| POST | `/plugins/install` | `{"path"}` | 安装一个 bundle 目录；排定重启 | `install_plugin` |
| POST | `/plugins/install` | `{"package", "index_url"?}` | 安装一个 PyPI 包；排定重启 | `install_plugin` |
| PUT | `/plugins/bundles/{name}` | `{"enabled"}` | 启用或停用一个安装在 profile 中的或可选的 bundle | `toggle_bundle` |
| DELETE | `/plugins/bundles/{name}` | | 卸载一个安装在 profile 中的 bundle | `uninstall_plugin` |
| PUT | `/plugins/entries/{id}` | `{"enabled"}` | 启用或停用安装在 profile 中的 bundle 的一个条目 | `toggle_entry` |
| POST | `/restart` | | 运行中的轮次结束后重启（受托管） | `restart_now` |
| GET | `/settings/mcp` | | MCP 服务器（密钥已掩码）与状态 | `get_mcp_settings` |
| PUT | `/settings/mcp` | `{"servers": {name: server}}` | 替换 MCP 服务器列表；排定重启 | `put_mcp_settings` |
| POST | `/highlight` | `{"items": [{code, lang?, filename?}]}` | 每项的 Pygments token span | `highlight_code` |
| GET | `/highlight.css` | | 明、暗主题的 token 颜色 | `highlight_css` |

`/plugins/bundles/{name}`、`/plugins/entries/{id}`：内置的 bundle 或条目 → 409。

## 会话路由（`routes_sessions.py`）

| 方法 | 路径 | 请求 | 应答 | 处理函数 |
|---|---|---|---|---|
| GET | `/sessions` | | 会话列表 | `list_sessions` |
| POST | `/sessions` | `{"title"?, "model"?, "workspace"?, "mode"?, "preset"?}` | 会话 | `create_session` |
| PUT | `/sessions/{id}` | `{"title"}` | 重命名会话 | `rename_session` |
| PUT | `/sessions/{id}/model` | `{"model"}` | 为会话选择 `route:model` | `set_session_model` |
| PUT | `/sessions/{id}/mode` | `{"mode"}` | 权限模式；下一次运行起 | `set_session_mode` |
| PUT | `/sessions/{id}/preset` | `{"preset"}` | agent 预设；下一次运行起 | `set_session_preset` |
| GET | `/sessions/{id}` | | 会话、busy、消息、待处理的审批 | `get_session` |
| GET | `/sessions/{id}/turns` | | 每轮的统计与轨迹记录 | `session_turns` |
| GET | `/sessions/{id}/changes` | | 每轮的变更文件摘要 | `session_changes` |
| GET | `/sessions/{id}/changes/{run}/diff` | `?index=` | 所列的一个文件的 hunk；行已高亮 | `session_changes_diff` |
| POST | `/sessions/{id}/messages` | `{"content", "images"?}` | SSE：运行事件 | `post_message` |
| POST | `/sessions/{id}/approvals` | `{"decisions": [decision]}` | SSE：运行事件 | `post_approvals` |
| POST | `/sessions/{id}/compact` | | SSE：一次手动压缩运行（`compact`、`done`） | `post_compact` |
| POST | `/sessions/{id}/retry` | | SSE：接续失败的上一轮的运行 | `post_retry` |
| POST | `/sessions/{id}/answers` | `{"answers", "interrupt_id"?}` | SSE：恢复后的运行 | `post_answers` |
| POST | `/sessions/{id}/cancel` | | `{"cancelled"}` | `cancel` |
| DELETE | `/sessions/{id}` | | `{"deleted"}` | `delete` |
| GET | `/sessions/{id}/stream` | | SSE：运行中的轮次；空闲时 204 | `attach` |

| 项 | 契约 |
|---|---|
| `/sessions/{id}/messages` 的 `images` | data URL |
| `/sessions/{id}/messages` 的 `@path` | 引用被展开（`references.py`） |
| `/sessions/{id}/answers` | 回答待处理的 `ask_user_question` |
| `decision` | `{"type": "approve"}` 或 `{"type": "reject"}` |
| `_sse` | 运行事件，`text/event-stream`；每个事件一行 `data:` |

| 状态码 | 条件 |
|---|---|
| 404 | 会话不存在 |
| 409 | 有运行中的轮次；审批待处理，或没有待处理的审批 |
| 422 | 向不接受图片输入的模型发送图片 |
| 503 | 重启待执行（`Retry-After: 2`） |

## 工作区路由（`routes_workspaces.py`）

| 方法 | 路径 | 请求 | 应答 | 处理函数 |
|---|---|---|---|---|
| GET | `/workspaces` | | 默认与最近的工作区、选择器种类 | `list_workspaces` |
| POST | `/workspaces/pick` | `{"path"?: prompt}` | 本机的系统文件夹对话框；null = 已取消 | `pick_workspace` |
| POST | `/workspaces` | `{"path"}` | 校验并记住一个工作区 | `add_workspace` |
| PUT | `/workspaces` | `{"path", "name"}` | 工作区的显示名 | `rename_workspace` |
| DELETE | `/workspaces` | `?path=` | 忘记一个工作区 | `forget_workspace` |
| POST | `/workspaces/browse` | `{"path"?}` | 一层目录；供选择器使用 | `browse_workspaces` |
| GET | `/workspaces/files` | `?path=&root=` | 工作区内的目录条目 | `list_files` |
| GET | `/workspaces/search` | `q`、`root`?、`limit`?、`hidden`?、`fuzzy`? | 匹配 `q` 的路径 | `search_files` |
| GET | `/workspaces/file` | `?path=&root=&limit=` | 工作区内一个文件的文本 | `read_file` |
| GET | `/workspaces/file/raw` | `?path=&root=` | 工作区内一个文件的字节（图片） | `read_file_raw` |

## 设置路由（`routes_settings.py`）

| 方法 | 路径 | 请求 | 应答 | 处理函数 |
|---|---|---|---|---|
| GET | `/models` | | 选择器目录：路由、模型、默认值 | `model_directory` |
| GET | `/agent` | | 预设、模式、新会话的默认值 | `agent_options` |
| PUT | `/settings/agent` | `{"default_preset"?, "default_mode"?}` | 新会话的默认值；持久化 | `put_agent_defaults` |
| GET | `/settings/compaction` | | 压缩设置 | `get_compaction_settings` |
| PUT | `/settings/compaction` | `{"auto"?, "threshold_ratio"?, "retain_ratio"?, "default_context_window"?, "summary_model"?}` | 压缩设置；立即生效；持久化 | `put_compaction_settings` |
| GET | `/settings/models` | | 已配置的路由及其凭据状态、目录、`groups`（全部可选模型，含插件发布的路由） | `get_model_settings` |
| PUT | `/settings/models` | `{"default"}` | 新会话的默认模型 | `put_default_model` |
| PUT | `/settings/model-retry` | `{"retry"}` | 没有自有策略的路由的重试策略 | `put_model_retry` |
| PUT | `/settings/models/{route}` | `route settings` | 创建或编辑一条路由；立即生效；route id 属于插件发布的路由 → 409 | `put_route` |
| DELETE | `/settings/models/{route}` | | 删除一条路由及其已存的凭据 | `delete_route` |
| POST | `/settings/models/{route}/discover` | `route settings` | 端点提供的模型 id | `discover_models` |
| POST | `/settings/models/{route}/test` | `route settings` | 用 `model` 做一次短补全 | `test_route` |

### `route settings`

```
{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?, "retry"?, "model"?}
```

| `api_key` | 契约 |
|---|---|
| 有值 | 存入 profile 凭据库；配置中引用它 |
| `""` | 删除已存的值 |
| 缺省 | 保留已存的值 |
| 应答 | 不返回凭据值 |

| 凭据名 | 条件 |
|---|---|
| 路由的 `api_key_env` | 已设置 |
| provider 类型的环境变量名 | 路由 id 等于 provider 类型 |
| `<ROUTE>_API_KEY` | 其余情况 |

已保存的设置：下一次模型请求起生效，无需重启。

## `@path` 引用（`references.py`）

用户消息中的 `@path` 引用：被引用的文件与目录随提示词一起发送。

| 项 | 契约 |
|---|---|
| 记号 | `@path` 或 `@"path with spaces"` |
| 位置 | 文本开头，或空白、开括号、逗号、顿号之后 |
| 指向 | 会话工作区内的文件或目录；`/` 起始，或相对其根 |
| 可解析的文件 | 追加 `<attached-file path=...>` 块：文本，截断 |
| 可解析的目录 | 追加 `<attached-directory path=...>` 列表 |
| `@path` 文本本身 | 留在原处 |
| 无法解析的记号（邮箱地址、handle） | 不处理 |

## 高亮（`highlight.py`）

Web UI 的服务端语法高亮（Pygments）：带 `hl-` class 的 token span，无内联颜色。

| 函数 | 结果 |
|---|---|
| `render(code, lang, filename)` | `{"html": <以 \n 连接的各行>, "lang": 别名或 None}`；没有匹配时 `html` 为空 |
| `lines(code, lang, filename)` | 每个源码行一个 HTML 字符串；span 不跨行 |
| `style_css()` | `.hl`（明）与 `[data-theme="dark"] .hl` 的 token 颜色 |
