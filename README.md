# pyharness

一切皆插件的 agent harness，Python 实现；架构对照 [DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness)。

| 层 | 实现 |
|---|---|
| 内核 | `pyharness-core`：服务容器、类型化事件、分层组合、Loader、supervisor |
| agent loop | deepagents；插件，可替换 |
| 持久化 | LangGraph checkpointer + store：SQLite 或 Postgres；插件，patch 切换 |
| HTTP | FastAPI + uvicorn；插件 |
| 变更生效 | 新一代 worker 进程：预检、回滚、会话续跑 |

```
┌──────────────────────────── supervisor (pyh run) ────────────────────────────┐
│ exit 75 → next generation · boot failure → last-known-good, start again      │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ spawn
┌───────────────▼──────────────────── worker (generation N) ───────────────────┐
│ compose: bundles → profile patch → home patch → --patch                      │
│ Loader: start by inject · missing service → PENDING · error → FAILED         │
│ app/ready → app/serve → commit → app/started                                 │
│                                                                              │
│ ctx.llm  ctx.tools  ctx.prompt  ctx.checkpointer  ctx.store  ctx.backend     │
│ ctx.agentLoop  ctx.agents  ctx.http        provided by plugins, keyed lookup │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 快速开始

| 依赖 | 版本 |
|---|---|
| Python | 3.12（`.python-version`） |
| uv | 最新 |

```bash
uv sync
uv run pyh init        # profile: ~/.pyharness/profiles/web
uv run pyh run         # supervisor + worker: http://127.0.0.1:8765
```

默认模型：`echo:echo`，无需凭据。真实模型：

```bash
export DEEPSEEK_API_KEY=...         # 预置提供方 openai、anthropic、deepseek、google_genai、openrouter 的集成包随 pyharness-llm 安装
export PYH_MODEL=deepseek:deepseek-chat
uv run pyh run
```

`PYH_MODEL`：`init_chat_model` 可识别的任意 `provider:model`。

也可在 Web 界面左下角「设置 → 模型」里添加提供方：预置提供方（OpenAI、Anthropic、DeepSeek、Google Gemini、OpenRouter）或自定义 OpenAI / Anthropic 兼容端点；获取模型列表、测试连接、应用即生效，无需重启。每个会话可在输入框的模型菜单里切换模型。路由配置写入 profile 补丁的 `llm` 条目（`providers.<route>`，模型规格为 `route:model`），优先于 `PYH_MODEL`；API Key 存入 `~/.pyharness/profiles/web/credentials.yaml`，配置只记录引用名（环境变量同名时优先）。

## 命令

| 命令 | 效果 |
|---|---|
| `pyh init [--template web\|creator\|empty]` | 创建 profile；`creator`：`base` + `creator` bundle，agent 获得插件编写 skills |
| `pyh run [--patch FILE] [--no-supervisor]` | 运行 profile |
| `pyh dump-config` | 组合后的配置树；每个条目标注来源层 |
| `pyh preflight [-v]` | 独立进程启动当前配置，输出报告 |
| `pyh exec "<prompt>"` | 无 HTTP 运行一轮；`http` 停用，`api`、`web-ui` 为 `PENDING` |
| `pyh plugin list` | 条目与状态 |
| `pyh plugin install <dir>` / `uninstall <bundle>` | 安装 / 卸载 bundle；预检，失败即恢复 |
| `pyh plugin enable <id>` / `disable <id>` | 启用 / 停用条目 |
| `pyh plugin enable-bundle <bundle>` / `disable-bundle <bundle>` | 启用 / 停用 bundle |
| `pyh restart` | 运行中的 supervisor 重启 worker（SIGHUP） |

## 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `PYH_HOME` | `~/.pyharness` | harness home |
| `PYH_PROFILE` | `web` | profile 名 |
| `PYH_MODEL` | `echo:echo` | 默认模型 |
| `PYH_HOST` | `127.0.0.1` | HTTP 地址 |
| `PYH_PORT` | `8765` | HTTP 端口 |
| `PYH_WORKSPACE` | 启动目录 | agent 工作区根目录 |
| `PYH_LOG_LEVEL` | `INFO` | 日志级别 |
| `PYH_POSTGRES_DSN` | — | `examples/patches/postgres.yaml` 的连接串 |

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 内核：插件、Context、事件、Loader、组合 |
| [docs/plugins.md](docs/plugins.md) | 内核插件、事件清单、扩展方式、第三方 bundle |
| [docs/lifecycle.md](docs/lifecycle.md) | 代、重启、supervisor、预检、变更事务、续跑 |
| [docs/self-extension.md](docs/self-extension.md) | agent 自扩展流程、工具、审批边界 |
| [docs/web-ui.md](docs/web-ui.md) | Web 界面、HTTP API |
| [docs/dsh-comparison.md](docs/dsh-comparison.md) | 与 dsh 的对照 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、目录、测试、写作规范 |

## 许可证

MIT，见 [LICENSE](LICENSE)。
