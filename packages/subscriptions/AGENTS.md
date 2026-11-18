# pyxis-harness-subscriptions

AI 订阅作为模型路由与工具：Codex（OpenAI）、ChatGPT、Google Antigravity、Grok（xAI），经各自的 OAuth 流程登录。

| 项 | 值 |
|---|---|
| 条目 | `subscriptions`（`toolkit` bundle） |
| 服务 | `SubscriptionsService`，`ctx.subscriptions` |
| 注入 | `llm`、`tools`、`http`、`webui` |
| 路由前缀 | `/api/subscriptions` |
| 数据根 | `<profile data>/toolkit/subscriptions/` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `SubscriptionsService`：provider、模型路由与工具、AI 订阅页的状态 |
| `routes.py` | AI 订阅页的 HTTP API |
| `providers.py` | provider 基类：登录流程的接线、token 管理器、目录与用量缓存；各 provider 模块继承它 |
| `codex.py` | Codex（OpenAI，ChatGPT 订阅的 Codex 后端）：OAuth 登录、模型目录、用量、聊天、网页搜索、图像生成 |
| `codex_tools.py` | Codex 的工具 |
| `chatgpt.py` | ChatGPT（「Sign in with ChatGPT」，计套餐用量的公共 OpenAI API）：动态客户端注册、按 issuer 的 JWKS 校验 `id_token`、经 `/v1/responses` 聊天，工具命名空间为 `dsh` 风格 |
| `antigravity.py` | Google Antigravity（Cloud Code Assist `v1internal`）：Google OAuth、项目发现、两个 origin 的目录、配额汇总、流式聊天、网页搜索、图像生成 |
| `antigravity_client.py` | Antigravity 客户端签名 |
| `antigravity_tools.py` | Antigravity 的工具 |
| `antigravity_wire.py` | Antigravity 线路格式：LangChain 消息 → contents / parts、Gemini 与 Claude / gpt-oss 模型的工具 schema、按模型的 thinking 配置、SSE 转换 |
| `grok.py` | Grok（xAI）：OIDC 发现的 OAuth、`api.x.ai` 与 CLI 代理的目录、账单用量、Responses 聊天、X 搜索、图像与视频生成 |
| `grok_tools.py` | Grok 的工具 |
| `responses.py` | Codex、ChatGPT、Grok 共用的 OpenAI Responses 线路格式：LangChain 消息 → `input` 条目、工具定义、Responses SSE 事件 → `AIMessageChunk`（文本、推理、工具调用、用量）的流式转换 |
| `catalog.py` | 各 provider 的模型目录，以及由它们发布到 `ctx.llm` 的路由 |
| `oauth.py` | OAuth 回环流程：每次登录尝试一个临时 HTTP 服务器（PKCE S256、state、nonce）；浏览器无法访问 harness 时手动输入回调；超时与取消 |
| `common.py` | 共用部分：错误码、HTTP 错误映射、SSE 解析、JWT claims、token 管理器（刷新共享进行中的调用，识别永久性错误）、请求归属 |
| `store.py` | 数据根下的本地状态 |
| `media.py` | 生成的媒体：图像 / 视频存入数据根，并向模型描述 |
| `config.toml` | provider 端点、OAuth client id 与 scope、线路层标识符 |
| `prompts.toml` | 模型可见文本 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `providers` | `{id: Provider}`：登录、账号、目录、用量、聊天模型、工具；启动时由数据根下的存储（`AuthStore`、`CatalogCache`）构建 |
| `sync_routes()` | `catalog.rebuild_routes`：把发现的模型发布为 `ctx.llm` 路由 `codex` / `chatgpt` / `antigravity` / `grok` |
| `sync_tools()` | 注册每个已登录且有工具的 provider 的工具；登出时撤销 |
| `catalog()` | `catalog.provider_catalog` |
| `status()` | `{"providers": {id: status}}`；Codex 项带 `clientVersion` |
| `tool_enabled()` | 一个 provider 工具的已存偏好；可按会话创建时刻取值 |
| `model_default()` | 一个模型的已存默认推理强度 |
| `media_url()` | 已存媒体文件的 URL：`/api/subscriptions/media/{name}` |

| 配置 | 含义 |
|---|---|
| `codexClientVersion` | 固定随目录请求发送的 Codex 客户端版本 |
| `antigravity` | `clientId`、`clientSecret`、`baseURL`、`userAgent`、`projectId`、`onboard`、`maxTokens` |
| `antigravity.userAgent` | 替换 Antigravity CLI 签名 |
| `models`、`chatgpt.models`、`grok.models` | 静态目录；非空 → 该 provider 不做发现 |
| `stream_idle_timeout` | 四个提供方的聊天模型：流无数据多少秒后以 `TIMEOUT` 失败；大于 0；默认 `300.0` |

## 工具

| 工具 | provider | 内容 |
|---|---|---|
| `codex_web_search` | `codex` | Codex 搜索后端及其命令集 |
| `codex_image_generate` | `codex` | 图像生成 |
| `antigravity_web_search` | `antigravity` | Gemini，Google Search grounding |
| `antigravity_image_generate` | `antigravity` | Gemini 3.1 Flash Image |
| `grok_x_search` | `grok` | 托管的 X 搜索 |
| `grok_image_generate` | `grok` | 图像生成 |
| `grok_video_generate` | `grok` | 视频生成 |

## 模型路由（`catalog.py`）

| 函数 | 契约 |
|---|---|
| `provider_catalog()` | 每个账号发现的模型，合并，带已存的上下文窗口与推理强度 |
| `cached_catalog()` | 同样的行，只取最近一次已知的目录；不访问网络 |
| `rebuild_routes()` | 以 `ctx.llm.publish` 发布 `codex` / `chatgpt` / `antigravity` / `grok` 路由：已登录的 provider 各一条；配置里类型为 `subscription` 的路由从运行中的配置移除 |

| 项 | 规则 |
|---|---|
| 存续 | 只存在于运行期 |
| 来源 | 已存的会话、最近一次已知的目录 |
| 重建时机 | 启动；登出；发现；偏好保存 |

## 路由

| 路径 | 方法 | 作用 |
|---|---|---|
| `status` | GET | 每个 provider：忙碌标志、账号、Codex 客户端版本 |
| `login` | POST | 启动该 provider 的 OAuth 流程；已有登录在进行 → 409 |
| `manual` | POST | 把粘贴的回调 URL / code 交给进行中的流程 |
| `cancel` | POST | 中止进行中的流程 |
| `logout` | POST | 移除一个账号；重建路由与工具 |
| `default` | POST | 选定 provider 的默认账号 |
| `usage` | POST | 一个账号的缓存用量；`force` 刷新 |
| `provider-settings` | GET | 目录；`force` 清除缓存并重新发现 |
| `provider-settings` | PUT | 保存偏好；重建路由与工具 |
| `model-default` | POST | 保存一个模型的默认推理强度 |
| `refresh` | POST | 重新发现全部目录；重建路由与工具 |
| `media/{name}` | GET | provider 工具存下的图像或视频 |

## 存储（`store.py`）

| 数据根下 | 内容 |
|---|---|
| `auth.json` | 账号会话 |
| `provider-settings.json` | provider 偏好 |
| `models.json` | 最近一次已知的模型目录 |
| `model-defaults.json` | 各模型的默认推理强度 |
| 媒体 | 生成的图像、视频 |

JSON 文件的写入：原子，权限 `0600`。

## Antigravity 客户端签名（`antigravity_client.py`）

Cloud Code 后端只服务 Antigravity CLI User-Agent 家族的内容请求。

| 名称 | 契约 |
|---|---|
| `build_user_agent()` | `antigravity/cli/<version> (aidev_client; os_type=…; arch=…; cl=…; …)` |
| `parse_cli_version()` | auto-updater 文本中的第一个 `x.y.z`，否则 `None` |
| `CliVersion` | 使用中的版本；`prime()` 每次启动从 CLI auto-updater 读取一次 stable 版本；读取失败 → 保留固定版本 |

## `config.toml`

| 项 | 规则 |
|---|---|
| 表 | 每个模块一张 |
| 加载 | 各模块用 `package_toml(__file__)` 读取自己的表 |

## `prompts.toml`

| 项 | 规则 |
|---|---|
| 表名 | 使用该文本的模块 |
| 加载 | `pyharness.package_prompts`；每个字符串值去除首尾空白 |
| 占位符 | `string.Template` 语法（`${name}`） |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「AI 订阅」页 | provider、账号登录（手动回调兜底）、模型 / 工具 / 用量标签页 |
| 工具行 | 生成媒体的预览 |
