# pyharness-plugin-manager

`plugin_manager` 工具、插件编写技能、包的只读挂载、系统提示词段。

| 条目 | entry point | 插件 | 注入 |
|---|---|---|---|
| `plugin-manager`（`base` bundle） | `pyharness-plugin-manager` | `apply`（函数插件） | `tools`、`prompt`、`agentLoop` |
| `dev-context`（`base` bundle） | `pyharness-dev-context` | `apply`（函数插件） | `prompt` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `plugin.py` | `plugin_manager` 工具、技能挂载、包的只读挂载、提示词段 |
| `dev_context.py` | 提示词段 `dev-context` |
| `reference.py` | 技能 `pyharness-composition-reference` 的 `references/packages.md` 的渲染 |
| `prompts.toml` | 模型可见的文本 |
| `skills/` | 技能内容 |

## 配置（`plugin-manager`）

| 配置 | 作用 | 面向的预设 |
|---|---|---|
| `guidance` | 系统提示词中的简短段 | 没有技能的预设（`standard`） |
| `skills` | 本包的 `skills/` 挂载到 `/skills/pyharness/` | `skills_presets`（`creator`） |
| `sources` | 已加载的包只读挂载到 `/harness/<模块名>/`；提示词段 `harness-sources` | `skills_presets`（`creator`） |

## 技能

| 项 | 值 |
|---|---|
| 位置 | `skills/<name>/SKILL.md` |
| 技能 | `pyharness-plugin-development`、`editing-pyharness-compositions`、`pyharness-composition-reference`、`agent-experience` |
| 模板 | `skills/pyharness-plugin-development/templates/` |

## 包的只读挂载

| 项 | 契约 |
|---|---|
| 范围 | 内核 `pyharness` 与每个已加载条目的包：`source_roots()` |
| 挂载点 | `/harness/<模块名>/`，经 `ctx.agentLoop.add_mount`；只读 |
| 挂载的目录 | `pyharness.package_root`：源码检出为含 `pyproject.toml`、`AGENTS.md` 与模块目录的发行目录；已安装的 wheel 为模块目录 |
| 路径的出处 | `harness_inspect topic=config` 的 `docs` 与 `package_dir` |
| 提示词段 `harness-sources` | 挂载点与路径的出处；order 55 |

## `plugin_manager` 工具

| 步骤 | 结果 |
|---|---|
| 变更动作 | `pyharness.manage` 事务：变更 → preflight → 保留或还原 |
| 被拒绝 | 返回错误；profile 不变 |
| 已保存，受托管 | 当前轮次结束后重启；发起调用的会话继续 |
| 已保存，未受托管 | 下次启动时生效 |

| 审批 | 契约 |
|---|---|
| 变更动作 | 等待人工批准 |
| 判定 | 工具审批门上的 `when` 谓词 |
| 开关 | `require_approval` |

## 提示词段 `dev-context`（`dev_context.py`）

| 行 | 值 | 条件 |
|---|---|---|
| `installation` | `pyharness` 包的目录 | |
| `profile` | profile 的名称与目录 | 有活动的 profile |
| `default workspace` | `ctx.workspace.root` | 工作区已激活 |
| `Web UI` | `ctx.http` 给出的 `http://host:port/`；API 在 `/api` 下 | |

| 部分 | 契约 |
|---|---|
| 引导文本 | 不含具体值 |
| 值 | 列表，跟在引导文本之后 |

## 包清单（`reference.py`）

| 项 | 契约 |
|---|---|
| 文件 | 技能 `pyharness-composition-reference` 的 `references/packages.md` |
| 来源 | 已安装的 entry point |
| 写入 | `python scripts/gen_packages.py` |
| 过期 | `tests/test_creator.py` 失败 |

## `prompts.toml`

| 项 | 契约 |
|---|---|
| 表 | 以使用它的模块命名：`[plugin_manager]`、`[dev_context]`；`[tools]`：工具描述 |
| 读取 | `pyharness.package_prompts`；每个字符串值去掉首尾空白 |
| 占位符 | `string.Template` 语法（`${name}`） |
