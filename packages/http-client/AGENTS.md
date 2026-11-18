# pyxis-harness-http-client

HTTP API 请求工具：注入鉴权的 API 目标、已存请求、页面与 agent 共用的请求历史、边到达边读取的事件流。

| 项 | 值 |
|---|---|
| 条目 | `http-client`（`toolkit` bundle） |
| 服务 | `HttpClientService`，`ctx.httpClient` |
| 注入 | `tools`、`prompt`、`http`、`webui` |
| 路由前缀 | `/api/http-client` |
| 数据根 | `<profile data>/toolkit/http-client/` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `config.py` | `Config` |
| `config.toml` | 上限、默认值、线路层的表；每个模块一张表，模块以 `package_toml(__file__)` 读取自己的表 |
| `prompts.toml` | 模型可见的文本；以 `pyharness.package_prompts(__file__)` 读取 |
| `protocol.py` | 线路常量、`join_url`、`substitute`、`SseParser` |
| `store.py` | 三个存储及其记录的校验 |
| `engine.py` | `HttpEngine`：主机策略、鉴权、重定向、正文上限、事件流、掩码 |
| `tools.py` | `http_*` 工具 |
| `routes.py` | 管理路由 |
| `service.py` | `HttpClientService`：三个存储、引擎、agent 工具开关、管理路由 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `store` | `TargetStore`：目标（含密钥）与开关 `agentTools`、`historyLimit` |
| `requests` | `RequestStore`：每个目标及 `direct` 作用域的已存请求 |
| `history` | `HistoryStore`：记录下来的交换，最新在前 |
| `engine` | `HttpEngine`：`send(ref, request, options)`、`test(ref)` |
| `sync()` | `agentTools` 开启期间注册 `http_*` 工具与提示词段 |

| 配置 | 含义 | 默认 |
|---|---|---|
| `data_dir` | 三个数据文件的目录 | `<profile data>/toolkit/http-client` |

| 数据文件 | 内容 |
|---|---|
| `targets.json` | 目标与开关，权限 0600；鉴权密钥为明文 |
| `requests.json` | 已存请求，每个目标至多 500 条；请求自带的鉴权为明文 |
| `history.jsonl` | 交换，默认保留 200 条（`historyLimit` 10–1 000）；正文截到 32 KiB |

## 目标

| 字段 | 含义 |
|---|---|
| `baseUrl` | http(s) scheme、主机、可选的路径前缀；请求路径接在其下 |
| `name` | 默认为主机名；agent 以它指代目标 |
| `auth` | `none`、`bearer`、`basic`、`header`、`query`；密钥留在存储里 |
| `headers` | 每个请求都发送；同名的请求头覆盖它 |
| `variables` | `{{name}}`，在路径、查询、请求头、正文中替换；不是密钥 |
| `allowedHosts` | 基础主机之外，绝对 URL 或重定向可以到达的主机；`*.example.com` |
| `allowMutations` | agent 可用 POST / PUT / PATCH / DELETE，每次调用带 `confirm=true` |
| `allowPrivate` | 请求可以到达 loopback、link-local、私有地址 |
| `timeoutMs` | 1 000–120 000，覆盖重定向与正文；默认 30 000 |

## `direct` 作用域

没有目标的请求。

| 项 | 规则 |
|---|---|
| 路径 | 完整 URL |
| 主机 | 任意，含私有网络 |
| 鉴权 | 不注入 |
| 归属 | 只属于页面；agent 不能发送，也不能列出 |

## 线路契约（`protocol.py`）

存储、引擎、路由、页面共用。

| 名称 | 契约 |
|---|---|
| `substitute()` | `{{name}}` → 变量的值；未知名称保持原样 |
| `join_url()` | 请求路径接在基础 URL 之下，或一个绝对 URL；附加查询 |
| `to_pairs()` | 映射或 pair 列表的 `[name, value]` pair；重复的名称保留 |
| `SseParser` | 增量的 server-sent event 解析器（WHATWG event stream 格式） |
| `parse_sse()` | 一段完整流文本中的每个事件 |

| 对象 | 字段 |
|---|---|
| 目标 | `id`、`name`、`baseUrl`、`auth`、`headers`、`variables`、`allowedHosts`、`allowMutations`、`allowPrivate`、`timeoutMs`、`createdAt`、`updatedAt` |
| 鉴权 | `{type: none}`、`{type: bearer, token}`、`{type: basic, username, password}`、`{type: header, name, value}`、`{type: query, name, value}` |
| 已存请求 | `id`、`targetId`、`name`、`method`、`path`、`query`、`headers`、`auth`、`bodyMode`、`body`、`form`、`createdAt`、`updatedAt` |
| 行 | `key`、`value`、`enabled`：`query`、`headers` 或 `form` 的一项 |
| 请求输入 | `method`、`path`、`query`（映射或 pair）、`headers`、`body`、`requestId`、`auth` |
| 交换 | `id`、`at`、`targetId`、`targetName`、`source`（`panel` / `agent`）、`requestId`、`request`，随后是 `response` 或 `error` |
| 交换的请求 | `method`、`url`（已掩码）、`path`、`query`、`headers`、`sentHeaders`、`body`、`bodyTruncated` |
| 交换的应答 | `status`、`statusText`、`headers`、`contentType`、`bodyBytes`、`body`、`bodyTruncated`、`binary`、`bodyBase64`、`durationMs`、`redirects`、`stream: {ended, times}` |
| 事件 | `event`（空：默认类型 `message`）、`data`、`id`、`retry` |

| 值 | 规则 |
|---|---|
| 时间 | epoch 毫秒 |
| `stream.ended` | `complete`、`cancelled`、`timeout`、`limit` |

## 存储（`store.py`）

| 存储 | 文件 | 内容 | 写入 |
|---|---|---|---|
| `TargetStore` | `targets.json` | 目标（鉴权密钥为明文）与开关 | 原子，权限 0600 |
| `RequestStore` | `requests.json` | 所有目标的已存请求，按创建顺序 | 原子，权限 0600 |
| `HistoryStore` | `history.jsonl` | 每行一个交换，最新在后；压缩到历史上限 | 逐行追加；压缩与清除时原子重写；权限 0600 |

| 规则 | 内容 |
|---|---|
| 密钥 | 留在存储里；`summarize()` 给出类型、非密钥的名称、一个短提示 |
| 目标名：字符 | 首字符为字母或数字；字母、数字、空格、点、连字符、下划线；64 个字符 |
| 目标名：唯一 | 不区分大小写；冲突时加数字后缀 |
| 更新时的鉴权 | 类型不变时，空密钥保留已存的密钥 |
| 请求的鉴权 | 按输入原样保存，含不完整的字段；`usable_request_auth()`：是否可以发送 |
| 无法读取的 `targets.json` | 文件改名为 `.corrupt-<time>`，由空存储取代 |
| 校验失败 | `StoreError` |

## 请求引擎（`engine.py`）

页面或 agent 的一个请求：从组合好的输入到记录下来的交换。

| 步骤 | 行为 |
|---|---|
| 目标 | 按 id 或名称解析；`direct` 只对页面开放 |
| 变量 | `{{name}}` 在路径、查询、请求头、正文中替换 |
| URL | 路径接在基础 URL 之下；绝对 URL 必须在基础主机或某个允许的主机上 |
| 私有地址 | 没有 `allowPrivate` 时拒绝 loopback、link-local、私有地址；主机名先解析 |
| 请求头 | 先固定请求头，再请求的请求头；传输层的请求头丢弃 |
| `content-type` 默认值 | 正文以 `{` 或 `[` 开头：JSON；否则 `text/plain` |
| 鉴权 | 目标的鉴权；页面发送且目标没有鉴权时，请求自带的鉴权生效 |
| 重定向：次数 | 至多五次，每次按允许的主机检查 |
| 重定向：凭据 | origin 变化时丢弃 |
| 重定向：方法 | 303，以及 POST 之后的 301 / 302：改为不带正文的 GET |
| 正文 | 读到上限为止；文本按声明的 charset 解码 |
| 二进制正文 | 省略；页面要求时以 base64 整体返回 |
| 事件流 | `text/event-stream` 逐事件读取；停止、超时、到达上限时，以已到达的内容结束 |
| 超时 | `timeoutMs` 覆盖重定向与正文；页面读取的流，每个 chunk 重新计时 |
| 掩码：对象 | 目标密钥、请求自带的鉴权、写进请求头的凭据，连同它们的 URL 编码形式 |
| 掩码：范围 | 交换的 URL、请求头、正文；替换为 `••••••` |
| 历史 | 记录交换；正文截断，二进制正文丢弃 |

| 失败 | 结果 |
|---|---|
| 策略失败、传输失败 | 交换的 `error` |
| 输入畸形、目标未知 | `PolicyError`；不发送，不记录 |

## 工具（`tools.py`）

`http_*` LangChain 工具；`agentTools` 开启期间注册；每个结果都是给模型的文本。

| 工具 | 契约 |
|---|---|
| `http_targets` | 目标表：名称、基础 URL、鉴权类型、mutation、变量名、额外主机 |
| `http_request` | 经引擎发一个请求；GET / HEAD / OPTIONS 之外的方法需要目标的 mutation 开关与 `confirm=true` |
| `http_history` | 一个目标或所有目标的近期交换；没有目标的请求不列出 |

密钥不进入任何结果：引擎掩码；目标表只带鉴权类型。

## 管理路由（`routes.py`）

前缀 `/api/http-client`；供 HTTP 页使用。

| 请求 | 应答 |
|---|---|
| `GET targets` | `{targets}`：不含密钥的摘要 |
| `POST targets` | `{target}`：创建的目标 |
| `PATCH targets?id=` | `{target}`：更新后的目标 |
| `DELETE targets?id=` | `{ok}`；该目标的已存请求与历史一并删除 |
| `GET requests?target=` | `{requests}`，按创建顺序；`direct`：没有目标的请求 |
| `POST requests` `{targetId, …}` | `{request}`；`targetId` 为目标 id 或 `direct` |
| `PATCH requests?id=` | `{request}`；带 `targetId` 则移动该请求 |
| `DELETE requests?id=` | `{ok}` |
| `GET settings`、`POST settings` | `{settings: {agentTools, historyLimit}}` |
| `POST send` `{id, request}` | `{exchange}`；`id` 为目标 id 或 `direct`（路径为完整 URL） |
| `GET history?target=&limit=` | `{entries}`，最新在前 |
| `DELETE history?id=`、`?target=`、不带参数 | `{removed}` |
| `POST test` `{id}` | `{result: {ok, status, latencyMs, error}}` |

| `POST send` | 契约 |
|---|---|
| `Accept: application/x-ndjson` | 应答每行一个 JSON 对象 |
| 事件流到达期间 | `{"type": "head"}`、`{"type": "event"}` |
| 结束 | `{"type": "done", "exchange"}` 或 `{"type": "error"}` |
| 应答之前关闭连接 | 请求被取消；记录的错误为 `cancelled` |
| 已发送请求的策略失败、传输失败 | `exchange.error` |
| 输入非法 | 400 |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「HTTP」入口 | 打开 HTTP 页 |
| HTTP 页 | 作用域选择器与目标；已存请求与交换历史；带自动保存的请求表单；应答面板；事件流视图 |
