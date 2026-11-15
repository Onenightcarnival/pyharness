# pyharness-web-tools

`web_search` 与 `web_fetch` 工具。

| 项 | 值 |
|---|---|
| 条目 | `web-tools`（`web` bundle） |
| 服务 | `WebToolsService`，`ctx.web` |
| 注入 | `tools` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `WebToolsService`：注册 `web_search` 与 `web_fetch`，持有凭据 |
| `config.py` | 插件配置 |
| `common.py` | `search.py` 与 `fetch.py` 共用 |
| `search.py` | `web_search`：DeepSeek 搜索 |
| `fetch.py` | `web_fetch`：HTTP GET，正文化为可读文本 |
| `prompts.toml` | 模型可见文本；`pyharness.package_prompts(__file__)` 加载 |

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
| `status()` | `{"search": {凭据描述, enabled, provider, model, base_url}, "fetch": {enabled}}` |
| `search()` | `search.search` |
| `fetch()` | `fetch.fetch` |
| `transport` | 全部请求的 httpx transport 覆盖（测试） |

## 配置

| 配置 | 默认 | 含义 |
|---|---|---|
| `search` | `True` | 注册 `web_search` |
| `fetch` | `True` | 注册 `web_fetch` |
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
