# pyharness-llm

`ctx.llm`：基于 LangChain provider 集成的聊天模型路由（route）注册表；模型规格（spec）为 `"route:model"`。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 包契约文档字符串；从子模块导出 `__all__` |
| `catalog` | `PROTOCOLS`（自定义端点的线协议）、`PRESETS`（设置页提供的类型）、`CURATED`（各 LangChain 类型的事实）；`builtin_types`、`type_info`、`translate_options` |
| `config` | `Modality`、`ModelFactory`、`ROUTE_ID`；配置模型 `ModelEntry`、`ProviderConfig`、`LLMConfig`；`LLMConfigError`；`split_spec`、`mask_secret`、`_freeze` |
| `service` | `PROBE_PROMPT`；`EchoChatModel`；`LLMService`：工厂注册、路由与凭据解析、`resolve` 与实例缓存、`catalog` / `describe` / `directory`、`probe`、`list_models` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `LLMConfig` | 模型 | 服务配置：`default`、`options`、`providers`；路由 id 须匹配 `^[a-z0-9][a-z0-9_-]{0,63}$` |
| `LLMService` | 类 | `Service` 子类，key `llm`；entry point `pyharness-llm` |
| `ProviderConfig` | 模型 | 一条路由：`type`、`title`、`protocol`、`base_url`、`api_key`、`api_key_env`、`models`、`options`；未知字段为该路由所有模型的关键字参数（`kwargs()`） |
| `ModelEntry` | 模型 | 目录条目：`id`、`name`、`context_window`、`max_tokens`、`input`（`text` / `image`，至少一个）、`options`；`extra="forbid"` |
| `LLMConfigError` | 类 | 配置或解析错误；`RuntimeError` 子类 |
| `EchoChatModel` | 类 | 无凭据占位模型：回复最后一条 human 消息，前缀 `echo: `；`bind_tools` 返回自身 |
| `PROTOCOLS` | 常量 | `openai-chat`、`openai-responses`、`anthropic-messages` → `title`、`type`、`options`、`models_api` |
| `PRESETS` | 常量 | `openai`、`anthropic`、`deepseek`、`google_genai`、`openrouter` |
| `CURATED` | 常量 | 类型 → `title`、`env`、`base_url`、`keys`、`credentials`、`models_api`、`models` |
| `split_spec` | 函数 | `"route:model"` → `(route, model)`；无冒号 → `("", spec)`；空 → `("", "")` |
| `mask_secret` | 函数 | 非空字符串 → 8 个 `•` 加末 4 位（长度 > 8 时），否则 8 个 `•`；非字符串或空 → `None` |
| `translate_options` | 函数 | `translate_options(kind, options)`：通用 `base_url` / `api_key` 改为该类型的关键字名，丢弃 `None`；`openai` 配非官方 `base_url` 时默认 `use_responses_api=False` |
| `type_info` | 函数 | `type_info(kind)`：`id`、`title`、`package`、`preset`、`installed`、`env`、`base_url`、`keys`、`credentials`、`models_api`、`models`、`curated` |

## 服务

| 项 | 值 |
|---|---|
| key | `llm` |
| inject | 无 |
| `default` | `None`；默认模型 `route:model` |
| `options` | `{}`；所有模型的关键字参数 |
| `providers` | `{}`；路由 id → `ProviderConfig` |
| start | 注册内置工厂 `echo` |
| stop | 无 |

| 方法 | 契约 |
|---|---|
| `register(provider, factory)` | `factory(model_name, **options) -> BaseChatModel` 注册为类型 `provider`；重复 → `LLMConfigError`；返回 disposer，归属调用方插件 |
| `providers()` | 已注册类型 → 所属 entry |
| `update(default=…, providers=None, options=None)` | 校验后替换部分配置并清空缓存 |
| `invalidate()` | 清空实例缓存 |
| `route(route)` / `route_type(route)` | 配置的路由，或以 id 为 `type` 的隐式路由；`protocol` 决定类型 |
| `references(route, cfg=None)` | 依次尝试的凭据引用：`api_key_env`、具名路由的 `<ROUTE>_API_KEY`、类型的环境变量 |
| `api_key_for(route, cfg=None)` | `(value, description)`；`description` 不含值，`source` 为 `config` / `env` / 凭据库 |
| `accepts_images(spec)` / `context_window(spec)` | 目录中模型声明的输入模态 / 上下文窗口；未知 → `None` |
| `options_for(route, model=None, **overrides)` | 关键字参数：全局 → 协议 → 路由 → `base_url` → 模型（`max_tokens`、`options`）→ overrides；需要凭据时补 `api_key` |
| `resolve(spec=None, **overrides)` | `spec` 或 `config.default` 的聊天模型；按 `(spec, options)` 缓存；无默认、无路由、未知类型、包未安装或初始化失败 → `LLMConfigError` |
| `catalog()` | 预设、`echo` 与已注册工厂的 `type_info` |
| `describe_route(route)` / `describe()` | 设置页视图：路由、凭据状态（`masked`、`required`）、目录、注册表、`env_model`（`PYH_MODEL`） |
| `directory()` | 选择器视图：按路由分组的模型（`spec`、`input`、`context_window`）；默认模型不在目录中时插入首组 |
| `probe(route, model, timeout=60.0, **overrides)` | 一次短补全（`PROBE_PROMPT`）：`ok`、`reply`（≤400 字符）、`latency_ms`；超时或异常 → `LLMConfigError` |
| `list_models(route, kind=None, timeout=20.0, **overrides)` | 端点的模型 id：OpenAI `/models`、Anthropic `/v1/models?limit=1000`、Ollama `/api/tags`；返回 `supported`、`models`（`id`、`name`、`context_window`、`max_tokens`、`input`）、`url` |

## 数据

| 项 | 内容 |
|---|---|
| 模型规格 | `"route:model"` |
| 凭据解析 | `api_key`（配置，不推荐）→ `api_key_env` → `<ROUTE>_API_KEY` → 类型默认变量；每个引用先查环境变量再查 profile 凭据库 |
| 类型来源 | `PRESETS`；`langchain.chat_models.base._BUILTIN_PROVIDERS` 中的其他内置类型；`register` 注册的工厂（内置 `echo`） |
| 实例缓存 | `(spec, 冻结后的 options)` → `BaseChatModel`；`update` / `invalidate` / `register` / 带 overrides 的 `probe` 清空 |
