# agent 自扩展

agent 编写插件、安装进自己的 profile，在下一代中使用。

| 预设 | 工具 | agent 看到的 |
|---|---|---|
| `standard` | 不含 `plugin_manager`、`harness_inspect` | 系统提示词中三行「Extending this harness」：指向 Creator 预设 |
| `creator` | 全部 | skill 目录（`/skills/pyharness/`）；完整流程按需由 `read_file` 加载；包的设计文档与源码（`/harness/`） |

预设按会话选择（输入框的「预设」标签），对照 dsh 的 agent preset；`creator` bundle 只把新会话默认预设设为 `creator`（`pyh init --template creator`）。

## 流程

```
agent ──harness_inspect──────────────▶ 服务方法、事件模式、配置 schema、工具、路由
      ──plugin_manager template───────▶ bundle 模板 → /plugins/<name>/（profile 的插件源码目录）
      ──plugin_manager install_bundle─▶ [人工批准] → 安装到 profile site/
                                         → 预检（独立进程）
                                            ├ 拒绝：恢复快照，错误返回 agent
                                            └ 保存：本轮结束后重启
supervisor ──▶ 第 N+1 代 ──▶ 续跑消息 ──▶ agent 验证新能力
```

## skills

`pyharness-plugin-manager` 包内的 `skills/` 目录经 `ctx.agentLoop.add_skills(dir, "pyharness", presets=["creator"])` 只读挂载到 `creator` 预设会话的 `/skills/pyharness/`（deepagents `CompositeBackend` 路由；写入被拒绝）。deepagents 的 skills 中间件在系统提示词里列出 skill 名称与描述；正文由 agent 用 `read_file` 按需读取。

| skill | 内容 |
|---|---|
| `pyharness-plugin-development` | 流程：inspect → template → 写入 `/plugins/<name>/` → `install_bundle` → 读结果 → 新一代验证；`references/`：bundle 与插件形式、扩展点与实践、HTTP 路由、验证；`templates/basic`、`templates/tool-and-route` |
| `editing-pyharness-compositions` | patch 方言：按 id 寻址、`merge`、`remove`、`parent` / `before` / `after`、`disabled`、`isolate`、插值；分层 |
| `pyharness-composition-reference` | `references/packages.md`：环境中全部 `pyharness.plugins` / `pyharness.bundles` entry point；`scripts/gen_packages.py` 生成，测试校验未过期 |
| `agent-experience` | 工具定义、提示词片段、skill、子 agent、状态消息的写法 |

知识来源顺序：运行时检查（`harness_inspect`）→ 包的 `AGENTS.md`（`topic=config` 的 `docs`）与包目录中的源码（`package_dir`）→ skill 的参考文件。

### 包的只读挂载

| 项 | 内容 |
|---|---|
| 范围 | 内核与每个已加载条目的包 |
| 挂载点 | `creator` 预设会话的 `/harness/<模块名>/`；写入被拒绝 |
| 内容 | 包的 `AGENTS.md` 与源码 |
| 路径 | `harness_inspect topic=config name=<条目 id>` 的 `docs`、`package_dir` |
| 接口 | `ctx.agentLoop.add_mount(mount, directory, presets=None)`；其他插件同样可挂载自己的只读目录 |

### 插件源码目录

| 项 | 内容 |
|---|---|
| 目录 | `~/Documents/pyharness/<profile>/plugins/`；在 harness home 与工作区之外 |
| 挂载点 | `creator` 预设会话的 `/plugins/`；可写，只读模式除外 |
| 归属 | profile：与会话的工作区无关；安装进同一个 profile 的 `site/` |
| 接口 | `ctx.agentLoop.add_mount(mount, directory, presets, writable=True)` |
| 对照 dsh | 源码随包分发、agent 可读；pyharness 只读，扩展经插件完成 |

每个 `SKILL.md` 小于 8000 字符。其他插件：`ctx.agentLoop.add_skills(directory, label, presets=None)` 挂载自己的 skills 目录，随插件停止卸载；`ctx.agentLoop.add_preset(id, title, description, tools=…, exclude_tools=…)` 添加预设；`ctx.prompt.add(..., presets=[…])` 限定提示词片段。

## 工具

### `harness_inspect`

只读。

| topic | 内容 |
|---|---|
| `overview` | 代、profile、条目计数、服务 key、事件 |
| `services` | 服务 key；带 `name`：类型、归属、方法 |
| `events` | 名称、模式、声明方、监听者 |
| `plugins` | Loader 条目与状态 |
| `config` | 条目；带 `name`：config JSON Schema、生效配置、包目录 |
| `tools` | 已注册工具与审批闸门；带 `name`：参数 schema |
| `routes` | HTTP 路由及其贡献插件 |
| `prompt` | 系统提示词片段 |
| `ui` | Web 界面的槽位与已登记的浏览器模块 |

生效配置中来自 `${env:...}` 的值、名称类似密钥的字段：脱敏。

### `plugin_manager`

| action | 参数 | 审批 | 效果 |
|---|---|---|---|
| `list` | — | 否 | 条目与状态；已安装 bundle |
| `template` | `target=<name>`、`variant=basic\|tool-and-route\|ui-panel` | 否 | bundle 模板文件；来自 skill 的 `templates/`；`ui-panel` 含浏览器模块 `client.js`，注册主区面板与侧边栏行 |
| `install_bundle` | `target=<dir 或 包需求>` | 是 | 从目录安装 bundle（`/plugins/<name>`，或会话工作区内的目录），或从 PyPI 按包名安装（如 `pyh-example==0.1.0`） |
| `uninstall_bundle` | `target=<bundle>` | 是 | 移除已安装的 bundle |
| `set_bundle_enabled` | `target=<bundle> enabled=<bool>` | 是 | 启用 / 停用 bundle |
| `set_plugin_enabled` | `target=<entry id> enabled=<bool>` | 是 | 启用 / 停用条目 |
| `restart` | — | 是 | 本轮结束后重启 |

| `application` | 含义 |
|---|---|
| `rejected` | 预检失败；profile 未变 |
| `restart-scheduled` | 已保存；受 supervisor 管理，本轮结束后重启，本会话续跑 |
| `saved-restart-required` | 已保存；不受 supervisor 管理，下次启动生效 |
| `unchanged` | 无变化 |

| 配置 | 默认 | 效果 |
|---|---|---|
| `require_approval` | `true` | 变更动作需人工批准 |
| `guidance` | `true` | 没有 skills 的预设的三行插件编写片段 |
| `skills` | `true` | 挂载插件编写 skills 到 `/skills/pyharness/` |
| `sources` | `true` | 已加载的包只读挂载到 `/harness/<模块名>/` |
| `skills_presets` | `["creator"]` | 看到 skills、包挂载与插件源码目录的预设 |

### `dev-context` 提示词段

`pyharness-dev-context`（base bundle 的 `dev-context` 条目）：告诉 agent harness 实现在工作区之外、「这个页面」指本进程的 Web 界面、profile 文件只经 `plugin_manager` 修改；随后列出安装目录、profile 目录、工作区、Web 界面地址。

## 边界

| 防线 | 范围 |
|---|---|
| 审批 | `plugin_manager` 的全部变更动作 |
| 工具管线 | `tools/execute`、`tools/result` 覆盖 deepagents 子 agent（`task`）内的工具调用 |
| 审批闸门归属 | 一个插件撤不掉另一个插件的闸门 |
| 工作区 | 工作区根目录位于 harness home 之内 → 插件失败；harness home 位于工作区之内 → 文件工具对其读写一律拒绝 |

- 安装的插件代码运行在 harness 进程内，权限同 harness 进程，不受工作区限制。
- 审批是安装代码的唯一闸门。
