# Web 界面

`pyxis-harness-web-ui`：`/` 下的单个自包含页面；无外部请求；数据来自 `/api`。

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
| 会话参数 | 欢迎区两个标签：工作区（最近列表、「选择目录…」打开本机的系统文件夹对话框，macOS `osascript` / Windows PowerShell / Linux zenity、kdialog；无对话框时退回内置目录浏览器；会话创建后不可改）、预设（标准 / 创造）；输入框左下角权限标签（仅可查看 / 工作区内修改 / 完全权限 / 自动审查，切换完全权限与自动审查需确认；已有会话可切换，下一轮生效）。会话打开后顶栏显示其工作区与预设 |
| 对话 | 空会话：居中欢迎区与输入框。会话开始后输入区固定在底部，消息区独立滚动。用户消息：浅蓝气泡，附图显示在气泡上方。回复：Markdown（代码块带语言与复制、表格、引用、图片），模型返回的图片块作为图片渲染；点击图片放大。`diff` / `patch` 围栏按行着色（新增绿、删除红、hunk 头与文件头各一色，整行铺满滚动宽度），复制得到原文。数学公式：行内 `$…$`、`\(…\)`，块级 `$$…$$`、`\[…\]` 与 `latex` / `tex` / `math` 围栏，用随包分发的 KaTeX（`GET /vendor/katex.min.js`，首次出现公式时才加载）渲染成 MathML；加载完成前与解析失败时显示 TeX 原文，流式输出中未闭合的公式按普通文本显示；复制含公式的选区得到 `$…$` / `$$…$$` |
| 代码高亮 | 服务端 Pygments：回复定稿后与历史加载时，代码块按围栏语言请求 `POST /api/highlight` 得到 token span；文件预览的「代码」渲染器按文件名选择 lexer；diff 两侧按文件名分别高亮。配色由 `GET /api/highlight.css` 提供（浅色 xcode、深色 github-dark），仅 token 颜色，背景沿用页面 |
| 改动文件卡片 | 每轮结束后，`pyxis-harness-workspace-changes` 用 git 工作树快照汇总本轮改动的文件与增删行数；卡片出现在该轮回复之后：单文件显示「已编辑 文件名」，多文件显示文件数与合计，前 4 行展开，其余可展开。点击行在右侧栏打开「第 N 轮改动」tab：文件选择器、单栏 / 左右对比、换行、在侧边栏打开文件、重新读取；hunk 带两侧行号与增删底色，新建 / 删除文件给出说明。摘要持久化；逐文件对比只在记录它的进程内可用，重启后提示不可用。工作区不在 git 仓库内时不记录 |
| 图片输入 | 输入框的「+」按钮、粘贴、拖入：PNG / JPEG / GIF / WebP，最多 8 张，超过 2048px 的边在浏览器内缩放，压缩后 8 MB 以内；缩略图可移除；当前模型未勾选「图像」输入时拒绝并提示 |
| 折叠行 | 推理内容、工具调用；展开为输入 / 输出卡片 |
| 轮次过程折叠 | 对齐 dsh：每轮的推理与工具调用归入一个过程组，运行中不显示组头，完成后组头显示「已完成，用时 X · N 步」（出错 / 已取消 / 等待审批），最终回复始终在组外可见。设置 → 通用「工作步骤展示」：简洁（收起并隐藏推理行）/ 标准 / 详细（收起，但工具行展开）/ 完全展开（不收起）；「工作步骤收起时机」：完成时 / 下一条消息时。偏好存于 `localStorage` |
| 左侧栏入口 | 插件在 `sidebar.panellist` 槽位登记的入口（如「记忆」）可以固定或取消固定：悬停或聚焦入口行时右侧出现取消固定按钮；取消固定的入口收进「更多」菜单，点行打开面板、点图钉重新固定（菜单保持打开）；设置 → 通用「左侧栏入口」里每个入口一个开关，绑定同一份状态（触屏没有悬停时用它）。状态存在服务端 `<profile data>/web-ui/prefs.json`（`GET` / `PUT /api/webui/prefs`），换浏览器也一致；保存失败时回滚并提示。取消固定不影响功能与数据，正在打开的面板保持打开。旧版存在 `localStorage` 的 `pyh-ui.hiddenPanels` 在服务端为空时迁移一次 |
| 记忆页 | `pyxis-harness-memory` 的浏览器模块，左侧栏「记忆」：页头（版本历史、导出、导入、刷新、清空）、版本号与最近修改时间、「允许 Agent 使用」开关（关掉后两个工具与提示词段立即注销）；「简历」视图（个人信息与能力、工作经历卡片、项目卡片，按经历时间最新 / 最早排序）与「目录」视图（工作经历 / 项目 / 经验三列 + 详情，独立项目分组）；编辑弹窗按类型给出字段（日期区间与「至今」、所属工作经历 / 项目下拉）；版本历史：修订列表（人工 / Agent、摘要、时间）、字段级修改前后对比、恢复此版本；导入 / 导出 `career-memory.json`；每 5 秒静默刷新 |
| 数据库页 | `pyxis-harness-rdb` 的浏览器模块，左侧栏「数据库」：页头「允许 Agent 使用」开关；左栏连接列表（类型徽标、名称、「可写」标记，当前连接的测试 / 编辑 / 删除）与对象树（多 schema 时下拉、过滤框、表 / 视图分组）；右侧 数据 / 结构 / SQL 三个页签。数据：过滤条（列、运算符、值）、刷新、导出 CSV、新增行、删除所选；表头点击排序、主键标记；双击单元格编辑（∅ 设为 NULL），改动按事务生成 SQL，保存前弹窗预览语句再执行；无主键的表只读。结构：列、索引、DDL。SQL：编辑器（Ctrl/Cmd+Enter 执行，选中部分只跑选中），看起来会写数据的语句先确认，结果表与导出。连接弹窗按类型（PostgreSQL / MySQL / GaussDB / SQLite）给字段，目标节点与随机选节点为可选项 |
| S3 页 | `pyxis-harness-s3` 的浏览器模块，左侧栏「S3」：页头「允许 Agent 使用」开关；左栏桶配置列表（名称、桶 / 前缀、endpoint，当前配置的测试 / 编辑 / 删除）；右侧对象浏览器：面包屑（桶 + 前缀为根）、当前页过滤、刷新、新建文件夹、上传（多选或拖入，XHR 进度条）；表格（全选、名称、大小、修改时间、操作：下载、分享链接、重命名、删除），点文件夹进入，点对象预览（图片内联、文本前 512 KB、二进制提示下载）；多选后删除所选；「加载更多」翻页；分享链接弹窗选有效期（1 小时 / 1 天 / 7 天）并复制预签名 URL；删除弹窗列出全部 key，文件夹递归。配置弹窗：桶、Endpoint、AK / SK（编辑时留空保留）、显示名、Region、限定前缀、路径风格 |
| MCP 页 | `pyxis-harness-config-center` 的浏览器模块，左侧栏「MCP」（替代原来设置里的 MCP 页签）：页头「导入 JSON」（Claude Desktop / Cursor 风格 `mcpServers`）与刷新；「连接设置」折叠区设启动等待秒数；左栏服务器列表（状态点：绿已连接 / 红失败、名称、命令或 URL、「已停用」标签），「＋ 添加」；右侧编辑卡：名称、连接方式（streamable HTTP / SSE / stdio）、stdio 的命令 / 参数（每行一个）/ 环境变量键值对 / 工作目录，HTTP 的地址 / 请求头键值对，调用前批准，启用开关；底部删除 / 测试连接（真实握手并列出工具名）/ 保存（写入 profile 补丁，重启后列表刷新）。环境变量与请求头的值可以写成 `${credential:NAME}`（也可与文字混写，如 `Bearer ${credential:GH_TOKEN}`）：配置里只留模板，值在编辑卡的「凭据」区逐项填写（只写，存入 profile 的 `credentials.yaml`；同名环境变量优先），缺值时服务器显示黄色「等待凭据」并列出缺的引用名 |
| 技能页 | 左侧栏「技能」：页头刷新、打开目录、安装 ZIP（冲突时提示覆盖 / 跳过 / 取消）；左栏技能列表（版本、启停状态、描述），右侧详情：启用开关、打开目录、删除、描述、「技能信息」（路径与 frontmatter）、文件树与预览（256 KB 截断） |
| 环境依赖 | 设置 →「环境依赖」（`settings.sections` 槽位）：bun / bunx 卡片（状态标签、已安装 / 提供版本、平台、可执行文件、数据目录、下载进度条、安装 / 修复 / 检测），安装中每 1.5 秒轮询 |
| 可观测 | 设置 →「可观测」（`pyxis-harness-otel`）：状态标签（上报中 / 未上报）、Endpoint、Public Key、Secret Key（已保存时留空保持）、启用上报、采集正文、高级设置（gzip、正文截断上限、单批 span 数）；「发送测试」「检查上报」「保存」；下方显示 trace 端点与本次运行的批次 / span 计数与最近一次结果 |
| AI 订阅页 | `pyxis-harness-subscriptions` 的浏览器模块，左侧栏「AI 订阅」：左栏提供方（Codex / ChatGPT / Antigravity / Grok）与当前提供方的账号列表（方案、默认账号），「＋ 添加账号」发起登录（校验授权 URL 的域名后在新标签打开）；登录中显示「等待授权」框（取消、手动提交回调 URL，每 1.5 秒轮询状态）；未连接时显示连接按钮与说明；已连接：账号头（已连接 / 未授权套餐、方案、重新登录（ChatGPT）、设为默认、断开连接），「模型」页签（搜索、刷新目录、自动显示所有模型、按模型勾选可见、上下文窗口编辑（整数 / 256K / 1M，Enter 保存，空恢复默认）、默认推理强度下拉），「工具」页签（每个工具一张卡片与开关），「用量」页签（方案、各额度窗口的已用百分比与重置时间）；页头「刷新模型目录」重新发现并重建模型路由 |
| API 网关页 | `pyxis-harness-gateway` 的浏览器模块，左侧栏「API 网关」：顶部监听状态标签与刷新；三个 tab（记住上次所在）：概览（启用开关、地址、端口、保存；端点表与鉴权提示；模型数与启用的 key 数）、API key（列表：显示 / 隐藏、复制、启停、删除；可用模型在「提供方 → 模型」树形对话框里勾选，不勾选表示全部；新建后一次性展示完整 key）、用量（今日 / 7 日 / 30 日，按 key、模型、协议、结果筛选；指标卡片用 K / M 紧凑显示；最新 200 条请求明细） |
| HTTP 页 | `pyxis-harness-http-client` 的浏览器模块，左侧栏「HTTP」：范围选择器（「无目标」或某个目标，「新增目标…」，目标的编辑与连接测试）；「请求」页签（保存的请求、过滤、新增、重命名、创建副本、复制为 cURL、删除）与「历史」页签；请求栏（方法、URL 或路径、发送；粘贴 cURL 填好整张表单；Params / Body / Headers / Auth）就地编辑并自动保存；响应栏（状态、耗时、大小；Preview / Headers / Request；事件流的事件、文本、原始视图；发送中可取消）；两栏之间的分隔条可拖动；`Ctrl` / `⌘` + `Enter` 发送 |
| 斜杠命令 | 输入框里键入 `/` 弹出命令菜单（↑↓ 选择，Enter / Tab 执行，Esc 关闭）：`/compact`、`/new`、`/model`、`/mode`、`/files`、`/terminal`、`/jobs`、`/clear`、`/settings`、`/help`；命令不会变成模型消息。插件的浏览器模块用 `ctx.commands.register({ name, description, icon, order?, when?, run(args) })` 添加命令 |
| @ 引用 | 键入 `@` 弹出工作区文件菜单（`GET /workspaces/search`，跳过隐藏目录与依赖目录；子串优先，其次子序列），选中插入 `@path`（含空格时 `@"path"`，目录以 `/` 结尾可继续下钻）。发送时 host 把能解析的引用展开成 `<attached-file path=…>`（文本，超长截断）或 `<attached-directory path=…>`（目录列表）附在消息后；气泡只显示原文与引用标签，点标签在右侧栏预览 |
| agent 提问 | agent 调用 `ask_user_question` 时轮次暂停（过程头显示「等待回答」），输入框上方出现问题卡片：标题、问题、单选 / 多选选项、自由输入；「提交回答」或「全部跳过」后续跑，工具收到 `{"answers": [...]}` |
| 上下文压缩 | 上下文接近窗口（默认 80%）时，模型调用前自动把较早的历史换成一份结构化检查点（保留最近 16% 窗口的内容，不拆开工具调用与结果）；对话里显示「上下文已压缩」行，可展开摘要；输入框输入 `/compact` 手动压缩整段历史。运行事件 `compact`，轨迹里一条「压缩」记录。设置 → 通用里可关闭自动压缩、调阈值与保留比例、设未声明窗口模型的默认窗口 |
| 性能与用量 | 每轮记录（`GET /sessions/{id}` 的 `turns`，`done` 事件的 `extras.turn`）：步骤数、工具调用数、token（输入 / 输出 / 缓存读写 / 推理）、模型用时、工具用时、首 token、解码用时。输入框下方的统计条（对齐 dsh）：「N 轮 M 步 · tok/s」点开会话统计（模型用时、工具调用用时、TTFT 平均、TPS），「X tok · 缓存命中」点开 token 用量明细（缓存命中、未缓存输入、缓存读取、缓存写入、输出及其中的推理），上下文占用圆环点开占用明细（已用 / 窗口、按系统提示词、工具定义、对话消息分段的占用条与各自的估算值）。统计条与每轮用量行上的 token 数用紧凑写法（`517`、`12.2K`、`1.2M`），明细里是带千分位的精确值；估算值前有 `~`。每轮回复下方有可展开的用量行。设置「性能与用量」为简洁时只显示 tok/s 与缓存命中 |
| 轨迹视图 | 顶栏「对话 / 轨迹」切换。轨迹：搜索、收起 / 展开所有轮次、总计；时间概览按轮次画出模型（蓝）与工具（黄）时间段；记录表按轮次列出用户、模型步骤（TTFT、耗时、token）、工具调用（耗时、状态）、结束；点击记录在右侧查看详情 |
| 运行中 | 本轮内容之后一处指示：「深度求索中，用时 Xs ···」；停止按钮取消当前轮 |
| 失败重试 | 模型调用失败时按重试策略自动重跑（在提供方 SDK 自带的重试之外）：设置 →「模型」页底部的「失败重试」设全局策略（不重试 / 瞬时错误 / 所有错误、最多重试次数、要重试的失败类型：限流、服务端错误、超时、网络连接、空响应、流中断），提供方编辑卡里的「失败重试」折叠区可单独设置或跟随全局。间隔 1 秒起每次翻倍、最长 30 秒，提供方给了 `Retry-After` 时取较长者。重试时对话里出现一行「模型调用失败（代码），N 秒后重试」，失败那次已流出的半截回复被移除；轨迹里一条「重试」记录。默认不开启 |
| 继续生成 | 一轮因模型调用失败而结束（限流、服务端错误、超时、网络连接、空响应、流中断）时，空输入框的发送按钮变成播放图标「继续生成」：从失败的那一步接着跑，不追加消息；刷新页面后仍可继续（会话详情带 `failure`）。其它失败（鉴权、上下文超限等）不提供继续，改好配置后重新发消息 |
| 审批 | 黄色审批卡片停靠在输入框上方；对应工具行标记待批准；设有审批时限时卡片右上角倒计时，到期后调用被拒绝、agent 继续 |
| 自动审查 | 被审查的工具行带结论标签（自动放行 / 审查未放行 / 审查失败），展开后的「审查」一栏列出风险与理由；未放行时审批卡片显示审查的理由 |
| 重启 | 输入框上方进度提示；完成后自动重连；续跑消息显示为系统分隔行，回滚时为警告色 |
| 插件页 | 全局面板不显示会话顶栏（同 dsh）：页面自带标题、简介、刷新与「添加插件」（默认按 PyPI 包名安装，可带版本；或切到本地目录，输入路径或用系统对话框选择；安装 → 预检 → 空闲后重启）。只有装进 profile 的用户插件可操作：其 bundle 行有启用 / 停用开关与卸载按钮，其条目有启用 / 停用开关；随环境安装的内置 bundle（base、creator）及其条目标为「内置」，不可改动，API 对它们返回 409（命令行与 agent 工具不受此限制）。每个变更都走预检，失败时回滚并提示；通过后在 supervisor 下等待空闲重启，页面显示重启进度并自动重连。bundle 与条目卡片用 40px 着色图标块；状态标签只在非运行态显示；「客户端模块」列出各插件的浏览器模块与加载状态 |
| 右侧栏 | 对齐 dsh：每个会话一组标签页，存于 `localStorage`（`pyh.rightbar.v1.<会话>`），刷新后恢复。标签条：带图标与关闭按钮的标签胶囊、「+」打开「开始」页、右端全屏切换与收起。「开始」页：罗盘标记与入口卡片（工作区文件、会话信息，插件注册的类型也可加卡片）；只有一个入口时直接打开该页。作为唯一标签的「开始」页不可关闭；关闭最后一个其它标签会一并收起右栏。文件 tab：根路径标签（目录弱化、末段高亮、过长左侧渐隐）、重新读取；目录树就地展开 / 折叠、目录优先、按类型着色的文件图标，轮次结束后自动刷新。点击文件打开预览 tab（同一路径只开一个）：路径头、渲染器菜单（Markdown / 代码 / 纯文本，图片直接显示）、换行开关、重新读取；二进制文件提示不支持，大文件截断提示。会话 tab：ID、工作区、预设、权限、模型、时间，复制 ID。终端 tab（`pyxis-harness-terminal` 的浏览器模块）：在工作区里开一个交互式 shell，xterm.js（CDN）渲染，加载不到时退化为逐行终端，刷新后重新接上同一个 PTY（服务端保留回放缓冲）；后台任务 tab：agent 用 `run_in_background` 启动的命令及其日志，可停止。面板可拖动调宽（280px 起，至多 70% 视口）；全屏形态覆盖整个窗口；窄屏自动全屏。文件页顶部有搜索框（200 ms 防抖，子串匹配路径）：结果显示为只含命中项及其上级目录的展开树，命中片段高亮，状态行给出结果数，超过 500 条时提示缩小范围；点文件照常打开，点目录清空搜索并在完整的树里展开定位到它；↓ / ↑ 在搜索框与结果行之间移动，Enter 打开，Esc 清空。页头的眼睛按钮切换是否显示点开头的文件，对树与搜索同时生效 |
| 插件槽位 | 页面在加载时读取 `window.__PYH_BOOT__` 的模块清单，依次加载各插件的 `client.js`；模块通过 `ctx.slots.register` 填入槽位：侧边栏面板行、「更多」菜单行、主区面板、输入框旁的停靠位、设置分区、右侧栏 tab。契约见 `pyxis_harness_web_ui` 包文档与创造模式 skill 的 `references/ui-plugin.md` |
| 模型菜单 | 输入框右下角的模型标签：按提供方分组的模型菜单；选择后写入会话（`PUT /sessions/{id}/model`），下一次请求生效；新会话在创建时带上选择；菜单底部「管理模型…」进入设置 |
| 会话顶栏 | 两行（同 dsh）：标题行（标题、工作区与预设标签、右侧栏按钮）与视图页签行（对话 / 轨迹，下划线样式）；首页不显示 |
| 设置对话框 | 800 × 800、28px 圆角、layer-2 底色；左侧 188px 导航（40px 行）；MCP 服务器改在左侧栏「MCP」页管理；「内置插件」有搜索框与按来源分组的两列卡片。「更多 → 设置」或模型菜单的「管理模型…」进入；左侧分区：通用（新会话权限、审批时限（不超时 / 1 分钟 / 5 分钟 / 15 分钟 / 1 小时）、每轮步数上限、并行工具调用数、自动审查的模型、上下文压缩及其摘要模型）、外观（主题浅色 / 深色 / 跟随系统、语言、工作步骤展示、工作步骤收起时机、性能与用量、左侧栏入口）、模型、预设（卡片，点击设为新会话默认）、内置插件（条目只读）。「模型」：新会话默认模型（下拉列出全部可选模型，含 AI 订阅等插件发布的路由）；只列出在这里配置的提供方，插件发布的路由（AI 订阅的 Codex / ChatGPT / Antigravity / Grok）不在此列、在各自的页面管理；提供方行（标题、类型、默认标记、密钥状态点、端点、模型数），点击展开编辑卡（同时只开一张）：API Key（只写、可显示）、Base URL（占位符为默认端点）、模型列表（ID、显示名、上下文、最大输出、输入模态勾选：文本 / 图像；「获取可用模型」打开可搜索的勾选列表，端点披露的模态随之带入，「恢复默认模型」）、测试连接、删除（确认框）、应用。「添加模型提供方」：「第三方模型提供方」从预置目录选择（OpenAI、Anthropic、DeepSeek、Google Gemini、OpenRouter；集成包随 pyxis-harness-llm 安装），或「自定义模型 API」填写提供方 ID、显示名、API 协议（OpenAI Chat Completions / Responses / Anthropic Messages）、端点，至少一个模型。应用后立即生效，无需重启；密钥写入 profile 的 `credentials.yaml`，配置只记录引用名 |

| 适配 | 行为 |
|---|---|
| 语言 | 中 / 英，按浏览器语言 |
| 主题 | 跟随系统；可手动切换，存于 `localStorage` |
| 移动端 | 侧边栏为抽屉 |

## API

`pyxis-harness-web-ui` 的路由（无前缀）：`GET /` 页面（含 `window.__PYH_BOOT__` 模块清单）；`GET /plugins/{entry}/client.js` 插件的浏览器模块；`POST /plugins/{entry}/call/{method}` 以 JSON 对象调用插件在 `register_client(calls=)` 登记的函数，返回 `{"result"}`，`ValueError` 为 422。

`pyxis-harness-api`，前缀 `/api`。

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/health` | | 代、重启状态、模型、工作区 |
| GET | `/plugins` | | Loader 条目、已安装 bundle |
| POST | `/plugins/install` | `{"path"}` 或 `{"package", "index_url"?}` | 安装 bundle 目录或 PyPI 包到 profile site；预检失败 422；成功后 `restart-scheduled`（supervised）或 `saved-restart-required` |
| PUT | `/plugins/bundles/{name}` | `{"enabled"}` | 启用 / 停用 bundle：装在 profile 里的，或 `optional: true` 的预置 bundle；内置 bundle 409 |
| DELETE | `/plugins/bundles/{name}` | | 卸载装在 profile 里的 bundle；其他 409 |
| PUT | `/plugins/entries/{id}` | `{"enabled"}` | 启用 / 停用条目 |
| POST | `/restart` | | 请求重启（运行中的轮次结束后）；未受 supervisor 管理时 409 |
| GET | `/sessions` | | 会话列表 |
| POST | `/sessions` | `{"title"?, "model"?, "workspace"?, "mode"?, "preset"?}` | 会话；工作区为绝对路径，不在 harness home 内 |
| PUT | `/sessions/{id}` | `{"title"}` | 重命名会话 |
| PUT | `/sessions/{id}/mode` | `{"mode"}` | 权限模式；下一轮生效 |
| PUT | `/sessions/{id}/preset` | `{"preset"}` | 预设；下一轮生效 |
| GET | `/agent` | | 预设、权限模式（`builtin: false`：插件添加，不作新会话默认）、新会话默认、审批时限 `approval_timeout` |
| PUT | `/settings/agent` | `{"default_preset"?, "default_mode"?, "approval_timeout"?, "max_steps"?, "max_parallel_tool_calls"?}` | 新会话默认；审批时限（秒，`null`：不超时）；每轮步数上限（`null`：不限）；并行工具调用数；写入 profile 补丁 |
| GET / PUT | `/settings/review` | `{"model"}` | 自动审查的模型（`null`：与被审调用相同）；立即生效并写入 profile 补丁 |
| GET / PUT | `/terminal/settings` | `{"timeout"?, "max_output_chars"?, "promote_on_timeout"?, "dialect"?, "shell"?, "pwsh"?}` | shell 工具：超时、输出上限、超时转后台立即生效；shell 的更换写入后请求重启；应答的 `application` 为 `applied` 或 `restart` |
| GET / PUT | `/web-tools/settings` | `{"search"?, "fetch"?, "search_provider"?, "search_base_url"?, "base_url"?, "max_results"?, "max_uses"?, "api_key"?}` | 网页搜索与获取：提供方、地址、数量与密钥立即生效；工具的开关写入后请求重启；密钥存入凭据文件，应答只带其状态 |
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
| GET | `/settings/mcp` | | MCP 服务器列表（env / headers 值打码，含 `${credential:REF}` 的值原样返回；`credentials` 列出各引用的 `{reference, configured, source}`）与连接状态（`connected` / `error` / `disabled` / `waiting-credentials`，后者带 `missing`）（MCP 页也用 `GET /config-center/mcp`，多带 `connectTimeout`） |
| PUT / DELETE | `/config-center/mcp/credentials` | `{"reference", "value"}` / `?reference=` | 存入或删除一个凭据值；回 `{"credential", "application"}`，被启用的 MCP 服务器引用时 `application` 为 `restart-scheduled`（受托管）或 `saved-restart-required` |
| PUT | `/settings/mcp` | `{"servers": {name: server}}` | 整体替换 MCP 服务器配置；打码值保留原值；写入 profile 补丁，重启生效 |
| POST | `/highlight` | `{"items": [{"code", "lang"?, "filename"?}]}` | 每项的 token span HTML（无匹配 lexer 时为空） |
| GET | `/highlight.css` | | 浅色与深色主题的 token 配色 |
| POST | `/workspaces/pick` | `{"path"?: 提示语}` | 本机系统文件夹对话框；取消为 `{"path": null}`；`GET /workspaces` 的 `picker` 为 `native` 或 `browse` |
| GET | `/sessions/{id}` | | 会话、运行状态、消息、待批准项及其期限 `approval_deadline`（无时限时 `null`）；上一轮以错误结束时 `failure`：`{"run_id", "code", "message", "continuable"}`，否则 `null` |
| POST | `/sessions/{id}/messages` | `{"content", "images"?}` | SSE 运行事件；`images` 为 data URL，模型未声明图像输入时 422；`@path` 引用展开成附件块 |
| GET | `/workspaces/search` | `q`, `root`?, `limit`?, `hidden`?, `fuzzy`? | 工作区里匹配 `q` 的文件与目录（`@` 引用菜单与文件页搜索用）：`limit` 1–500，`hidden=true` 包含点开头的文件与目录（依赖目录始终跳过），`fuzzy=false` 只留子串匹配；`{"entries", "truncated"}` |
| GET / PUT | `/webui/prefs` | `{"unpinnedPanels": [入口 id]}` | 页面偏好：取消固定的左侧栏入口；写入 `<profile data>/web-ui/prefs.json`，非法请求 400 |
| GET | `/jobs` | | 后台任务列表（`session` 可筛选） |
| GET | `/jobs/{id}` | `tail` | 一个后台任务与日志尾部 |
| DELETE | `/jobs/{id}` | | 停止后台任务 |
| GET / POST | `/terminals` | `{"workspace"?, "cols", "rows", "title"?}` | PTY 终端列表 / 新建；`POST /terminals/{id}/resize`、`DELETE /terminals/{id}`；WebSocket `/terminals/{id}/ws`：二进制帧为终端字节，文本帧为 JSON 控制（`resize`、`exit`） |
| POST | `/sessions/{id}/answers` | `{"answers": [{"id", "selected", "custom"?}], "interrupt_id"?}` | 回答 agent 的 `ask_user_question`，SSE 续跑；没有待回答的问题 409，未知问题 id 422 |
| POST | `/sessions/{id}/retry` | | 继续失败的上一轮：一轮 `retry` 类型的运行，从失败的那一步续跑，不加消息，SSE 同消息；上一轮没有失败、失败代码不可继续、会话忙时 409 |
| POST | `/sessions/{id}/compact` | | 手动压缩：一轮 `compact` 类型的运行，SSE 带 `compact`（有历史被替换时）与 `done`；会话忙或等待审批时 409 |
| GET | `/settings/compaction` | | 压缩配置：`auto`、`threshold_ratio`、`retain_ratio`、`default_context_window`、`summary_model` |
| PUT | `/settings/compaction` | 同上（可只给部分字段） | 立即生效并写入 profile 补丁；不重启 |
| POST | `/sessions/{id}/approvals` | `{"decisions": [{"type": "approve" \| "reject"}]}` | SSE 运行事件 |
| POST | `/sessions/{id}/cancel` | | `{"cancelled"}` |
| DELETE | `/sessions/{id}` | | `{"deleted"}` |
| GET | `/sessions/{id}/stream` | | 运行中轮次的 SSE；空闲时 204 |
| PUT | `/sessions/{id}/model` | `{"model"}` | 会话的模型 `route:model`；`null` 回到默认 |
| GET | `/models` | | 选择器目录：按路由分组的模型、默认模型 |
| GET | `/settings/models` | | 路由（密钥状态与打码，不含值；各自的 `retry`）、提供方目录、协议、全局重试策略 `retry` 与可选的失败代码 `retry_choices`、模型未声明时的 `default_context_window` 与 `default_max_tokens` |
| PUT | `/settings/models` | `{"default"}` | 新会话默认模型 |
| PUT | `/settings/model-retry` | `{"retry": 策略 \| null}` | 全局重试策略；`null` 不重试。策略：`mode`（`transient` / `all`）、`max_retries`（0–10）、`codes`、`initial_delay_ms`、`backoff_factor`、`max_delay_ms` |
| PUT | `/settings/models/{route}` | 路由设置 | 新建或修改路由；立即生效并写入 profile 补丁 |
| DELETE | `/settings/models/{route}` | | 删除路由及其凭据 |
| POST | `/settings/models/{route}/discover` | 路由设置 | 端点提供的模型（OpenAI / Anthropic 的 `/models`、Gemini 的 `/v1beta/models`、Ollama 的 `/api/tags`） |
| POST | `/settings/models/{route}/test` | 路由设置 + `model` | `{"ok", "reply", "latency_ms"}` 或 `{"ok": false, "error"}` |

| 状态码 | 条件 |
|---|---|
| 404 | 会话不存在 |
| 422 | 图片发给未声明图像输入的模型；非法的图片数据 |
| 409 | 轮次运行中；或待批准项存在 / 缺失 |
| 503 | 重启挂起；`Retry-After: 2` |

路由设置：`{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?, "retry"?}`。`protocol`（自定义端点）：`openai-chat`、`openai-responses`、`anthropic-messages`、`gemini`；Gemini 的 `base_url` 带不带 `/v1beta` 都可以。`retry` 为这条路由的重试策略，`{"mode": "inherit"}` 去掉它、跟随全局。`api_key` 缺省沿用，`""` 删除；填写的密钥存入 profile 的 `credentials.yaml`（0600），配置里的 `api_key_env` 只记录引用名；环境变量同名时优先。配置里已有的明文 `api_key` 在下次保存时迁入凭据文件。

运行事件：

| 事件 | 内容 |
|---|---|
| `reasoning` | 推理文本：DeepSeek `reasoning_content`、Anthropic / OpenAI reasoning 块 |
| `token` | 回复文本 |
| `image` | 回复中的图片（data URL 或 URL） |
| `tool_call` | 工具名、参数 |
| `tool_result` | 工具结果 |
| `context` | 主 agent 的一次模型请求按部分估算的 token 数：`system`、`tools`、`messages`；先于该请求的应答 |
| `tool_review` | 自动审查的结论：`id`、`name`、`decision`、`risk`、`reason` 或 `error`；先于对应的 `tool_call` |
| `retry` | 重试策略即将重跑失败的模型调用：`attempt`、`max_retries`、`code`、`message`、`delay_ms`；失败那次已流出的文本作废 |
| `interrupt` | 待批准的工具调用；设有审批时限时带 `deadline` |
| `error` | 错误信息 `message`、失败代码 `code`、可否继续 `continuable` |
| `done` | 轮次结束 |

推理内容随历史保存。一次运行的订阅者从头重放；断开连接不影响运行。
