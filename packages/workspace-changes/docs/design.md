# pyharness-workspace-changes

`ctx.workspaceChanges`：每个回合改动了哪些文件，来自 git 工作树快照。

## 模块

| 模块 | 职责 |
|---|---|
| `pyharness_workspace_changes/__init__.py` | 契约文档；导出公开名称 |
| `pyharness_workspace_changes/service.py` | `WorkspaceChangesService`、`Config`、store 命名空间；回合首尾快照、摘要、diff、git 子进程 |
| `pyharness_workspace_changes/git.py` | `Repo`（仓库路径）、`GitError`、`parse_unified`（unified diff → hunk） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `WorkspaceChangesService` | `Service` 子类 | `ctx.workspaceChanges`：每回合变更文件摘要与 diff |
| `Config` | pydantic 模型 | 服务配置 |
| `GitError` | 异常（`RuntimeError`） | git 命令失败或超时 |
| `parse_unified` | 函数 | unified diff 文本 → `[{old_start, new_start, header, lines: [{kind, old, new, text}]}]`；`kind` 为 ctx/add/del |
| `NAMESPACE` | 元组 | `("pyharness", "changes")`；摘要的 store 命名空间前缀 |

## 服务

| 项 | 值 |
|---|---|
| key | `workspaceChanges` |
| name | `pyharness-workspace-changes` |
| inject | `agents`、`workspace`、`store` |
| `timeout_s` | `30.0`；单条 git 命令的秒数，超时放弃本回合记录 |
| `max_files` | `500`；每个摘要列出的文件数；`total` 仍计全部 |
| `context_lines` | `3`；每个 hunk 的上下文行数 |
| `max_diff_bytes` | `2_000_000`；单文件 unified diff 的最大字节数，超过则 `oversized` |
| start | 监听 `agent/turn-start`、`agent/turn-end` |
| stop | 删除每个会话的私有 git 目录；清空内存中的树 id |

| 成员 | 契约 |
|---|---|
| `summaries(session_id)` | 该会话改动过文件的回合摘要，按 `seq` 升序（来自 store） |
| `summary(session_id, run_id)` | 一条摘要或 `None` |
| `diff(session_id, run_id, index)` | 列出文件的 hunk；记录它的进程已不在时 `available: False`；二进制文件 hunk 为空；未知 run 或 index 抛 `LookupError` |

## 事件 / 工具 / 路由 / 提示段

### 监听的事件

| 事件 | 动作 |
|---|---|
| `agent/turn-start` | 对会话工作区的工作树做快照（`git add --all` 到私有索引，`write-tree`），记下基线树 id；非仓库则跳过 |
| `agent/turn-end` | 第二次快照；`diff-tree --numstat` / `--name-status` 得到文件列表；有改动则写摘要并放入 `turn.extras["changes"]` |

异常从不打断回合：失败只记 warning。

## 数据

| 项 | 值 |
|---|---|
| 摘要 | `ctx.store` 命名空间 `("pyharness", "changes", session_id)`，键为运行 id |
| 摘要形状 | `{run_id, session_id, seq, at, after, workspace, repo, files, total, added, deleted}` |
| `files[]` | `{path, display, status, added, deleted, binary}`；`path` 相对仓库顶层，`display` 相对工作区根（上层为 `../x`） |
| `after` | 回合结束时的会话消息数；Web UI 据此放置卡片 |
| 快照目录 | 每个会话一个 `tempfile.mkdtemp(prefix="pyh-changes-")`：`index`（仓库索引副本）与 `objects`（`GIT_OBJECT_DIRECTORY`） |
| git 环境 | 清除 `GIT_*`；`GIT_TERMINAL_PROMPT=0`、`GIT_OPTIONAL_LOCKS=0`、`LC_ALL=C`；仓库对象目录作为只读 alternate |
| 仓库 | 从不被改写；`.gitignore` 生效，忽略的文件不列出 |
| diff 生命周期 | 树 id 只存于内存，进程重启后 `available: False`；摘要持久化 |
