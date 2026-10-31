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
| 层级背景 | 对齐 dsh 的 layer-1 / 2 / 3（暗色 `#232324` / `#2c2c2e` / `#353638`）：输入框、弹窗、设置对话框按层取色；导航选中行用 nav-active |
| 阴影 | soft / panel / prominent 都带 0.5px 描边（亮色 l4、暗色 l3），数值与 dsh elevation 一致 |
| 菜单 | 半透明填充 + `blur(40px) saturate(150%)`，行高 34px、圆角 12px |
| 提示气泡 | 元素的 `title` 在悬停 450ms 后以 dsh 风格气泡显示（13px / 20px，圆角 8px） |
| 代码块 | 11px / 19px 等宽，头部 10 / 18 / 8 / 22，正文 6 / 22 / 20，语言名用三级文字色；行内代码 12px 无描边 |
| 输入框 | 正文 14px / 24px；表单输入 34px、描边 l4、layer-1 底色 |

## 布局

| 区域 | 内容 |
|---|---|
| 侧边栏 | 品牌行与当前代；新会话；插件页入口；「工作区」区头（搜索会话、视图选项：按工作区分组 / 单一列表、按最近更新 / 创建时间排序，添加工作区）；工作区行可折叠，悬停显示「操作」（重命名、删除工作区：从列表移除，文件夹与会话保留，会话归入「未分组」）与「在此新建会话」；会话行：相对时间、运行中圆点，悬停显示操作菜单（重命名、复制会话 ID、删除会话，删除需确认）；底部「更多」菜单：设置、主题、profile 状态。收起后为图标栏，点标志展开 |
| 会话参数 | 欢迎区两个标签：工作区（最近列表、「选择目录…」打开本机的系统文件夹对话框，macOS `osascript` / Windows PowerShell / Linux zenity、kdialog；无对话框时退回内置目录浏览器；会话创建后不可改）、预设（标准 / 创造）；输入框左下角权限标签（仅可查看 / 工作区内修改 / 完全权限，切换完全权限需确认；已有会话可切换，下一轮生效）。会话打开后顶栏显示其工作区与预设 |
| 对话 | 空会话：居中欢迎区与输入框。会话开始后输入区固定在底部，消息区独立滚动。用户消息：浅蓝气泡，附图显示在气泡上方。回复：Markdown（代码块带语言与复制、表格、引用、图片），模型返回的图片块作为图片渲染；点击图片放大 |
| 代码高亮 | 服务端 Pygments：回复定稿后与历史加载时，代码块按围栏语言请求 `POST /api/highlight` 得到 token span；文件预览的「代码」渲染器按文件名选择 lexer；diff 两侧按文件名分别高亮。配色由 `GET /api/highlight.css` 提供（浅色 xcode、深色 github-dark），仅 token 颜色，背景沿用页面 |
| 改动文件卡片 | 每轮结束后，`pyharness-workspace-changes` 用 git 工作树快照汇总本轮改动的文件与增删行数；卡片出现在该轮回复之后：单文件显示「已编辑 文件名」，多文件显示文件数与合计，前 4 行展开，其余可展开。点击行在右侧栏打开「第 N 轮改动」tab：文件选择器、单栏 / 左右对比、换行、在侧边栏打开文件、重新读取；hunk 带两侧行号与增删底色，新建 / 删除文件给出说明。摘要持久化；逐文件对比只在记录它的进程内可用，重启后提示不可用。工作区不在 git 仓库内时不记录 |
| 图片输入 | 输入框的「+」按钮、粘贴、拖入：PNG / JPEG / GIF / WebP，最多 8 张，超过 2048px 的边在浏览器内缩放，压缩后 8 MB 以内；缩略图可移除；当前模型未勾选「图像」输入时拒绝并提示 |
| 折叠行 | 推理内容、工具调用；展开为输入 / 输出卡片 |
| 轮次过程折叠 | 对齐 dsh：每轮的推理与工具调用归入一个过程组，组头运行中显示「深度求索中，用时 Xs ···」，完成后显示「已完成，用时 X · N 步」（出错 / 已取消 / 等待审批），最终回复始终在组外可见。设置 → 通用「工作步骤展示」：简洁（收起并隐藏推理行）/ 标准 / 详细（收起，但工具行展开）/ 完全展开（不收起）；「工作步骤收起时机」：完成时 / 下一条消息时。偏好存于 `localStorage` |
| 性能与用量 | 每轮记录（`GET /sessions/{id}` 的 `turns`，`done` 事件的 `extras.turn`）：步骤数、工具调用数、token（输入 / 输出 / 缓存读写 / 推理）、模型用时、工具用时、首 token、解码用时。输入框下方的统计条：「N 轮 M 步 · tok/s」点开会话统计（模型用时、工具调用用时、TTFT 平均、TPS），「X tokens · 缓存命中」点开 token 用量明细；模型声明了上下文窗口时显示上下文占用圆环。每轮回复下方有可展开的用量行。设置「性能与用量」为简洁时只显示 tok/s 与缓存命中 |
| 轨迹视图 | 顶栏「对话 / 轨迹」切换。轨迹：搜索、收起 / 展开所有轮次、总计；时间概览按轮次画出模型（蓝）与工具（黄）时间段；记录表按轮次列出用户、模型步骤（TTFT、耗时、token）、工具调用（耗时、状态）、结束；点击记录在右侧查看详情 |
| 运行中 | 「思考中」闪光；停止按钮取消当前轮 |
| 审批 | 黄色审批卡片停靠在输入框上方；对应工具行标记待批准 |
| 重启 | 输入框上方进度提示；完成后自动重连；续跑消息显示为系统分隔行，回滚时为警告色 |
| 插件页 | 全局面板不显示会话顶栏（同 dsh）：页面自带标题、简介、刷新与「添加插件」（默认按 PyPI 包名安装，可带版本；或切到本地目录，输入路径或用系统对话框选择；安装 → 预检 → 空闲后重启）。bundle 行有启用 / 停用开关（base 除外）与卸载按钮（仅 profile 内安装的）；非 base 条目有启用 / 停用开关（http、api、web-ui 除外）。每个变更都走预检，失败时回滚并提示；通过后在 supervisor 下等待空闲重启，页面显示重启进度并自动重连。bundle 与条目卡片用 40px 着色图标块；状态标签只在非运行态显示；「客户端模块」列出各插件的浏览器模块与加载状态 |
| 右侧栏 | 对齐 dsh：每个会话一组标签页，存于 `localStorage`（`pyh.rightbar.v1.<会话>`），刷新后恢复。标签条：带图标与关闭按钮的标签胶囊、「+」打开「开始」页、右端全屏切换与收起。「开始」页：罗盘标记与入口卡片（工作区文件、会话信息，插件注册的类型也可加卡片）；只有一个入口时直接打开该页。作为唯一标签的「开始」页不可关闭；关闭最后一个其它标签会一并收起右栏。文件 tab：根路径标签（目录弱化、末段高亮、过长左侧渐隐）、重新读取；目录树就地展开 / 折叠、目录优先、按类型着色的文件图标，轮次结束后自动刷新。点击文件打开预览 tab（同一路径只开一个）：路径头、渲染器菜单（Markdown / 代码 / 纯文本，图片直接显示）、换行开关、重新读取；二进制文件提示不支持，大文件截断提示。会话 tab：ID、工作区、预设、权限、模型、时间，复制 ID。面板可拖动调宽（280px 起，至多 70% 视口）；全屏形态覆盖整个窗口；窄屏自动全屏 |
| 插件槽位 | 页面在加载时读取 `window.__PYH_BOOT__` 的模块清单，依次加载各插件的 `client.js`；模块通过 `ctx.slots.register` 填入槽位：侧边栏面板行、「更多」菜单行、主区面板、输入框旁的停靠位、设置分区、右侧栏 tab。契约见 `pyharness_web_ui` 包文档与创造模式 skill 的 `references/ui-plugin.md` |
| 模型菜单 | 输入框右下角的模型标签：按提供方分组的模型菜单；选择后写入会话（`PUT /sessions/{id}/model`），下一次请求生效；新会话在创建时带上选择；菜单底部「管理模型…」进入设置 |
| 会话顶栏 | 两行（同 dsh）：标题行（标题、工作区与预设标签、右侧栏按钮）与视图页签行（对话 / 轨迹，下划线样式）；首页不显示 |
| 设置对话框 | 800 × 800、28px 圆角、layer-2 底色；左侧 188px 导航（40px 行）；「内置插件」有搜索框与按来源分组的两列卡片。「更多 → 设置」或模型菜单的「管理模型…」进入；左侧分区：通用（新会话权限、语言、外观浅色 / 深色 / 跟随系统）、模型、预设（卡片，点击设为新会话默认）、内置插件（条目只读）。「模型」：新会话默认模型；提供方行（标题、类型、默认标记、密钥状态点、端点、模型数），点击展开编辑卡（同时只开一张）：API Key（只写、可显示）、Base URL（占位符为默认端点）、模型列表（ID、显示名、上下文、最大输出、输入模态勾选：文本 / 图像；「获取可用模型」打开可搜索的勾选列表，端点披露的模态随之带入，「恢复默认模型」）、测试连接、删除（确认框）、应用。「添加模型提供方」：「第三方模型提供方」从预置目录选择（OpenAI、Anthropic、DeepSeek、Google Gemini、OpenRouter；集成包随 pyharness-llm 安装），或「自定义模型 API」填写提供方 ID、显示名、API 协议（OpenAI Chat Completions / Responses / Anthropic Messages）、端点，至少一个模型。应用后立即生效，无需重启；密钥写入 profile 的 `credentials.yaml`，配置只记录引用名 |

| 适配 | 行为 |
|---|---|
| 语言 | 中 / 英，按浏览器语言 |
| 主题 | 跟随系统；可手动切换，存于 `localStorage` |
| 移动端 | 侧边栏为抽屉 |

## API

`pyharness-web-ui` 的路由（无前缀）：`GET /` 页面（含 `window.__PYH_BOOT__` 模块清单）；`GET /plugins/{entry}/client.js` 插件的浏览器模块；`POST /plugins/{entry}/call/{method}` 以 JSON 对象调用插件在 `register_client(calls=)` 登记的函数，返回 `{"result"}`，`ValueError` 为 422。

`pyharness-api`，前缀 `/api`。

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/health` | | 代、重启状态、模型、工作区 |
| GET | `/plugins` | | Loader 条目、已安装 bundle |
| POST | `/plugins/install` | `{"path"}` 或 `{"package", "index_url"?}` | 安装 bundle 目录或 PyPI 包到 profile site；预检失败 422；成功后 `restart-scheduled`（supervised）或 `saved-restart-required` |
| PUT | `/plugins/bundles/{name}` | `{"enabled"}` | 启用 / 停用 bundle |
| DELETE | `/plugins/bundles/{name}` | | 卸载 bundle |
| PUT | `/plugins/entries/{id}` | `{"enabled"}` | 启用 / 停用条目 |
| POST | `/restart` | | 请求重启（运行中的轮次结束后）；未受 supervisor 管理时 409 |
| GET | `/sessions` | | 会话列表 |
| POST | `/sessions` | `{"title"?, "model"?, "workspace"?, "mode"?, "preset"?}` | 会话；工作区为绝对路径，不在 harness home 内 |
| PUT | `/sessions/{id}` | `{"title"}` | 重命名会话 |
| PUT | `/sessions/{id}/mode` | `{"mode"}` | 权限模式；下一轮生效 |
| PUT | `/sessions/{id}/preset` | `{"preset"}` | 预设；下一轮生效 |
| GET | `/agent` | | 预设、权限模式、新会话默认 |
| PUT | `/settings/agent` | `{"default_preset"?, "default_mode"?}` | 新会话默认；写入 profile 补丁 |
| GET | `/workspaces` | | 默认与最近工作区 |
| POST | `/workspaces` | `{"path"}` | 校验并记住工作区 |
| PUT | `/workspaces` | `{"path", "name"}` | 工作区显示名；空值恢复目录名 |
| DELETE | `/workspaces?path=` | | 从最近列表移除；文件夹与会话保留 |
| POST | `/workspaces/browse` | `{"path"?}` | 一级目录列表（仅目录，隐藏目录标记） |
| GET | `/workspaces/files?path=&root=` | | 工作区内目录的条目（名称、虚拟路径、目录、大小、隐藏、修改时间）；`root` 缺省为默认工作区 |
| GET | `/workspaces/file?path=&root=&limit=` | | 工作区内文本文件的内容（默认至多 512 KB）；`binary`、`truncated` 标记 |
| GET | `/workspaces/file/raw?path=&root=` | | 工作区内文件的原始字节（预览图片用，至多 20 MB），按扩展名猜测类型 |
| GET | `/sessions/{id}/changes` | | 各轮改动文件摘要（`GET /sessions/{id}` 也带 `changes`） |
| GET | `/sessions/{id}/turns` | | 各轮记录：`stats`（步骤、token、墙钟时间）与 `records`（轨迹：user / step / tool / end）；`GET /sessions/{id}` 也带 `turns` 与 `context_window` |
| GET | `/sessions/{id}/changes/{run}/diff?index=` | | 所列文件的 hunk，行带高亮 HTML；重启后 `available: false` |
| POST | `/highlight` | `{"items": [{"code", "lang"?, "filename"?}]}` | 每项的 token span HTML（无匹配 lexer 时为空） |
| GET | `/highlight.css` | | 浅色与深色主题的 token 配色 |
| POST | `/workspaces/pick` | `{"path"?: 提示语}` | 本机系统文件夹对话框；取消为 `{"path": null}`；`GET /workspaces` 的 `picker` 为 `native` 或 `browse` |
| GET | `/sessions/{id}` | | 会话、运行状态、消息、待批准项 |
| POST | `/sessions/{id}/messages` | `{"content", "images"?}` | SSE 运行事件；`images` 为 data URL，模型未声明图像输入时 422 |
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
| 422 | 图片发给未声明图像输入的模型；非法的图片数据 |
| 409 | 轮次运行中；或待批准项存在 / 缺失 |
| 503 | 重启挂起；`Retry-After: 2` |

路由设置：`{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?}`。`api_key` 缺省沿用，`""` 删除；填写的密钥存入 profile 的 `credentials.yaml`（0600），配置里的 `api_key_env` 只记录引用名；环境变量同名时优先。配置里已有的明文 `api_key` 在下次保存时迁入凭据文件。

运行事件：

| 事件 | 内容 |
|---|---|
| `reasoning` | 推理文本：DeepSeek `reasoning_content`、Anthropic / OpenAI reasoning 块 |
| `token` | 回复文本 |
| `image` | 回复中的图片（data URL 或 URL） |
| `tool_call` | 工具名、参数 |
| `tool_result` | 工具结果 |
| `interrupt` | 待批准的工具调用 |
| `error` | 错误信息 |
| `done` | 轮次结束 |

推理内容随历史保存。一次运行的订阅者从头重放；断开连接不影响运行。
