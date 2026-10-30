# Web 界面

`pyharness-web-ui`：`/` 下的单个自包含页面；无外部请求；数据来自 `/api`。

## 视觉

DeepSeek Harness Web 的设计系统；不含 DeepSeek 标志、名称、标语。

| token | 值 |
|---|---|
| 色阶 | neutral-bluish |
| 描边 | 0.5px 发丝线 |
| 圆角 | 4 / 8 / 12 / 16 / 20 / 28 |
| 投影 | soft / panel / prominent |
| 正文 | 14px / 24px |
| 用户气泡 | `rgb(237, 243, 254)` |
| 强调色 | `rgb(65, 118, 230)` |
| 侧边栏底色 | `rgb(249, 250, 251)`；暗色基底 `rgb(21, 21, 23)` |

## 布局

| 区域 | 内容 |
|---|---|
| 侧边栏 | 品牌行与当前代；新会话；插件页入口；按工作区分组的会话列表：相对时间、运行中圆点、悬停删除；profile 状态；设置入口；明暗主题切换 |
| 对话 | 空会话：居中欢迎区与输入框。用户消息：浅蓝气泡。回复：Markdown（代码块带语言与复制、表格、引用） |
| 折叠行 | 推理内容、工具调用；展开为输入 / 输出卡片 |
| 运行中 | 「思考中」闪光；停止按钮取消当前轮 |
| 审批 | 黄色审批卡片停靠在输入框上方；对应工具行标记待批准 |
| 重启 | 输入框上方进度提示；完成后自动重连；续跑消息显示为系统分隔行，回滚时为警告色 |
| 插件页 | bundle 与条目卡片；状态：运行中、等待依赖、已停用、失败 |
| 模型菜单 | 输入框右下角的模型标签：按提供方分组的模型菜单；选择后写入会话（`PUT /sessions/{id}/model`），下一次请求生效；新会话在创建时带上选择；菜单底部「管理模型…」进入设置 |
| 设置页 | 左下角齿轮进入。「模型」：新会话默认模型；提供方行（标题、类型、默认标记、密钥状态点、端点、模型数），点击展开编辑卡（同时只开一张）：API Key（只写、可显示）、Base URL（占位符为默认端点）、模型列表（ID、显示名、上下文、最大输出；「获取可用模型」打开可搜索的勾选列表，「恢复默认模型」）、测试连接、删除（确认框）、应用。「添加模型提供方」：「第三方模型提供方」从 LangChain 预置目录选择（未安装的包标注安装命令），或「自定义模型 API」填写提供方 ID、显示名、API 协议（OpenAI Chat Completions / Responses / Anthropic Messages）、端点，至少一个模型。应用后立即生效，无需重启；密钥写入 profile 的 `credentials.yaml`，配置只记录引用名 |

| 适配 | 行为 |
|---|---|
| 语言 | 中 / 英，按浏览器语言 |
| 主题 | 跟随系统；可手动切换，存于 `localStorage` |
| 移动端 | 侧边栏为抽屉 |

## API

`pyharness-api`，前缀 `/api`。

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/health` | | 代、重启状态、模型、工作区 |
| GET | `/plugins` | | Loader 条目、已安装 bundle |
| GET | `/sessions` | | 会话列表 |
| POST | `/sessions` | `{"title"?}` | 会话 |
| GET | `/sessions/{id}` | | 会话、运行状态、消息、待批准项 |
| POST | `/sessions/{id}/messages` | `{"content"}` | SSE 运行事件 |
| POST | `/sessions/{id}/approvals` | `{"decisions": [{"type": "approve" \| "reject"}]}` | SSE 运行事件 |
| POST | `/sessions/{id}/cancel` | | `{"cancelled"}` |
| DELETE | `/sessions/{id}` | | `{"deleted"}` |
| GET | `/sessions/{id}/stream` | | 运行中轮次的 SSE；空闲时 204 |
| PUT | `/sessions/{id}/model` | `{"model"}` | 会话的模型 `route:model`；`null` 回到默认 |
| GET | `/models` | | 选择器目录：按路由分组的模型、默认模型 |
| GET | `/settings/models` | | 路由（密钥状态与打码，不含值）、提供方目录、协议 |
| PUT | `/settings/models` | `{"default"}` | 新会话默认模型 |
| PUT | `/settings/models/{route}` | 路由设置 | 新建或修改路由；立即生效并写入 profile 补丁 |
| DELETE | `/settings/models/{route}` | | 删除路由及其凭据 |
| POST | `/settings/models/{route}/discover` | 路由设置 | 端点提供的模型（OpenAI / Anthropic 的 `/models`、Ollama 的 `/api/tags`） |
| POST | `/settings/models/{route}/test` | 路由设置 + `model` | `{"ok", "reply", "latency_ms"}` 或 `{"ok": false, "error"}` |

| 状态码 | 条件 |
|---|---|
| 404 | 会话不存在 |
| 409 | 轮次运行中；或待批准项存在 / 缺失 |
| 503 | 重启挂起；`Retry-After: 2` |

路由设置：`{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?}`。`api_key` 缺省沿用，`""` 删除；填写的密钥存入 profile 的 `credentials.yaml`（0600），配置里的 `api_key_env` 只记录引用名；环境变量同名时优先。配置里已有的明文 `api_key` 在下次保存时迁入凭据文件。

运行事件：

| 事件 | 内容 |
|---|---|
| `reasoning` | 推理文本：DeepSeek `reasoning_content`、Anthropic / OpenAI reasoning 块 |
| `token` | 回复文本 |
| `tool_call` | 工具名、参数 |
| `tool_result` | 工具结果 |
| `interrupt` | 待批准的工具调用 |
| `error` | 错误信息 |
| `done` | 轮次结束 |

推理内容随历史保存。一次运行的订阅者从头重放；断开连接不影响运行。
