# pyharness-llm

聊天模型路由：LangChain provider 集成之上的 `route:model` 解析。

| 项 | 值 |
|---|---|
| 条目 | `llm`（`base` bundle） |
| 服务 | `LLMService`，`ctx.llm` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `LLMService`：provider 注册表、路由解析与模型缓存、设置视图、探测、模型列表 |
| `config.py` | 配置模型：路由、模型目录条目、`route:model` spec 的辅助函数 |
| `catalog.py` | provider 目录：线路协议、设置页预设、各 LangChain provider 类型的事实 |
| `config.toml` | provider 目录与失败码集合；`catalog.py`、`failures.py` 读取 |
| `failures.py` | 模型调用的失败码 |
| `prompts.toml` | 模型可见文本 |

## 路由

| 概念 | 定义 |
|---|---|
| 路由 | `config.providers[route]` 下配置的一个 provider：`type`、连接事实、模型目录 |
| `type` | LangChain provider（`init_chat_model` 的 `model_provider`），或 `LLMService.register` 注册的工厂 |
| 连接事实 | `base_url`、`api_key_env` |
| 模型 spec | `"route:model"` |
| 模型条目的 `input` | 输入模态：`text`、`image`；选择器与附件处理读取 |

| `type` | 来源 |
|---|---|
| 预设（`PRESETS`） | 设置页提供；其集成包是本插件的依赖 |
| 其余 LangChain 内置 | 配置中接受（`langchain.chat_models.base._BUILTIN_PROVIDERS`） |
| 已注册 | `LLMService.register`（内置 `echo`） |

## 服务

| 方法 | 契约 |
|---|---|
| `resolve(spec)` | `route:model` 的聊天模型；实例缓存到下一次 `update` |
| `build(spec, ...)` | 带单次请求覆盖项的新聊天模型；不缓存 |
| `update(...)` | 替换运行中的配置；下一次请求生效 |
| `describe()` | 路由及凭据状态（不含值）、provider 目录 |
| `directory()` | 选择器用的模型选项，按路由分组 |
| `probe(...)` | 一次简短补全 |
| `list_models(...)` | 端点提供的模型 id（OpenAI、Anthropic、Gemini、Ollama 的列表接口） |
| `retry_policy(spec)` | spec 所属路由的 `RetryPolicy`，否则全局策略，否则 `None` |

## 凭据

| 配置键 | 契约 |
|---|---|
| `api_key_env` | 凭据引用；解析顺序：环境变量，profile 凭据库 |
| `api_key` | 配置中的明文 key；接受，不推荐 |

## 失败码（`failures.py`）

一次失败的模型调用对应一个稳定的失败码，取自 provider 抛出的异常。

| 失败码 | 失败 |
|---|---|
| `RATE_LIMIT` | HTTP 429 |
| `SERVER` | 504 以外的 HTTP 5xx |
| `TIMEOUT` | 请求或流超时；HTTP 408、504 |
| `TRANSPORT` | 连接建立失败或中断 |
| `STREAM_CLOSED` | 响应流提前结束或违反协议 |
| `EMPTY_RESPONSE` | provider 的应答没有内容 |
| `AUTH` | HTTP 401、403 |
| `CONTEXT_WINDOW_EXCEEDED` | HTTP 400，消息指明上下文窗口 |
| `CONFIG` | 路由不可用：无模型、无凭据、未知 provider |
| `HTTP_<status>` | 其余 HTTP 错误状态 |
| `UNKNOWN` | 以上皆非 |

| 名称 | 契约 |
|---|---|
| `failure_code()` | 异常的失败码；优先级：属于本词表的 `code` 属性，HTTP 状态，异常类型；沿 cause 链查找 |
| `retry_after_ms()` | provider 要求的等待：异常的 `retry_after_ms`，否则其 `Retry-After` 响应头（秒）；都没有 → `None` |
| `TRANSIENT_CODES` | 重试策略默认重试的失败码 |
| `RETRY_CHOICES` | 设置表单为重试策略提供的失败码 |
| `CONTINUABLE_CODES` | 失败回合可手动继续的失败码 |

## 重试

| 项 | 契约 |
|---|---|
| 重试对象 | 策略列出的失败码 |
| 间隔 | 退避 |
| 层次 | 叠加在 provider 客户端自身的重试之上 |
| 无策略的路由 | 继承 `config.retry` |

## `config.toml`

| 键 | 含义 |
|---|---|
| `[PROTOCOLS.<id>]` | 自定义端点的线路协议：标题、LangChain 类型、模型选项、模型列表 API |
| `[failures]` | `failures.py` 的失败码集合 |
| `PRESETS` | 设置页提供的 provider 类型；其集成包是本插件的依赖 |
| `[CURATED.<type>]` | 各 LangChain provider 类型的事实；缺 `models_api` → 无模型列表 |

## `prompts.toml`

| 项 | 规则 |
|---|---|
| 表名 | 使用该文本的模块 |
| 加载 | `pyharness.package_prompts`；每个字符串值去除首尾空白 |
| 占位符 | `string.Template` 语法（`${name}`） |
