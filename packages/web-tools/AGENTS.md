# pyxis-harness-web-tools

`web_search` 与 `web_fetch` 工具。

| 项 | 值 |
|---|---|
| 条目 | `web-tools`（`base` bundle） |
| 服务 | `WebToolsService`，`ctx.web` |
| 注入 | `tools` |
| 可选 | `http`：设置路由，前缀 `/api/web-tools`；`webui`：设置分区；`agents`：开关切换后丢弃已构建的图 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `WebToolsService`：按开关注册 `web_search` 与 `web_fetch`，持有凭据；设置及其路由 |
| `config.py` | 插件配置 |
| `common.py` | `search.py` 与 `fetch.py` 共用 |
| `search.py` | `web_search`：DeepSeek 搜索 |
| `fetch.py` | `web_fetch`：HTTP GET，正文化为可读文本 |
| `prompts.toml` | 模型可见文本；`pyxis_harness.package_prompts(__file__)` 加载 |
| `client.js` | 浏览器模块：设置分区「网页搜索」 |

## 开关

agent 是否拥有这两个工具：`agent_tools`。插件始终加载；关闭期间服务的 `search()`、`fetch()` 照常可用。

| 项 | 契约 |
|---|---|
| 开启 | 注册 `web_search`（`search: true`）与 `web_fetch`（`fetch: true`） |
| 关闭 | 两个工具都不注册 |
| 切换 | 设置分区「允许 Agent 使用」，`PUT /api/web-tools/settings` `{"agent_tools": bool}`；立即注册或注销，不重启 |
| 图 | 每个会话的下一轮按新的工具集构建，临时对话相同；进行中的一轮不变（`tools/changed`，见 `pyxis-harness-tools`） |
| 保存 | profile patch 里 `web-tools` 的 `config.agent_tools`（`manage.set_entry_config`，`merge: true`） |
| 默认 | 配置 `agent_tools`（`True`）：profile patch 没有保存值时生效 |
| 层序 | 组合的层序（见 `pyxis-harness-core`）：bundle 层的值 < profile patch 里保存的值 < home patch、`--patch` 覆盖层 |
| 提示词段 | 无 |

## 工具

| 工具 | 来源 | 结果 |
|---|---|---|
| `web_search` | DeepSeek Search API：每次搜索一个直接请求 | 来源：标题、url、摘要、日期 |
| `web_search`，`search_provider: deepseek-legacy` | 一次带 `web_search_20250305` 服务器工具的 Messages 调用 | 回答文本与被引用的来源 |
| `web_fetch` | HTTP GET | HTML 化为文本（链接保留为 `[text](url)`），JSON 重新缩进，其余文本原样；截断到 `fetch_max_chars` |

两个工具的输出以一条通知开头：内容是不可信的外部内容。

## 服务

| 成员 | 契约 |
|---|---|
| `api_key()` | `api_key_env` 凭据 |
| `status()` | `{"search": {凭据描述, enabled, provider, model, base_url}, "fetch": {enabled}}`；`enabled`：工具已注册 |
| `search()` | `search.search` |
| `fetch()` | `fetch.fetch` |
| `transport` | 全部请求的 httpx transport 覆盖（测试） |
| `sync()` | 按 `agent_tools` 注册或注销两个工具；返回开关状态 |
| `settings()` | 设置与搜索密钥的状态（不含密钥的值） |
| `save(fields)` | 更改设置并写入 profile 补丁；`GET`、`PUT /api/web-tools/settings`；应答：`settings()` 加 `application`（`applied` 或 `restart`） |

| `save` 的字段 | 生效 |
|---|---|
| `agent_tools` | 立即：`sync()` |
| `search_provider`、`search_base_url`、`base_url`、`max_results`、`max_uses` | 立即：下一次搜索 |
| `api_key` | 立即；存入 profile 的凭据文件；空串：删除 |
| `search`、`fetch` | 下一代；请求重启 |

## 配置

| 配置 | 默认 | 含义 |
|---|---|---|
| `agent_tools` | `True` | agent 拥有这两个工具；开关保存前的值 |
| `search` | `True` | `web_search` 存在 |
| `fetch` | `True` | `web_fetch` 存在 |
| `api_key_env` | `DEEPSEEK_API_KEY` | 搜索 key 的凭据引用 |
| `search_provider` | `deepseek-search-api` | `deepseek-search-api` 或 `deepseek-legacy` |
| `search_base_url` | `https://api.deepseek.com/v1/tools` | Search API 基址；追加 `/search` |
| `search_requests_per_second` | 5 | 每秒发起的 Search API 请求数；5 为账号级上限 |
| `max_results` | 10（1–50） | 每次搜索返回的来源数 |
| `summary_max_chars` | 800 | 工具结果中单个来源摘要的上限 |
| `base_url` | `https://api.deepseek.com/anthropic/v1` | `deepseek-legacy`：Anthropic 格式的 Messages 端点 |
| `model` | `deepseek-v4-flash` | `deepseek-legacy`：搜索模型 |
| `max_uses` | 5（1–20） | `deepseek-legacy`：DeepSeek 每次查询可运行的搜索数 |
| `max_tokens` | 4096（≥ 256） | `deepseek-legacy`：回答预算 |
| `search_timeout` | 90.0 | 秒 |
| `fetch_timeout` | 30.0 | 秒 |
| `fetch_max_chars` | 20000（≥ 1000） | `web_fetch` 的文本上限 |
| `fetch_max_bytes` | 5000000（≥ 10000） | `web_fetch` 的正文读取上限 |
| `approval` | `False` | 传给 `ctx.tools.register` 的审批门 |

## 凭据

| 项 | 契约 |
|---|---|
| 搜索 key | `api_key_env` 凭据（`DEEPSEEK_API_KEY`） |
| 解析顺序 | 环境变量，profile 凭据库 |
| 写入方 | 设置 → 模型，DeepSeek 路由 |
| 缺失 | `web_search` 返回添加该凭据的说明；回合不失败 |

## 搜索（`search.py`）

| `search_provider` | 请求 |
|---|---|
| `deepseek-search-api` | `POST {search_base_url}/search` `{query, count, need_content: false}`：一个直接请求，按 `search_requests_per_second` 限速；来源带摘要 |
| `deepseek-legacy` | 一次 Anthropic 格式的 Messages 调用，带 `web_search_20250305` 服务器工具：带引用来源的回答 |

| 函数 | 契约 |
|---|---|
| `search()` | `{"answer", "sources", "truncated"}`；失败 → `RuntimeError`，消息面向用户 |
| `map_search_response()` | Search API 应答的来源：url、title、snippet、summary、published_at |
| `parse_search_response()` | 带 `web_search_tool_result` 块的 Messages 应答的回答文本与去重后的来源 |
| `format_search()` | 工具结果：通知、回答、`Sources:` 列表（每个来源的摘要或片段）、引用指示 |
| `search_tool()` | 绑定到服务的 `web_search` LangChain 工具 |

Search API 端点的重定向、HTTP 429：搜索失败。

## 抓取（`fetch.py`）

| 函数 | 契约 |
|---|---|
| `html_to_text()` | HTML 文档的 `(title, text)`：标题、列表项、段落，链接为 `[text](url)` |
| `fetch()` | `{"url", "status", "content_type", "title", "text", "truncated"}`；失败 → `RuntimeError` |
| `fetch_tool()` | 绑定到服务的 `web_fetch` LangChain 工具 |

| 正文 | 处理 |
|---|---|
| 读取 | 至多 `fetch_max_bytes` |
| HTML | 化为文本 |
| JSON | 重新缩进 |
| 其余文本类型 | 原样 |
| 二进制 | 给出描述 |
| 文本 | 在 `max_chars` 处截断；`max_chars` 至多 `fetch_max_chars` |

## 共用（`common.py`）

| 名称 | 契约 |
|---|---|
| `NOTICE` | 每个工具结果的首行：内容是不可信数据 |
| `USER_AGENT` | 每个外发请求的 `user-agent` 头 |
| `Host` | 两个模块所用的服务视图：配置、API key、client |
| `Pacer` | 任意一秒窗口内至多 `limit` 次请求发起 |
