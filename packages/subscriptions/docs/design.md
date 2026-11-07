# pyharness-subscriptions

把 Codex（OpenAI）、ChatGPT、Google Antigravity、Grok（xAI）的订阅账号经 OAuth 登录后，作为 `ctx.llm` 的模型路由（model route）与工具提供，并提供「AI 订阅」页面。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__.py` | 包契约文档字符串；导出 `Config`、`SubscriptionsService` |
| `service.py` | `SubscriptionsService`：生命周期、四个 Provider 的构造、`subscription` 路由类型工厂、工具注册与注销、状态汇总、工具用辅助方法 |
| `catalog.py` | 按提供方合并各账号的模型目录（`provider_catalog`、`cached_catalog`）并据此重写 `ctx.llm` 的四条路由（`rebuild_routes`）；`ROUTE_TYPE` |
| `routes.py` | `/api/subscriptions` 下的 HTTP 路由（`build_router`） |
| `providers.py` | Provider 基类：登录流程接线、令牌管理器、目录与用量缓存、`DiscoveredModel` |
| `store.py` | 本地状态：`AuthStore`、`ProviderSettings`、`ModelDefaults`、`CatalogCache`、`MediaStore`；`PROVIDERS`、`PROVIDER_TOOLS` |
| `oauth.py` | OAuth 回环（loopback）流程：每次登录一个临时 HTTP 服务（PKCE S256、state、nonce）、手动回调输入、超时与取消 |
| `common.py` | 共享件：错误码、HTTP 错误映射、SSE 解析、JWT claims、令牌管理器（共享进行中的刷新、永久错误判定）、请求归因 |
| `responses.py` | OpenAI Responses 线格式（Codex、ChatGPT、Grok 共用）：LangChain 消息 → `input`、工具定义、SSE → `AIMessageChunk` |
| `antigravity_wire.py` | Google Antigravity（Cloud Code Assist `v1internal`）线格式：contents / parts、Gemini 与 Claude / gpt-oss 的工具 schema、thinking 配置、SSE 翻译 |
| `media.py` | 生成媒体：图片 / 视频保存到数据目录并向模型描述；搜索结果格式化与来源去重 |
| `codex.py` | `CodexProvider`：OAuth 登录、模型目录、用量、对话、客户端版本 |
| `chatgpt.py` | `ChatGPTProvider`：动态客户端注册、id_token 对 JWKS 校验、经 `/v1/responses` 对话 |
| `antigravity.py` | `AntigravityProvider`：Google OAuth、project 发现、双来源目录、配额汇总、流式对话 |
| `grok.py` | `GrokProvider`：OIDC 发现的 OAuth、`api.x.ai` 与 CLI 代理的目录、计费用量、Responses 对话 |
| `codex_tools.py` | `codex_web_search`、`codex_image_generate` |
| `antigravity_tools.py` | `antigravity_web_search`、`antigravity_image_generate` |
| `grok_tools.py` | `grok_x_search`、`grok_image_generate`、`grok_video_generate` |
| `client.js` | 浏览器模块：侧栏「AI 订阅」入口及其页面（账号、模型、工具、用量） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `SubscriptionsService` | `Service` 子类 | 服务键 `subscriptions`；entry point `pyharness-subscriptions` |
| `Config` | pydantic 模型 | 服务配置 |

## 服务

| 项 | 值 |
|---|---|
| 服务键 | `subscriptions` |
| 注入 | `llm`、`tools`、`http`、`webui` |
| `Config.codexClientVersion` | `None`；固定随目录请求发送的 Codex 客户端版本 |
| `Config.antigravity` | `{}`；`clientId`、`clientSecret`、`baseURL`、`userAgent`、`projectId`、`onboard`、`maxTokens` |
| `Config.models` | `[]`；静态 Codex 目录，非空时关闭发现 |
| `Config.chatgpt` | `{}`；含 `models` 静态目录 |
| `Config.grok` | `{}`；含 `models` 静态目录，非空时关闭发现 |
| `Config.stream_idle_timeout` | `300.0`；流无数据多少秒后失败 |
| `start()` | 建数据目录与各 store；构造四个 Provider；注册路由类型 `subscription`、HTTP 路由、`client.js`；监听 `agent/turn-start`；用缓存目录重建模型路由并注册工具；1 秒后后台发现目录 |
| `stop()` | 注销全部工具；关闭 HTTP 客户端 |

## 事件 / 工具 / 路由 / 提示段

### 事件

| 事件 | 角色 | 作用 |
|---|---|---|
| `agent/turn-start` | 监听 | 记录每个会话首轮的创建时间（毫秒），供 `tool_enabled(at_creation=True)` 取会话创建时的开关 |

### LLM 路由类型

| 项 | 值 |
|---|---|
| 类型 | `subscription` |
| 路由 | `codex`、`chatgpt`、`antigravity`、`grok`；仅在该提供方至少有一个账号时存在 |
| 路由 options | `provider`；模型级 `reasoning_effort`（来自 `ModelDefaults`） |
| 工厂 options | `provider`、`account`、`reasoning_effort`、`max_tokens`、`temperature`、`fast_tier` |
| 重建时机 | 启动（缓存目录）、后台发现、登录 / 注销、偏好写入、默认强度写入、`refresh` |

### 工具

全部以 `tags=("subscriptions", "<provider>")` 注册，不传 approval；仅当提供方有账号且 `PROVIDER_TOOLS[provider]` 非空时注册，注销最后一个账号时整体注销。

| 工具 | 提供方 | 开关（`ProviderSettings.tools`） | 开关取值时刻 |
|---|---|---|---|
| `codex_web_search` | codex | `web_search` | 调用时 |
| `codex_image_generate` | codex | `image_generate` | 会话创建时 |
| `antigravity_web_search` | antigravity | `web_search` | 调用时 |
| `antigravity_image_generate` | antigravity | `image_generate` | 会话创建时 |
| `grok_x_search` | grok | `x_search` | 调用时 |
| `grok_image_generate` | grok | `image_generate` | 会话创建时 |
| `grok_video_generate` | grok | `video_generate` | 会话创建时 |

### HTTP 路由（前缀 `/api/subscriptions`，tag `pyharness-subscriptions`）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/status` | 各提供方状态；Codex 附 `clientVersion` |
| POST | `/login` | 启动提供方的 OAuth 流程；另一登录进行中时 409 |
| POST | `/manual` | 把粘贴的回调 URL / 授权码交给进行中的流程 |
| POST | `/cancel` | 取消进行中的流程 |
| POST | `/logout` | 移除一个账号；重建路由与工具 |
| POST | `/default` | 设置提供方的默认账号；未知账号 404 |
| POST | `/usage` | 一个账号的缓存用量；`force` 刷新；失败 502 |
| GET | `/provider-settings` | 目录（`provider`、`force`）；`force` 清缓存并重新发现，Codex 同时刷新客户端版本 |
| PUT | `/provider-settings` | 写偏好；重建路由与工具；非法值 400 |
| POST | `/model-default` | 写一个模型的默认推理强度；模型不提供该强度时 400 |
| POST | `/refresh` | 重新发现全部目录；重建路由与工具 |
| GET | `/media/{name}` | 工具保存的图片（png / jpg / webp / gif）或视频（mp4）；`cache-control: no-store` |

### Web UI 槽位

| 槽位 | 键 | 内容 |
|---|---|---|
| `sidebar.panellist` | `subscriptions` | 侧栏「AI 订阅」入口，order 60 |
| `main` | `subscriptions` | 订阅页面：账号、模型、工具、用量 |

## 数据

目录 `<profile data>/toolkit/subscriptions/`（无 profile 时 `~/.pyharness/data/toolkit/subscriptions/`）；每次写入原子、权限 0600。

| 文件 / 目录 | 所有者 | 形状 |
|---|---|---|
| `auth.json` | `AuthStore` | `{"<provider>": {"default": key, "accounts": {key: session}}}` |
| `provider-settings.json` | `ProviderSettings` | `{"providers": {"<provider>": {"visibleModels"?, "contextWindows", "tools", "accounts"}}, "toolHistory": []}` |
| `models.json` | `CatalogCache` | `{"<provider>": {"at": ms, "models": [...]}, "accounts": {"<provider>": {key: {"at", "models"}}}}` |
| `model-defaults.json` | `ModelDefaults` | `{"<provider>": {"<model>": effort}}` |
| `images/` | `MediaStore` | `image-<stamp>-<rand>-<index>.<ext>` |
| `videos/` | `MediaStore` | `video-<stamp>-<rand>.mp4` |

登录凭证只存于 `auth.json`，不写入 profile 的凭证库；本包不定义凭证引用名。
