# pyharness-workspace

工作区提供者：工作区注册表与默认的 deepagents backend。

| 项 | 值 |
|---|---|
| 条目 | `workspace`（`base` bundle） |
| 插件 | `apply`（函数插件） |
| 提供 | `ctx.workspace`（`Workspaces`）、`ctx.backend` |
| 注入 | `tools` |
| 数据 | 记住的工作区：`ctx.store` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `config.py` | `Config` |
| `plugin.py` | `apply`：提供 `ctx.workspace` 与 `ctx.backend` |
| `workspace.py` | `Workspace`、`WorkspaceError`、`DEFAULT_WORKSPACE` |
| `registry.py` | `Workspaces`：打开、backend、最近使用、选择器、浏览 |

## 默认工作区

| 项 | 契约 |
|---|---|
| 根目录 | `profile.documents` 下的 `default-workspace/`：`~/Documents/pyharness/<profile>/default-workspace/`；不存在时创建 |
| 配置、环境变量、启动目录 | 不参与 |
| `<profile>/` 目录的其余内容 | 不在 agent 的文件工具范围内 |
| 没有 profile 的 harness | 进程的当前目录 |

## Backend

| 配置 | backend | agent 的文件工具 |
|---|---|---|
| `shell: false` | `FilesystemBackend` | 工作区根上的 `ls`、`read_file`、`write_file` … |
| `shell: true` | `LocalShellBackend` | 同上，加 `execute`；需审批，`shell_approval: false` 时免审批 |

`virtual_mode`：agent 路径以 `/` 起始，`/` = 根；路径不出根。

## harness home 与根

| 关系 | 结果 |
|---|---|
| home 在根之内 | 文件工具在 home 上被拒绝（读与写） |
| 根在 home 之内 | 拒绝 |

## `Workspaces`（`ctx.workspace`，`registry.py`）

| 成员 | 契约 |
|---|---|
| `default` | 配置的工作区（`config.root`）；`root`、`resolve` … 委托给它 |
| `open(path)` | `path` 的已校验 `Workspace`；`None` 为默认工作区 |
| `backend_for(path, shell)` | 工作区的 backend，带缓存；`shell=False` 给出仅文件系统的 backend |
| `recent()` / `remember` / `forget` | 会话用过的工作区；存于 `ctx.store` |
| `rename(path, name)` | 工作区的显示名；`None` 恢复为目录名 |
| `browse(path)` | 一层目录：仅子目录；供应用内选择器使用 |
| `picker()` | `native`（本机的系统文件夹对话框）或 `browse` |
| `pick(prompt)` | 打开系统文件夹对话框；所选的绝对路径，或 `None` |

| 平台 | 原生对话框 |
|---|---|
| macOS | `osascript` `choose folder` |
| Windows | PowerShell `FolderBrowserDialog` |
| Linux | `zenity` 或 `kdialog`；有显示环境时 |

## `Workspace`（`workspace.py`）

一个工作区：根目录、agent 路径解析、受保护路径。

| 成员 | 契约 |
|---|---|
| `resolve(path)` | agent 路径的真实路径；在根之外或在 home 之内 → `ValueError` |
| `permissions()` | deepagents 的 `FilesystemPermission` 规则：拒绝受保护路径 |
| `describe()` | `{root, name, virtual_mode, protected}` |
