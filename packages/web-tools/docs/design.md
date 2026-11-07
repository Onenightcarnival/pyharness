# pyharness-web-tools

`ctx.web`：`web_search`（DeepSeek 原生搜索）与 `web_fetch`（HTTP GET 转可读文本）两个工具。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__.py` | 包契约文档字符串；导出公开名称 |
| `common.py` | `NOTICE`（每个工具结果的首行：内容为不可信数据）、`USER_AGENT` |
| `search.py` | `web_search`：一次 Anthropic 格式 Messages 调用（`web_search_20250305` 服务端工具）；`parse_search_response`、`format_search`、`search_tool` |
| `fetch.py` | `web_fetch`：流式 GET、HTML → 文本（`_TextExtractor`、`html_to_text`）、JSON 重排、二进制描述、截断；`fetch_tool` |
| `service.py` | `Config`、`WebToolsService`：工具注册、凭证读取、`status()`、HTTP 客户端、`search()` / `fetch()` 委托 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `WebToolsService` | `Service` 子类 | 服务键 `web`；entry point `pyharness-web-tools` |
| `Config` | pydantic 模型 | 服务配置 |
| `format_search` | 函数 | `(answer, sources, truncated) -> str`：`NOTICE`、答案、`Sources:` 列表、截断提示、引用指令 |
| `parse_search_response` | 函数 | `(body) -> (answer, sources)`：Messages 响应中 `text` 块的文本与 `web_search_tool_result` 块的去重来源（url、title、snippet、published_at） |
| `html_to_text` | 函数 | `(markup, base="") -> (title, text)`：标题、列表项、段落、`[text](url)` 链接、`[image: alt]`；script / style 等丢弃 |

## 服务

| 项 | 值 |
|---|---|
| 服务键 | `web` |
| 注入 | `tools` |
| `Config.search` | `True`；注册 `web_search` |
| `Config.fetch` | `True`；注册 `web_fetch` |
| `Config.api_key_env` | `"DEEPSEEK_API_KEY"`；搜索密钥的凭证引用 |
| `Config.base_url` | `"https://api.deepseek.com/anthropic/v1"`；Messages 端点前缀，请求发往 `<base_url>/messages` |
| `Config.model` | `"deepseek-v4-flash"`；搜索模型 |
| `Config.max_uses` | `5`（1–20）；DeepSeek 每次查询可执行的搜索次数 |
| `Config.max_results` | `8`（1–50）；返回的来源数，超出即 `truncated` |
| `Config.max_tokens` | `4096`（≥ 256）；答案预算 |
| `Config.search_timeout` | `90.0` 秒 |
| `Config.fetch_timeout` | `30.0` 秒 |
| `Config.fetch_max_chars` | `20000`（≥ 1000）；`web_fetch` 文本上限，`max_chars` 参数不得超过它 |
| `Config.fetch_max_bytes` | `5000000`（≥ 10000）；`web_fetch` 读取的响应体上限 |
| `Config.approval` | `False`；传给 `ctx.tools.register` 的审批门 |
| `transport` | `None`；httpx transport 覆盖（测试） |
| `start()` | 按 `search` / `fetch` 注册两个工具 |
| `stop()` | 无 |

## 事件 / 工具 / 路由 / 提示段

### 工具

| 工具 | 参数 | approval | tags | 结果 |
|---|---|---|---|---|
| `web_search` | `query` | `config.approval` | `("web",)` | `format_search(...)`；空查询、无密钥或请求失败时返回 `Error: ...` 文本，不抛出 |
| `web_fetch` | `url`、`max_chars?` | `config.approval` | `("web",)` | `NOTICE`、URL、状态、标题、正文；截断时附提示；非 http(s) URL 或请求失败时返回 `Error: ...` 文本 |

`web_fetch` 的内容分派：`text/html`、`application/xhtml+xml`（或无类型且以 `<` 开头）→ `html_to_text`；`text/*`、`application/json`（重排缩进）、`application/xml`、`application/javascript`、`+json`、`+xml` → 原文；其余 → `(binary content: <kind>, <size> bytes; not shown)`。

## 数据

| 项 | 值 |
|---|---|
| 凭证引用 | `config.api_key_env`（默认 `DEEPSEEK_API_KEY`）：有 profile 时读 `profile.credentials.get(ref)`，否则读环境变量 |
| `status()` | `{"search": {凭证描述…, "enabled", "model", "base_url"}, "fetch": {"enabled"}}`；无 profile 时凭证描述为 `{"reference", "configured", "source": "env" | None}` |

本包不拥有文件或 store。
