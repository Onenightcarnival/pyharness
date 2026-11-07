# pyharness-workspace

工作区提供者：`ctx.workspace`（工作区注册表）与 `ctx.backend`（默认工作区的 deepagents 后端）。

## 模块

| 模块 | 职责 |
|---|---|
| `pyharness_workspace/__init__.py` | 契约文档；导出公开名称 |
| `pyharness_workspace/plugin.py` | `name`、`inject`、`Config`、`apply`（校验根目录与 harness home、提供 `workspace` 与 `backend`） |
| `pyharness_workspace/workspace.py` | `Workspace`（根目录、agent 路径解析、受保护路径、权限规则）、`WorkspaceError` |
| `pyharness_workspace/registry.py` | `Workspaces`：打开与缓存工作区、后端缓存、最近工作区、OS 目录对话框、目录浏览 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | pydantic 模型 | 插件配置 |
| `Workspace` | 类 | 一个工作区：`root`、`virtual_mode`、`protected`、`resolve`、`permissions`、`describe` |
| `WorkspaceError` | 异常（`ValueError`） | 路径不能作为工作区 |
| `Workspaces` | 类 | `ctx.workspace`：注册表；默认工作区的属性与方法可直接访问 |
| `apply` | 函数 `(ctx, config)` | 提供 `ctx.workspace`、`ctx.backend` |
| `name` | 字符串 | `pyharness-workspace` |
| `inject` | 列表 | `tools` |

## 服务

| 项 | 值 |
|---|---|
| 形态 | 函数插件（`apply`，async） |
| name | `pyharness-workspace` |
| inject | `tools` |
| `root` | `${cwd}`；默认 agent 工作目录 |
| `virtual_mode` | `True`；agent 路径以 `/` 为根且不出根目录 |
| `shell` | `False`；`True` 时提供本机无沙箱 shell 的 `execute` 工具 |
| `shell_approval` | `True`；`shell` 开启时 `execute` 需审批（approve / reject） |
| `shell_timeout` | `120`；秒 |
| `recent_limit` | `20`；选择器记住的工作区数 |
| `picker` | `auto`；`native`（OS 对话框）或 `browse`（应用内浏览） |
| `picker_command` | `None`；打印所选目录的命令（空输出为取消），替代平台对话框 |
| `picker_timeout` | `600`；等待 OS 对话框的秒数 |
| apply | 创建根目录；根在 home 内则 `RuntimeError`；home 在根内则加入 `protected`；提供 `workspace`、`backend` |

| 配置 | 后端 | agent 文件工具 |
|---|---|---|
| `shell: false` | `FilesystemBackend` | `ls`、`read_file`、`write_file` … 在工作区根目录 |
| `shell: true` | `LocalShellBackend` | 同上加 `execute` |

| 平台 | 原生对话框 |
|---|---|
| macOS | `osascript` `choose folder` |
| Windows | PowerShell `FolderBrowserDialog` |
| Linux | 有显示时 `zenity` 或 `kdialog` |

## 事件 / 工具 / 路由 / 提示段

### 工具

| 工具 | 来源 | 审批 |
|---|---|---|
| `execute` | deepagents `LocalShellBackend`（`shell: true`） | `shell_approval: true` 时 `ctx.tools.require_approval("execute", {"allowed_decisions": ["approve", "reject"]})` |

## 数据

| 项 | 值 |
|---|---|
| 最近工作区 | `ctx.store` 命名空间 `("pyharness", "workspaces")`，键为根目录绝对路径 |
| 记录形状 | `{root, name, virtual_mode, protected, last_used}`；`name` 为显示名（至多 80 字符） |
| 默认工作区 | 不写入 store；`recent()` 始终排第一 |
| 受保护路径 | harness home 在根内时：读写均拒绝（`resolve` 抛 `ValueError`；deepagents `FilesystemPermission` deny） |
| 后端缓存 | 每个 `(root, use_shell)` 一个后端实例 |
