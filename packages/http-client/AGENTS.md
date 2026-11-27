# pyxis-harness-http-client

HTTP API 请求工具：注入鉴权的 API 目标、密钥变量、已存请求、从应答提取并自动刷新的变量、页面与 agent 共用的请求历史、边到达边读取的事件流、不含密钥的配置导出与导入。

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
| `prompts.toml` | 模型可见的文本；以 `pyxis_harness.package_prompts(__file__)` 读取 |
| `protocol.py` | 线路常量、`join_url`、`substitute`、`request_input_of`、`SseParser` |
| `capture.py` | 提取规则：JSON 路径、取值、有效期 |
| `store.py` | 四个存储及其记录的校验 |
| `engine.py` | `HttpEngine`：主机策略、变量、鉴权、自动刷新、重定向、正文上限、事件流、提取、掩码 |
| `transfer.py` | 导出文档的生成；导入的校验与合并 |
| `tools.py` | `http_*` 工具 |
| `routes.py` | 管理路由 |
| `service.py` | `HttpClientService`：四个存储、引擎、agent 工具开关、管理路由 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `store` | `TargetStore`：目标（含密钥）与开关 `agentTools`、`historyLimit` |
| `requests` | `RequestStore`：每个目标及 `direct` 作用域的已存请求 |
| `values` | `ValueStore`：每个目标及 `direct` 作用域已提取的变量值 |
| `history` | `HistoryStore`：记录下来的交换，最新在前 |
| `engine` | `HttpEngine`：`send(ref, request, options)`、`test(ref)` |
| `sync()` | `agentTools` 开启期间注册 `http_*` 工具与提示词段 |

| 配置 | 含义 | 默认 |
|---|---|---|
| `data_dir` | 四个数据文件的目录 | `<profile data>/toolkit/http-client` |

| 数据文件 | 内容 |
|---|---|
| `targets.json` | 目标与开关，权限 0600；鉴权密钥与密钥变量为明文 |
| `requests.json` | 已存请求，每个目标至多 500 条；请求自带的鉴权为明文 |
| `values.json` | 已提取的变量值，权限 0600；值为明文 |
| `history.jsonl` | 交换，默认保留 200 条（`historyLimit` 10–1 000）；正文截到 32 KiB |

## 目标

| 字段 | 含义 |
|---|---|
| `baseUrl` | http(s) scheme、主机、可选的路径前缀；请求路径接在其下 |
| `name` | 默认为主机名；agent 以它指代目标 |
| `auth` | `none`、`bearer`、`basic`、`header`、`query`；密钥留在存储里；字段值可引用 `{{name}}` |
| `headers` | 每个请求都发送；同名的请求头覆盖它；值可引用 `{{name}}` |
| `variables` | `{{name}}` 的值；不是密钥 |
| `secrets` | 密钥变量：`{{name}}` 的值，留在存储里；名称不与 `variables` 重复 |
| `allowedHosts` | 基础主机之外，绝对 URL 或重定向可以到达的主机；`*.example.com` |
| `allowMutations` | agent 可用 POST / PUT / PATCH / DELETE，每次调用带 `confirm=true` |
| `allowPrivate` | 请求可以到达 loopback、link-local、私有地址 |
| `timeoutMs` | 1 000–120 000，覆盖重定向与正文；默认 30 000 |

| 未填写的密钥 | 规则 |
|---|---|
| 来源 | 导入的目标：文档与存储都没有该密钥的值 |
| 鉴权密钥 | 鉴权摘要带 `missing: true`；发往该目标的请求被拒绝 |
| 密钥变量 | 摘要里的短提示为空；引用它的请求被拒绝 |
| 编辑 | 留空不保留：保存目标时填入值，或移除该密钥变量 |

## 变量

`{{name}}`：一个作用域（一个目标，或 `direct`）内的名称。

| 种类 | 值的来源 | 页面得到 |
|---|---|---|
| 变量 | 目标的 `variables` | 名称与值 |
| 密钥变量 | 目标的 `secrets` | 名称与短提示 |
| 提取的变量 | 已存请求的提取规则，存于 `values.json` | 名称与短提示 |

| 规则 | 内容 |
|---|---|
| 替换位置 | 请求的路径、查询、请求头、正文；目标的固定请求头与鉴权字段；请求自带的鉴权字段 |
| 同名 | 提取的变量优先于变量与密钥变量 |
| 未知名称 | 保持原样 |
| 没有存值的密钥变量 | 引用它的请求被拒绝 |
| 使用者 | 页面的请求与 agent 对该目标的请求 |

## 提取规则（`capture.py`）

已存请求的 `captures`。页面发送该已存请求（请求输入带它的 `requestId`），或宿主把它作为刷新发送，并收到 2xx 应答：宿主从应答读值，写入该请求所在作用域。

| 字段 | 含义 | 默认 |
|---|---|---|
| `name` | 写入的变量名；空：规则不执行 | `""` |
| `source` | `body`：JSON 正文中的路径；`header`：应答头 | `body` |
| `path` | JSON 路径，或应答头名 | `""` |
| `enabled` | 规则是否执行 | `true` |
| `ttlSeconds` | 有效期秒数，至多 31 622 400；0：不过期 | `0` |
| `ttlPath` | 同一应答 JSON 中有效期秒数的路径；优先于 `ttlSeconds` | `""` |
| `refresh` | `off`、`expired`、`rejected`；见「自动刷新」 | `off` |

| 项 | 规则 |
|---|---|
| 条数 | 每个请求至多 20 条 |
| JSON 路径 | `data.token`、`items[0].id`、`$.a["b.c"]`；开头的 `$` 可省略 |
| 取值 | 字符串、数字、布尔值；空值、对象、数组、含换行、超过 16 KiB 的值不提取 |
| 有效期 | `expiresAt` = 提取时间 + 有效期；`ttlPath` 读不到正数：照常提取，不过期，结果带 `warning` |
| 过期 | `expiresAt` 之前 30 s 起；有效期不足 300 s 时，提前其十分之一 |
| 未提取 | 状态不是 2xx、正文不是 JSON、正文被截断、路径或应答头不存在、应答是事件流：结果带 `error`，已存的值不变 |
| 不执行 | agent 自己的请求；`requestId` 不属于该作用域的请求 |
| 更新 | 再次发送该已存请求，或自动刷新 |

## 自动刷新

提取规则的 `refresh`：宿主自行发送该规则所在的已存请求（来源请求）。

| `refresh` | 行为 |
|---|---|
| `off` | 不刷新；过期的值照常替换 |
| `expired` | 同一作用域的请求引用该变量，且值缺失或过期：发送前刷新 |
| `rejected` | 同 `expired`；引用该变量的请求收到 401：刷新一次，重发一次 |

| 项 | 规则 |
|---|---|
| 引用位置 | 请求的路径、查询、请求头、正文；随请求发送的固定请求头与鉴权 |
| 顺序 | 先发送来源请求并提取，再发送原请求；一个来源请求提供多个所需变量时只发送一次 |
| 来源请求 | 按存储的表单发送（`request_input_of()`），带它自带的鉴权；不带引用了它所提取变量的目标鉴权与固定请求头 |
| 自身 | 发送来源请求本身不触发对它的刷新 |
| 401 | 事件流应答不重发；为本次请求刷新过的来源请求不再刷新；刷新失败时结果是该 401 应答，`refreshed` 列出失败 |
| agent | agent 的请求同样触发；刷新发送的是用户保存的表单，不受 `allowMutations` 与 `confirm` 约束 |
| 并发 | 同一来源请求的刷新同时只有一次，其余请求等待其结果 |
| 链 | 来源请求引用的变量同样按需刷新；一条链至多 3 次刷新；互相依赖是错误 |
| 失败 | 来源请求失败或没有提取到变量：原请求不发送，`error` 写明来源请求与原因；不重试，下一次请求重新尝试 |
| 取消 | 取消原请求即停止等待；已发出的刷新照常完成并保存提取到的值 |
| 记录 | 刷新是一条独立的交换，`source` 为触发它的一方，带 `refreshOf`；原请求的交换带 `refreshed` |
| 同一变量的多个来源 | 发送该变量当前值的来源请求；没有值时取创建最早的一条 |

| 令牌类 API | 配置 |
|---|---|
| 目标的 `secrets` | `client_secret` |
| 已存请求 | 调用换取令牌的接口；正文引用 `{{client_secret}}` |
| 该请求的提取规则 | `name: access_token`、`path: access_token`、`ttlPath: expires_in`、`refresh: expired` |
| 目标的 `auth` | `{type: bearer, token: "{{access_token}}"}` |

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
| `referenced_variables()` | 若干文本中以 `{{name}}` 引用的名称 |
| `request_input_of()` | 已存请求的表单 → 请求输入：启用且有名称的行、所选模式的正文及其默认 `content-type` |
| `saved_request_title()` | 已存请求的标题：名称，否则路径，否则方法 |
| `blank_capture()` | 各字段取默认值的提取规则 |
| `join_url()` | 请求路径接在基础 URL 之下，或一个绝对 URL；附加查询 |
| `to_pairs()` | 映射或 pair 列表的 `[name, value]` pair；重复的名称保留 |
| `SseParser` | 增量的 server-sent event 解析器（WHATWG event stream 格式） |
| `parse_sse()` | 一段完整流文本中的每个事件 |

| 对象 | 字段 |
|---|---|
| 目标 | `id`、`name`、`baseUrl`、`auth`、`headers`、`variables`、`secrets`、`allowedHosts`、`allowMutations`、`allowPrivate`、`timeoutMs`、`createdAt`、`updatedAt` |
| 目标摘要 | 目标的字段；`auth`：鉴权摘要；`secrets`：名称 → 短提示，空提示表示没有存值 |
| 鉴权 | `{type: none}`、`{type: bearer, token}`、`{type: basic, username, password}`、`{type: header, name, value}`、`{type: query, name, value}` |
| 鉴权摘要 | `{type: none}`、`{type: bearer, hint}`、`{type: basic, username}`、`{type: header, name, hint}`、`{type: query, name, hint}`；各自可带 `missing` |
| 已存请求 | `id`、`targetId`、`name`、`method`、`path`、`query`、`headers`、`auth`、`bodyMode`、`body`、`form`、`captures`、`createdAt`、`updatedAt` |
| 行 | `key`、`value`、`enabled`：`query`、`headers` 或 `form` 的一项 |
| 提取规则 | `name`、`source`、`path`、`enabled`、`ttlSeconds`、`ttlPath`、`refresh`：`captures` 的一项 |
| 请求输入 | `method`、`path`、`query`（映射或 pair）、`headers`、`body`、`requestId`、`auth` |
| 交换 | `id`、`at`、`targetId`、`targetName`、`source`（`panel` / `agent`）、`requestId`、`request`、`refreshed`、`refreshOf`，随后是 `response` 或 `error`，以及 `captures` |
| 提取结果 | `name`、`ok`、`error`、`warning`：交换的 `captures` 的一项，每条执行的规则一项 |
| 刷新 | `requestId`、`requestName`、`variables`、`reason`、`exchangeId`、`ok`、`error`：交换的 `refreshed` 的一项 |
| 已提取的值 | `name`、`hint`、`requestId`、`at`、`expiresAt` |
| 导出文档 | `format`、`version`、`exportedAt`、`settings: {historyLimit}`、`targets`、`requests`；见「导出与导入」 |
| 导入结果 | `conflicts`、`created`、`overwritten`、`skipped`、`needAuth`、`requests` |
| 交换的请求 | `method`、`url`（已掩码）、`path`、`query`、`headers`、`sentHeaders`、`body`、`bodyTruncated` |
| 交换的应答 | `status`、`statusText`、`headers`、`contentType`、`bodyBytes`、`body`、`bodyTruncated`、`binary`、`bodyBase64`、`durationMs`、`redirects`、`stream: {ended, times}` |
| 事件 | `event`（空：默认类型 `message`）、`data`、`id`、`retry` |

| 值 | 规则 |
|---|---|
| 时间 | epoch 毫秒 |
| `stream.ended` | `complete`、`cancelled`、`timeout`、`limit` |
| 短提示 | 前三个与后两个字符；六个字符以内：`••••` |
| 鉴权摘要的 `hint` | 短提示；恰为一个 `{{name}}` 引用的值原样给出 |
| `refreshed` | 发送前及 401 之后所做的刷新，按顺序；没有刷新时不出现 |
| 鉴权摘要的 `missing` | `true`：鉴权密钥没有存值；有存值时不出现 |
| `refreshOf` | 只出现在宿主作为刷新发送的交换上：该次刷新所为的变量名 |
| 刷新的 `reason` | `missing`、`expired`、`rejected` |
| 已提取的值的 `requestId` | 值所来自的已存请求 |
| `expiresAt` | 不过期的值没有此字段 |

## 存储（`store.py`）

| 存储 | 文件 | 内容 | 写入 |
|---|---|---|---|
| `TargetStore` | `targets.json` | 目标（鉴权密钥与密钥变量为明文）与开关 | 原子，权限 0600 |
| `RequestStore` | `requests.json` | 所有目标的已存请求，按创建顺序 | 原子，权限 0600 |
| `ValueStore` | `values.json` | 各作用域已提取的值：`value`、`requestId`、`at`、`expiresAt` | 原子，权限 0600 |
| `HistoryStore` | `history.jsonl` | 每行一个交换，最新在后；压缩到历史上限 | 逐行追加；压缩与清除时原子重写；权限 0600 |

| 规则 | 内容 |
|---|---|
| 密钥 | 留在存储里；`summarize()` 给出类型、非密钥的名称、一个短提示；`ValueStore.list()` 给出名称与短提示，按名称排序 |
| 变量名 | 首字符为字母或下划线；字母、数字、下划线、点、连字符；64 个字符 |
| 目标名：字符 | 首字符为字母或数字；字母、数字、空格、点、连字符、下划线；64 个字符 |
| 目标名：唯一 | 不区分大小写；冲突时加数字后缀 |
| 更新时的鉴权 | 类型不变时，空密钥保留已存的密钥；没有已存的密钥则拒绝 |
| 更新时的密钥变量 | `secrets` 是完整的集合：空值保留同名的已存值，没有已存值则拒绝；没有给出的名称被删除 |
| 导入时的密钥 | 空值保留已存值的规则同上；没有已存值时留空（`build_target(…, allow_missing=True)`） |
| 导入的写入 | `replace_all()`：整个列表一次写入；先已存请求，再目标与历史上限 |
| 提取规则的字段 | 缺失或非法的字段取默认值；`ttlSeconds` 截到上限 |
| 没有 `secrets` 的目标、没有 `captures` 的已存请求 | 读作空 |
| 请求的鉴权 | 按输入原样保存，含不完整的字段；`usable_request_auth()`：是否可以发送 |
| 无法读取的 `targets.json` | 文件改名为 `.corrupt-<time>`，由空存储取代 |
| 无法读取的 `values.json` | 读作空 |
| 校验失败 | `StoreError` |

## 请求引擎（`engine.py`）

页面或 agent 的一个请求：从组合好的输入到记录下来的交换。

| 步骤 | 行为 |
|---|---|
| 目标 | 按 id 或名称解析；`direct` 只对页面开放 |
| 刷新 | 发送之前；见「自动刷新」 |
| 变量 | `{{name}}` 替换为值；位置与优先级见「变量」 |
| URL | 路径接在基础 URL 之下；绝对 URL 必须在基础主机或某个允许的主机上 |
| 私有地址 | 没有 `allowPrivate` 时拒绝 loopback、link-local、私有地址；主机名先解析 |
| 请求头 | 先固定请求头，再请求的请求头；传输层的请求头丢弃 |
| `content-type` 默认值 | 正文以 `{` 或 `[` 开头：JSON；否则 `text/plain` |
| 鉴权 | 目标的鉴权；目标的鉴权不适用，且请求由页面发送或由宿主作为刷新发送时，请求自带的鉴权生效 |
| 未填写的密钥 | 目标的鉴权密钥未填写：请求被拒绝；请求引用了未填写的密钥变量：请求被拒绝 |
| 重定向：次数 | 至多五次，每次按允许的主机检查 |
| 重定向：凭据 | origin 变化时丢弃 |
| 重定向：方法 | 303，以及 POST 之后的 301 / 302：改为不带正文的 GET |
| 正文 | 读到上限为止；文本按声明的 charset 解码 |
| 二进制正文 | 省略；页面要求时以 base64 整体返回 |
| 事件流 | `text/event-stream` 逐事件读取；停止、超时、到达上限时，以已到达的内容结束 |
| 超时 | `timeoutMs` 覆盖重定向与正文；页面读取的流，每个 chunk 重新计时 |
| 提取 | 已存请求的提取规则在收到的应答上执行，先于掩码；结果写入交换的 `captures` |
| 401 | 见「自动刷新」；重发时两次发送各记录一条交换 |
| 掩码：对象 | 目标密钥、密钥变量的值、作用域内已提取的值（含从本次应答提取的）、请求自带的鉴权、写进请求头的凭据，连同它们的 URL 编码形式 |
| 掩码：范围 | 交换的 URL、请求头、正文、`error`；替换为 `••••••` |
| 历史 | 记录交换；正文截断，二进制正文丢弃 |

| 失败 | 结果 |
|---|---|
| 策略失败、传输失败、刷新失败、目标的鉴权密钥未填写、引用了没有存值的密钥变量 | 交换的 `error` |
| 输入畸形、目标未知 | `PolicyError`；不发送，不记录 |

## 导出与导入（`transfer.py`）

配置作为一个 JSON 文档：目标、已存请求、历史上限；不含密钥。

| 文档字段 | 内容 |
|---|---|
| `format`、`version` | `pyxis-harness-http`、`1` |
| `exportedAt` | 导出时间 |
| `settings` | `{historyLimit}` |
| `targets` | 目标的字段，不含 `createdAt`、`updatedAt`；`id` 只用于把文档里的请求连到目标 |
| `requests` | 已存请求的字段，不含 `createdAt`、`updatedAt`；`targetId`：文档里的目标 id，或 `direct` |

| 导出（`export_bundle()`） | 规则 |
|---|---|
| 鉴权密钥：目标的、请求自带的 | 字面值置空；引用了 `{{name}}` 的值原样保留 |
| 凭据请求头的值：目标的固定请求头、请求的请求头 | 同上；凭据请求头：`config.toml` 的 `CREDENTIAL_HEADERS` |
| 密钥变量 | 只有名称，值为空 |
| 其余字段 | 原样：变量、请求的查询、正文、表单、提取规则 |
| 不在文档里 | 已提取的值、历史、`agentTools`；目标已不存在的请求 |

| 导入（`plan_import()`） | 规则 |
|---|---|
| 接受的文档 | `format` 为 `pyxis-harness-http` 或 `dsh-http`（dsh-toolkit 的导出文件，形状相同）；`version` 至多 1 |
| 校验 | 整份文档先校验；任何一项非法：`StoreError`，什么都不写 |
| 匹配 | 目标按名称，不区分大小写；没有目标的请求整体作为一个单位 `direct` |
| `overwrite` | 同名的目标：设置与请求列表换成文档里的；id 与 `createdAt` 不变 |
| `skip` | 同名的目标及其请求保持不变 |
| 没有同名的目标 | 新建，取新的 id |
| `overwrite` 时文档里为空的密钥 | 取已存的值：鉴权密钥（类型不变时）、同名的密钥变量、同名的固定请求头 |
| 没有已存的值 | 鉴权密钥与密钥变量留空，即「未填写」；固定请求头略去 |
| 请求的归属 | 随其目标；目标被跳过，或文档没有定义该目标：不导入 |
| 请求的 id | 文档里的 id 空闲时沿用，历史保持关联；否则取新的 id |
| 历史上限 | 文档里的值合法时采用 |
| 上限 | 每份文档至多 200 个目标；每个作用域至多 500 条请求 |
| 不变 | 历史、已提取的值、`agentTools` |

| 导入结果 | 含义 |
|---|---|
| `conflicts` | 文档里也有的现有目标名；双方都有无目标的请求时含 `direct` |
| `created`、`overwritten`、`skipped` | 目标名 |
| `needAuth` | 写入后鉴权密钥或密钥变量未填写的目标名 |
| `requests` | 写入的已存请求数 |

## 工具（`tools.py`）

`http_*` LangChain 工具；`agentTools` 开启期间注册；每个结果都是给模型的文本。

| 工具 | 契约 |
|---|---|
| `http_targets` | 目标表：名称、基础 URL、鉴权类型、mutation、变量名、额外主机；变量名含变量、密钥变量、提取的变量、设有自动刷新的变量 |
| `http_request` | 经引擎发一个请求；GET / HEAD / OPTIONS 之外的方法需要目标的 mutation 开关与 `confirm=true`；结果列出宿主为它所做的刷新 |
| `http_history` | 一个目标或所有目标的近期交换；没有目标的请求不列出 |

密钥不进入任何结果：引擎掩码；目标表只带鉴权类型与变量名。

## 管理路由（`routes.py`）

前缀 `/api/http-client`；供 HTTP 页使用。

| 请求 | 应答 |
|---|---|
| `GET targets` | `{targets}`：不含密钥的摘要 |
| `POST targets` | `{target}`：创建的目标 |
| `PATCH targets?id=` | `{target}`：更新后的目标 |
| `DELETE targets?id=` | `{ok}`；该目标的已存请求、历史、已提取的值一并删除 |
| `GET requests?target=` | `{requests}`，按创建顺序；`direct`：没有目标的请求 |
| `POST requests` `{targetId, …}` | `{request}`；`targetId` 为目标 id 或 `direct` |
| `PATCH requests?id=` | `{request}`；带 `targetId` 则移动该请求 |
| `DELETE requests?id=` | `{ok}` |
| `GET settings`、`POST settings` | `{settings: {agentTools, historyLimit}}` |
| `POST send` `{id, request}` | `{exchange}`；`id` 为目标 id 或 `direct`（路径为完整 URL） |
| `GET history?target=&limit=` | `{entries}`，最新在前 |
| `DELETE history?id=`、`?target=`、不带参数 | `{removed}` |
| `POST test` `{id}` | `{result: {ok, status, latencyMs, error}}` |
| `GET values?target=` | `{values}`：该作用域已提取的值，不含值本身；`target` 为目标 id 或 `direct`，未知时 400 |
| `DELETE values?target=&name=` | `{removed}`；省略 `name`：清除该作用域全部 |
| `GET transfer` | `{bundle}`：导出文档 |
| `POST transfer` `{bundle, conflict, dryRun}` | `{result}`：导入结果；`conflict` 为 `overwrite` 或 `skip`（默认）；文档非法时 400，什么都不写 |
| `POST transfer` 的 `dryRun: true` | 只校验，不写入；`result` 是该次导入将得到的结果，页面读其中的 `conflicts` |

| `POST send` | 契约 |
|---|---|
| `Accept: application/x-ndjson` | 应答每行一个 JSON 对象 |
| 事件流到达期间 | `{"type": "head"}`、`{"type": "event"}` |
| 结束 | `{"type": "done", "exchange"}` 或 `{"type": "error"}` |
| 应答之前关闭连接 | 请求被取消；记录的错误为 `cancelled` |
| 已发送请求的策略失败、传输失败、刷新失败 | `exchange.error` |
| 输入非法 | 400 |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「HTTP」入口 | 打开 HTTP 页 |
| HTTP 页 | 标题栏：agent 工具开关、「导入」、「导出」；作用域选择器与目标；已存请求与交换历史；带自动保存的请求表单；应答面板；事件流视图 |

| 部件 | 内容 |
|---|---|
| 目标对话框 | 目标的字段；「高级」之下：变量、密钥变量、允许的主机、超时、私有地址开关 |
| 密钥变量编辑器 | 每行：名称、密码输入框；占位符为已存值的短提示 |
| 请求表单的页签 | Params、Body、Headers、Auth、提取；保持一行：窄面板先隐去文字徽标，再横向滚动 |
| 「提取」页签 | 每条提取规则一张卡片；「添加规则」；其下为作用域内已提取的变量 |
| 规则卡片 | 启用、变量、来源与路径、有效期、自动刷新、移除 |
| 已提取的变量 | 每个值：名称、短提示、过期时间或「已过期」、来源请求、提取时间、「清除」；「全部清除」 |
| 应答面板 Preview | 正文之前：`refreshOf`、`refreshed`；正文之后：`captures` |
| 历史列表 | 带 `refreshOf` 的交换标「刷新」 |
| 创建副本 | 已存请求的表单，含 `captures` |
| 「导出」 | 下载导出文档：`pyxis-harness-http-<YYYYMMDD>.json` |
| 「导入」 | 选择文件 → `dryRun` → 有 `conflicts` 时对话框选「覆盖」或「跳过」，没有时直接导入 → 结果一行，列出 `needAuth` 的目标 |
| 「密钥未填写」 | 目标信息行（鉴权密钥或任一密钥变量未填写）；目标对话框里未填写的密钥输入框的占位符；Auth 页签的鉴权摘要与一行说明 |
| 语法高亮 | 应答正文（格式化与原始）、已发送的正文、展开的事件的 `data` |

| 项 | 规则 |
|---|---|
| 提交的 `secrets` | 编辑器的全部行：空值保留已存值，移除的行即删除 |
| 提取规则的保存 | 随表单自动保存；`PATCH` 带完整的 `captures` |
| 有效期输入框 | 空：不过期；数字：`ttlSeconds`，截到上限；其他文本：`ttlPath` |
| 「已过期」 | 按「提取规则」的过期规则 |
| 已提取的变量的读取 | 进入作用域、每次发送之后、历史出现新交换时 |
| `refreshOf` 的显示 | 一行：宿主为哪些变量发送了该交换 |
| `refreshed` 的显示 | 每次刷新一行：来源请求、变量、原因；失败的一行带 `error`；交换自身带 `error` 时不列失败的刷新 |
| `captures` 的显示 | 一行列出已提取的名称；每个 `warning`、每个 `error` 各一行 |
| 导出、导入之前 | 待保存的请求表单先写入 |
| 导入之后 | 重新读取目标、设置与当前作用域 |
| URL 预览 | 变量替换为值；密钥变量与已提取的变量显示为 `••••••`，与变量同名时以它们为准 |
| 「复制为 cURL」 | URL 同预览；请求头与正文里变量替换为值，密钥变量与已提取的变量保持 `{{name}}` |
| 高亮的来源 | 宿主页的 `POST /api/highlight`（`require("pyxis-harness")` 的 `json`）；token 颜色来自宿主页已加载的样式表 |
| 高亮的语言 | 按 `content-type`：JSON、HTML、XML、JavaScript、CSS、YAML；其余以 `{` 或 `[` 开头的文本按 JSON；事件的 `data` 是 JSON 时按 JSON |
| 高亮的时机 | 纯文本先显示，着色在应答返回后替换；同一文本只请求一次，保留最近 16 份 |
| 不高亮 | 超过 200 000 个字符的文本；只含 `••••••` 的文本；没有匹配的语言；请求失败；正文编辑框 |
