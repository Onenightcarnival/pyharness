# pyharness-plugin-manager

`plugin_manager` 工具、插件编写 skills、`dev-context` 提示段：agent 自扩展（self-extension）的入口。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 插件 `pyharness-plugin-manager`：`plugin_manager` 工具、skills 挂载、`plugin-authoring` 提示段、`render_template` |
| `dev_context` | 插件 `pyharness-dev-context`：`dev-context` 提示段（安装目录、profile、工作区、Web UI 地址） |
| `reference` | 生成 `skills/pyharness-composition-reference/references/packages.md`：环境中全部插件与 bundle entry point |
| `skills/pyharness-plugin-development/SKILL.md` | 流程：inspect → template → 写入 `/plugins/<name>/` → `install_bundle` → 新一代验证；`references/`：`host-plugin.md`、`ui-plugin.md`、`http.md`、`practices.md`、`verification.md` |
| `skills/pyharness-plugin-development/templates/basic/` | `pyproject.toml`、`__MODULE__/__init__.py`、`__MODULE__/bundle.yaml` |
| `skills/pyharness-plugin-development/templates/tool-and-route/` | 同上，含工具与 HTTP 路由 |
| `skills/pyharness-plugin-development/templates/ui-panel/` | 同上，加 `__MODULE__/client.js`：注册 `main` 面板与 `sidebar.panellist` 行 |
| `skills/editing-pyharness-compositions/SKILL.md` | patch 方言：按 id 寻址、`merge`、`remove`、`parent` / `before` / `after`、`disabled`、`isolate`、插值、分层 |
| `skills/pyharness-composition-reference/SKILL.md`、`references/packages.md` | 已安装包清单；`scripts/gen_packages.py` 生成，`tests/test_creator.py` 校验未过期 |
| `skills/agent-experience/SKILL.md` | 工具定义、提示词片段、skill、子 agent、状态消息的写法 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Action` | 类型别名 | `Literal["list", "template", "install_bundle", "uninstall_bundle", "set_bundle_enabled", "set_plugin_enabled", "restart"]` |
| `Config` | 模型 | `require_approval`、`guidance`、`skills`、`skills_presets` |
| `MUTATING` | 常量 | 需审批的 action 集合：`install_bundle`、`uninstall_bundle`、`set_bundle_enabled`、`set_plugin_enabled`、`restart` |
| `SKILLS_DIR` | 常量 | 包内 `skills/` |
| `TEMPLATES_DIR` | 常量 | `skills/pyharness-plugin-development/templates/` |
| `TOKENS` | 常量 | `("__DIST__", "__MODULE__", "__BUNDLE__", "__TITLE__")` |
| `apply` | 函数 | `apply(ctx, config)`：挂载 skills、添加提示段、注册工具 |
| `inject` | 常量 | `["tools", "prompt", "agentLoop"]` |
| `name` | 常量 | `"pyharness-plugin-manager"` |
| `render_template` | 函数 | `render_template(short, variant="basic")` → `{相对路径: 内容}`；`short` 规整为 slug，`dist` = `pyh-<slug>`、`module` = `pyh_<slug_>`、`title` = 首字母大写 + ` plugin`；未知 variant → `ValueError` |
| `template_variants` | 函数 | `templates/` 下的目录名，排序 |

## 服务

### `pyharness-plugin-manager`（条目 `plugin-manager`）

| 项 | 值 |
|---|---|
| 形式 | 函数插件 |
| `inject` | `tools`、`prompt`、`agentLoop` |
| `Config.require_approval` | `True`；变更 action 需人工批准 |
| `Config.guidance` | `True`；没有 skills 的预设看到三行 `plugin-authoring` 片段 |
| `Config.skills` | `True`；`ctx.agentLoop.add_skills(SKILLS_DIR, "pyharness", presets=skills_presets)` 挂载到 `/skills/pyharness/` |
| `Config.skills_presets` | `["creator"]` |
| `apply` | 挂载 skills；`guidance` 为真且存在无 skills 的预设（或 `skills` 为假）时添加提示段；注册工具 |

### `pyharness-dev-context`（条目 `dev-context`）

| 项 | 值 |
|---|---|
| 形式 | 函数插件 |
| `inject` | `prompt` |
| `Config.order` | `60` |
| `apply` | `ctx.prompt.add("dev-context", callable, order=config.order)`；内容每次渲染时计算 |

## 工具

| 工具 | 审批 | 参数 |
|---|---|---|
| `plugin_manager` | `require_approval` 为真时 `{"allowed_decisions": ["approve", "reject"], "description": ..., "when": args.action ∈ MUTATING}` | `action: Action`、`target`、`enabled`、`variant` |

| action | 参数 | 效果 |
|---|---|---|
| `list` | — | `entries`（`id`、`name`、`state`、`source`、`missing`、`error`）、`bundles`（`profile.installed_bundles()`）、`generation` |
| `template` | `target=<name>`、`variant=basic\|tool-and-route\|ui-panel` | `write_under: /plugins/<name>`、`files`、`then` |
| `install_bundle` | `target=<dir 或 包需求>` | 路径（`manage.looks_like_path` 或经 `ctx.workspace.resolve` 存在）→ `manage.install_bundle`；否则 `manage.install_package` |
| `uninstall_bundle` | `target=<bundle>` | `manage.uninstall_bundle` |
| `set_bundle_enabled` | `target`、`enabled` | `manage.set_bundle_enabled` |
| `set_plugin_enabled` | `target=<entry id>`、`enabled` | `manage.set_entry_enabled` |
| `restart` | — | 视为 `saved` 后走 `finish` |

| `application` | 条件 |
|---|---|
| `rejected` | 预检失败；profile 未变 |
| `restart-scheduled` | `saved` 且 `lifecycle.supervised`：`request_restart(reason, resume=[session])`，本轮结束后重启 |
| `saved-restart-required` | `saved` 且不受 supervisor 管理 |
| `unchanged` | manage 返回无变化 |

| 规则 | 内容 |
|---|---|
| 无 profile | 返回 `{"error": "no profile: plugin management unavailable"}` |
| `baseline` | 调用时的 `ctx.loader.snapshot()`；已失败的条目不算新失败 |
| 会话 id | `runtime.config["configurable"]["thread_id"]` |

## 提示段

| id | order | presets | 内容 |
|---|---|---|---|
| `plugin-authoring` | 50 | `skills` 为真时：不在 `skills_presets` 中的预设；否则全部 | 「Extending this harness」三行：`harness_inspect`、`plugin_manager`、Creator 预设 |
| `dev-context` | `Config.order`（60） | 全部 | 「This harness」固定文本 + `installation`、`profile`、`default workspace`（有 `ctx.workspace.root` 时）、`Web UI` / `API` 地址（`ctx.http.config.serve` 为真时） |

## 数据

| 项 | 位置 |
|---|---|
| skills | 包内 `skills/`，只读挂载为 `/skills/pyharness/`（deepagents `CompositeBackend`） |
| 模板输出 | agent 写入工作区 `/plugins/<name>/` |
| `packages.md` | `reference.write_packages()` 写入 `skills/pyharness-composition-reference/references/packages.md` |
