# pyharness-gateway

本地 LLM API 网关：`ctx.llm` 的模型路由，以 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 三种协议在独立监听器上提供；API key；逐请求用量记账。

| 项 | 值 |
|---|---|
| 条目 | `gateway`（`toolkit` bundle） |
| 服务 | `GatewayService`，`ctx.gateway` |
| 注入 | `llm`、`http`、`webui` |
| 路由前缀 | `/api/gateway`（管理路由）；`/v1`（网关监听器） |
| 数据根 | `<profile data>/toolkit/gateway/` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `config.py` | `Config` |
| `config.toml` | 监听默认值、上限、线路层的表；每个模块一张表，模块以 `package_toml(__file__)` 读取自己的表 |
| `settings.py`、`keys.py`、`usage.py` | 三个存储 |
| `models.py` | `ModelCatalog`：模型 id 与别名解析 |
| `images.py` | `ImageResolver` |
| `drafts.py` | `ParsedRequest`、`Generation`、`GatewayError`、字段读取器 |
| `chunks.py` | 流词汇、`normalize()`、`BlockAssembler` |
| `openai_chat.py`、`openai_responses.py`、`anthropic_messages.py` | 各一种协议的解析与编码 |
| `backend.py` | `LangChainBackend`：一个请求 → 一条路由上的一次 `astream` |
| `server.py` | 网关应用 |
| `listener.py` | `Listener`：网关应用的 uvicorn 服务器 |
| `routes.py` | 管理路由 |
| `service.py` | `GatewayService`：三个存储、网关应用、监听器、管理路由 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `status()` | 设置、监听状态（`listening`、`listenError`）、模型列表、key 列表 |
| `save_settings()` | 保存完整的设置对象，重启监听器 |
| `settings` | `SettingsStore`：`enabled`、`host`、`port`、`aliases`、`pricing` |
| `keys` | `KeyStore`：创建、更新、删除、显示、校验 |
| `usage` | `UsageStore`：请求账本及其区间汇总 |
| `app` | 网关 ASGI 应用 |

| 时机 | 行为 |
|---|---|
| `app/serve` | 监听器绑定 |
| 绑定失败 | 记入 `status()`；不使启动失败 |

| 配置 | 含义 | 默认 |
|---|---|---|
| `listen` | 设置文件存在之前的监听器初始状态 | 开 |
| `host`、`port` | 监听器初始地址 | `127.0.0.1:8766` |
| `data_dir` | 三个数据文件的目录 | `<profile data>/toolkit/gateway` |
| `max_body_bytes` | 请求体上限 | 32 MiB |

| 数据文件 | 内容 |
|---|---|
| `settings.json` | 监听字段在页面上编辑；`aliases` 与 `pricing` 在文件里编辑 |
| `keys.json` | 每个 key 的完整值，权限 0600；启动时没有任何 key 则生成名为 `default` 的 key |
| `usage.sqlite` | 每个通过鉴权的协议请求一行；超过 400 天的行被删除 |

## 网关应用（`server.py`）

内容：key 鉴权、三个协议端点、模型列表、流式转发、每个通过鉴权的协议请求的账本记录。

| 路由 | 行为 |
|---|---|
| `OPTIONS *` | 204，带 CORS 头 |
| `GET /v1/models` | 该 key 可用的模型，OpenAI 列表；请求带 `anthropic-version` 或 `x-api-key` 时为 Anthropic 形状 |
| `POST /v1/chat/completions` | OpenAI Chat Completions；`stream`、`stream_options.include_usage` |
| `POST /v1/responses` | OpenAI Responses；`stream`，事件带 `sequence_number` |
| `POST /v1/messages` | Anthropic Messages；`stream` |

| 请求要素 | 规则 |
|---|---|
| key | 每个请求携带：`Authorization: Bearer <key>` 或 `x-api-key: <key>` |
| 模型 id | `ctx.llm` 的 `route:model` |
| 请求里的模型名 | 先经 `aliases` 解析；没有默认模型 |
| 图片输入 | `data:` URL、`http(s)` URL；PNG、JPEG、WebP、GIF；以 `data:` URL 到达模型 |

| 失败 | 状态 |
|---|---|
| key 缺失或无效 | 401 |
| key 不允许使用该模型 | 403 |
| 请求畸形或不受支持 | 400 |
| 解析不出模型 | 404 |
| 请求体超过 `max_body_bytes` | 413 |
| 路由失败 | provider 的状态码（4xx 或 5xx）；否则 502 |
| 客户端断开 | 模型请求被取消；账本记 499 |
| 流开始之后的失败 | 以该端点协议的错误帧送达，随后流结束 |

## 模型目录（`models.py`）

内容：每条路由的每个模型，记作 `provider:model`；别名解析。

| 名称 | 契约 |
|---|---|
| `list()` | 各路由提供的每个模型：`{id, provider, providerName, model, name}` |
| `resolve()` | 请求的模型名 → `Target`：先查别名，再按已知路由的 `provider:model` id |
| `ModelResolutionError` | 请求未给出模型名，或给出的名称属于未知路由 |

## 请求模型（`drafts.py`）

流向：每种入站协议解析为 `ParsedRequest` → 服务器解析模型、加载图片 → `materialize()` 得到由 LangChain 消息组成的 `Generation`。

| 名称 | 契约 |
|---|---|
| `GatewayError` | 请求级失败：HTTP 状态、错误码、出错的参数 |
| `ParsedRequest` | 模型名、流标志、system 文本、草稿消息、工具、采样参数 |
| `materialize()` | `ParsedRequest` + `Target` → `Generation`；图片经解析器 |
| `optional_*()` | 请求字段的带类型读取器；类型错误 → `GatewayError` 400 |

| 草稿 block | 字段 |
|---|---|
| `text` | `text` |
| `tool-call` | `id`、`name`、`arguments`（JSON 文本） |
| `pending-image` | `source`：`{kind: "url", url}` 或 `{kind: "base64", media_type, data}` |

| 草稿消息 | 字段 |
|---|---|
| `user` | `content` |
| `assistant` | `content` |
| `tool` | `call_id`、`content`、`is_error` |

## 图片（`images.py`）

| 名称 | 契约 |
|---|---|
| `ImageResolver` | `await resolver(image)` → `data:` URL；任何拒绝 → `GatewayError` 400 |
| `sniff_media_type` | 由起始字节得出媒体类型；用于应答没有可用 content type 的情况 |

| 项 | 规则 |
|---|---|
| 输入 | base64 载荷、远程 URL |
| 类型 | PNG、JPEG、WebP、GIF |
| 大小 | 至多 `MAX_IMAGE_BYTES` |
| 远程 URL | 以 `http` 或 `https` 获取 |

## 模型侧（`backend.py`）

| 名称 | 契约 |
|---|---|
| `LangChainBackend` | 一个 `Generation` → `ctx.llm` 某条路由上的一次 LangChain `astream`；`stream(generation)` 产出 `chunks.py` 的 chunk |
| `UpstreamError` | 路由失败：provider 的状态码（4xx 或 5xx）；否则 502 |

| 请求 | 模型实例 |
|---|---|
| 带 `temperature`、`max_tokens` 或 `reasoning_effort` | 自建实例：`ctx.llm.build` |
| 三者都不带 | 缓存实例：`ctx.llm.resolve` |
| `reasoning_effort` | 只到达 `REASONING_EFFORT_TYPES` 列出的路由类型 |

## 流词汇（`chunks.py`）

内容：LangChain 消息流 → 协议编码器消费的 block chunk。

| chunk | 字段 |
|---|---|
| `block-start` | `index`、`block_type`（`text`、`reasoning`、`tool-call`） |
| `text-delta` | `index`、`text` |
| `reasoning-delta` | `index`、`text` |
| `tool-call-delta` | `index`、`id`、`arguments_delta`；首个 delta 带 `name` |
| `block-end` | `index` |
| `usage` | `usage`：token 计数器 |
| `finish` | `reason`：`{kind}`，取 `stop`、`tool-calls`、`max-tokens`；`error` 另带 `failure` |

| 名称 | 契约 |
|---|---|
| `normalize()` | 一次 LangChain `astream` 的 chunk；同一时刻只开着一个 text 或 reasoning block；tool call 开到 finish |
| `BlockAssembler` | 把 chunk 收集为完成的 block、usage、finish reason |
| `full_usage()` | 每个计数器都在的 usage |
| `finish_failure()` | `error`、`aborted` 的 finish → `{code, message, status}`；正常 finish → `None` |

| 来源 | 读取 |
|---|---|
| reasoning 文本 | `additional_kwargs["reasoning_content"]`；`reasoning` / `thinking` content block |
| 没有 `tool_call_chunks` 的消息（不流式的模型） | 其 `tool_calls` 整体计入 |

## 协议模块

| | `openai_chat.py` | `openai_responses.py` | `anthropic_messages.py` |
|---|---|---|---|
| 协议 | OpenAI Chat Completions | OpenAI Responses | Anthropic Messages |
| `parse_request()` | body → `ParsedRequest`；畸形或不受支持的请求 → `GatewayError` 400 | body → `ParsedRequest`；`reasoning` 输入项被丢弃 | body → `ParsedRequest`；此前轮次的 `thinking` block 被丢弃 |
| 流编码器 | `ChatStreamEncoder`：每个 chunk 的 SSE 帧（`chat.completion.chunk`）；请求了 usage 时，usage 在最后一个不含 choices 的 chunk 上 | `ResponsesStreamEncoder`：语义事件，以 `sequence_number` 编号；每个 block 一个 output item | `AnthropicStreamEncoder`：内容 block 事件流，`message_start` … `message_stop`；`tool_use` block 在它的首个 delta 上打开 |
| 完整对象 | `completion()`：`chat.completion` | `completion()`：`response` | `message()`：`message` |
| `error_body()` | `{"error": {message, type, code, param}}` | `{"error": {type, code, message, param}}` | `{"type": "error", "error": {type, message}}` |

## 设置（`settings.py`）

| 名称 | 契约 |
|---|---|
| `normalize()` | 完整、已校验的设置对象；未知字段丢弃 |
| `SettingsStore` | 绑定一个文件的设置；读取失败回落到默认值；写入原子，权限 0600 |
| `is_model_id()` | `provider:model` 形状检查；key 的模型白名单共用 |

| 设置字段 | 含义 |
|---|---|
| `enabled`、`host`、`port` | 监听器 |
| `aliases` | 请求里的模型名 → 网关模型 id |
| `pricing` | 网关模型 id → `{input, output}`：每一百万 token 的价格 |

## API key（`keys.py`）

| 名称 | 契约 |
|---|---|
| `KeyStore` | 绑定一个文件的 key；每次变更原子地重写文件 |
| `verify()` | 出示的 key 与每个已存 key 做常量时间比较；匹配且启用的 key 通过 |
| `touch()` | 记录 `lastUsedAt`；每个 key 每分钟至多写一次 |
| `presented_key()` | 请求的 key：`Authorization: Bearer <key>` 或 `x-api-key: <key>` |

| 项 | 内容 |
|---|---|
| 文件 | JSON，权限 0600，保存每个 key 的完整值；页面可显示、复制 |
| key 视图 | `id`、`name`、`prefix`、`enabled`、`models`、`createdAt`、`lastUsedAt` |
| `models` | 允许的网关模型 id；`None` 允许所有模型 |
| `createdAt`、`lastUsedAt` | epoch 毫秒 |

## 用量账本（`usage.py`）

内容：SQLite 中的逐请求账本；按模型、按 key 的区间聚合。

| 名称 | 契约 |
|---|---|
| `UsageStore` | 绑定一个文件的账本；首次使用时打开；超过保留期的行在插入时删除 |
| `record()` | 一个结束的网关请求 |
| `summary()` | 整个区间的 facet；过滤后部分的合计、分组、最新的行 |
| `parse_filter()` | 由查询参数得到行过滤器；空值与未知值忽略 |
| `range_start()` | `today`（本地午夜）、`7d`、`30d` 的起点，epoch 毫秒 |

| 费用 | 规则 |
|---|---|
| 值 | 模型有价格的那些行之和 |
| 组内没有任何行有价格 | `None` |

## 监听器（`listener.py`）

内容：网关应用自己的 uvicorn 服务器；设置变更时重启。

| 成员 | 契约 |
|---|---|
| `apply()` | 停掉运行中的服务器；`enabled` 时在 `host:port` 上监听；同一时刻只有一次 apply |
| `close()` | 停掉服务器 |
| `listening` | 已绑定 socket 的 `{"host", "port"}`，或 `None` |
| `error` | 上一次 `apply` 无法监听的原因，或 `None` |

绑定失败：记入 `error` 并写日志；不抛出。

## 管理路由（`routes.py`）

前缀 `/api/gateway`；供 API 网关页使用。

| 请求 | 应答 |
|---|---|
| `GET status` | 设置、监听状态、模型列表、key 列表 |
| `PUT settings` | 保存完整的设置对象，重启监听器；返回 status |
| `GET keys` | key 列表 |
| `GET keys?id=` | 一个 key 的完整值 |
| `POST keys` `{name, models}` | `{key, record}`：新 key 的完整值 |
| `PATCH keys` `{id, name?, enabled?, models?}` | `{record}` |
| `DELETE keys?id=` | 剩余的 key |
| `GET usage?range=&key=&model=&protocol=&outcome=` | 区间的 facet；过滤后的合计、分组、最新的行 |

| 失败 | 状态 |
|---|---|
| 设置或 key 非法 | 400 |
| key id 未知 | 404 |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「API 网关」入口 | 打开 API 网关页 |
| API 网关页 | 监听状态与设置；API key（provider → 模型的白名单选择器）；用量过滤器、指标卡片、请求明细表 |
