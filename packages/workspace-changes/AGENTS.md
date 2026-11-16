# pyharness-workspace-changes

每一轮改动了哪些文件：来自 git 工作树快照。

| 项 | 值 |
|---|---|
| 条目 | `workspace-changes`（`base` bundle） |
| 服务 | `WorkspaceChangesService`，`ctx.workspaceChanges` |
| 注入 | `agents`、`workspace`、`store` |
| 数据 | 摘要：`ctx.store`；diff：仅在本进程内 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `WorkspaceChangesService`、`Config`、store 命名空间：每轮的工作树快照、存储的摘要、diff |
| `git.py` | `Repo`、`GitError`、`parse_unified` |

## 事件

| 时机 | 工作 |
|---|---|
| `agent/turn-start` | 把会话工作区的工作树快照进私有对象目录（tree id） |
| `agent/turn-end` | 第二次快照；两者之间 `diff-tree` → 摘要；写入 `turn.extras["changes"]` |

## 服务

| 成员 | 契约 |
|---|---|
| `summaries(session_id)` | 会话中改动过文件的各轮的摘要，从旧到新（已存储） |
| `summary(session_id, run_id)` | 一份摘要，或 `None` |
| `diff(session_id, run_id, index)` | 所列文件的 hunk；重启后 `available: False` |

`available: False`：记录该 diff 的进程已不存在。

## 摘要

```
{run_id, session_id, seq, at, after, workspace, repo,
 files: [{path, display, status, added, deleted, binary}],
 total, added, deleted}
```

| 字段 | 含义 |
|---|---|
| `path` | 相对仓库 |
| `display` | 相对工作区根；在其之上为 `../x` |
| `after` | 该轮结束时会话的消息数；Web UI 放置卡片的位置 |

## 快照

| 项 | 契约 |
|---|---|
| 仓库 | 不被改动 |
| tree 的存放 | 仓库 index 的副本 + 私有对象目录（`GIT_OBJECT_DIRECTORY`）；仓库的对象作为只读 alternate |
| index 的副本 | 保留原文件的修改时间：git 据此重读与 index 同一秒内修改的文件 |
| `.gitignore` | 生效；被忽略的文件不列出 |
| 工作区不在 git 仓库内 | 无摘要 |
| 该轮没有改动 | 无摘要 |
| diff | 仅在本进程运行期间存在 |
| 摘要 | 持久化在 `ctx.store` |

## `git.py`

| 名称 | 契约 |
|---|---|
| `Repo` | `top`（工作树）、`objects`（对象目录）、`index`（index 文件） |
| `GitError` | 一条 git 命令失败或超时 |
| `parse_unified` | unified diff 的 hunk |
