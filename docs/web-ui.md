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
| 侧边栏 | 品牌行与当前代；新会话；插件页入口；按工作区分组的会话列表：相对时间、运行中圆点、悬停删除；profile 状态；明暗主题切换 |
| 对话 | 空会话：居中欢迎区与输入框。用户消息：浅蓝气泡。回复：Markdown（代码块带语言与复制、表格、引用） |
| 折叠行 | 推理内容、工具调用；展开为输入 / 输出卡片 |
| 运行中 | 「思考中」闪光；停止按钮取消当前轮 |
| 审批 | 黄色审批卡片停靠在输入框上方；对应工具行标记待批准 |
| 重启 | 输入框上方进度提示；完成后自动重连；续跑消息显示为系统分隔行，回滚时为警告色 |
| 插件页 | bundle 与条目卡片；状态：运行中、等待依赖、已停用、失败 |

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

| 状态码 | 条件 |
|---|---|
| 404 | 会话不存在 |
| 409 | 轮次运行中；或待批准项存在 / 缺失 |
| 503 | 重启挂起；`Retry-After: 2` |

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
