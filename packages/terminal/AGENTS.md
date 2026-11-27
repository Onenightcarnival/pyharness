# pyxis-harness-terminal

agent 的 shell 工具、后台作业、Web UI 的 PTY 终端。

| 项 | 值 |
|---|---|
| 条目 | `terminal`（`base` bundle） |
| 服务 | `TerminalService`，`ctx.terminal` |
| 注入 | `tools`、`http` |
| 路由前缀 | `/api` |
| 数据 | `<profile runtime>/jobs/`：作业日志 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `TerminalService`：命令、作业、终端、工具与路由注册 |
| `config.py` | 插件配置 |
| `shell.py` | `Shell`：方言、可执行文件、argv、环境；PowerShell 的解析顺序；输出的解码与截尾 |
| `process.py` | `Tree`：一条命令的进程树；启动、终止 |
| `win32.py` | Windows 的 Job Object 与 `taskkill` |
| `jobs.py` | `Job`、`JobRegistry`：每条命令一个作业，输出写入日志文件 |
| `pty.py` | Web UI 的 PTY 终端：每个终端一个交互式 shell、一个回滚缓冲区、订阅者队列 |
| `tools.py` | 终端服务之上的 LangChain 工具：`bash` / `pwsh`、`job_*` |
| `routes.py` | HTTP 路由：终端状态、作业、终端、终端 WebSocket |
| `prompts.toml` | 模型可见文本；`pyxis_harness.package_prompts(__file__)` 加载 |
| `client.js` | 浏览器模块 |

## 工具

| 工具 | 契约 |
|---|---|
| `bash`（Windows 之外） | `bash -c <命令>` |
| `pwsh`（Windows） | `<PowerShell> -NoLogo -NoProfile -NonInteractive -Command <命令>` |
| `job_output`、`job_list`、`job_kill` | 后台作业的输出、列表、终止 |

模型只见到 `bash` 与 `pwsh` 中的一个：`dialect` 配置，否则随平台。

| shell 工具的参数 | 契约 |
|---|---|
| `command` | 命令行 |
| `timeout` | 等待秒数；默认 `timeout`，上限 `max_timeout` |
| `workdir` | 起始目录；默认会话的 workspace 根；相对路径相对该根 |
| `run_in_background` | 立即返回作业 id；不设超时（`jobs_tool` 关闭时无此参数） |
| `name` | 后台作业的标签 |

| 项 | 规则 |
|---|---|
| `shell` 标签 | shell 工具携带；agent loop 在只读模式下不提供它 |
| `approval` | 把守 shell 工具：workspace-write 模式下弹出审批；full access 下无 |

## 命令

| 项 | 契约 |
|---|---|
| 进程 | 每次调用一个新的 shell 进程；目录与变量不跨调用保留 |
| 作业 | 每条命令从启动起就是一个作业；前台调用等待它 |
| stdin | 空 |
| 输出 | stdout 与 stderr 合并写入作业日志；按 UTF-8 读，换行归一为 `\n` |
| 环境 | 进程环境，加 `NO_COLOR=1`、`PAGER=cat`、`GIT_PAGER=cat`；bash 另加 `TERM=dumb` |
| 取消调用 | 终止该命令 |

| 前台结果 | 返回 | 作业与日志 |
|---|---|---|
| 超时内结束 | 输出与标记 | 一并删除 |
| 输出超过 `max_output_chars` | 输出的尾部；`[output truncated; full output: <日志>]` | 作业删除，日志保留 |
| 到达超时，`promote_on_timeout` 且有作业工具 | 已有输出；`[still running after Ns; moved to background job <id>]` | 转为后台作业 |
| 到达超时，其余情况 | 已有输出；`[timed out after Ns; the command was stopped]` | 终止后删除 |

| 标记 | 条件 |
|---|---|
| `(no output)` | 没有输出 |
| `[exit code: N]` | 退出码非 0 |
| `[killed by signal: NAME]` | 被信号结束（POSIX） |
| `[stopped: …]` | 在调用之外被终止（作业列表里的停止） |

## PowerShell

| 项 | 契约 |
|---|---|
| 可执行文件 | `pwsh` 配置 → `%ProgramFiles%\PowerShell\7\pwsh.exe` → PATH 各目录下的 `pwsh.exe` → Windows PowerShell 5.1 → PATH 上的 `pwsh` |
| 输出编码 | 每条命令前置一句，把输出固定为 UTF-8 |
| 不是 UTF-8 的输出字节 | 按 OEM 代码页读 |
| profile | 不加载 |

## 进程树

| 平台 | 归属 | 终止 |
|---|---|---|
| POSIX | 新会话，命令是进程组组长 | 对进程组 SIGTERM；`grace` 秒后对剩余成员 SIGKILL |
| Windows | Job Object（关闭句柄即结束成员）；无窗口 | 结束 Job 的全部进程；没有 Job 时 `taskkill /PID <pid> /T /F` |

| Windows | 说明 |
|---|---|
| 没有温和的一档 | 控制台进程不响应不带 `/F` 的终止 |
| 被终止的命令 | 退出码 1，没有信号 |
| 归属的建立 | 进程启动之后；在此之前由它启动的进程不在 Job 中 |
| worker 被强制结束 | 系统关闭句柄，各 Job 的进程随之结束 |

## 路由

| 对象 | 方法 | 路径 |
|---|---|---|
| 终端状态 | GET | `/terminal/status` |
| shell 工具的设置 | GET、PUT | `/terminal/settings` |
| 作业 | GET | `/jobs` |
| 作业 | GET | `/jobs/{id}` |
| 作业 | DELETE | `/jobs/{id}` |
| 终端 | POST | `/terminals` |
| 终端 | GET | `/terminals` |
| 终端 | DELETE | `/terminals/{id}` |
| 终端 | WebSocket | `/terminals/{id}/ws`；二进制帧：字节；文本帧：JSON 控制 |

## PTY 终端

| 项 | 契约 |
|---|---|
| 用途 | 右侧栏终端标签页的 PTY 会话 |
| 依赖 | `pty`（POSIX） |
| 其他平台 | 终端标签页报告自身不可用 |

## 设置

| 字段 | 生效 |
|---|---|
| `timeout`、`max_output_chars`、`promote_on_timeout` | 立即：下一条命令；工具重新登记，参数说明随之更新 |
| `dialect`、`shell`、`pwsh` | 写入 profile 补丁；改变了生效的 shell 时请求重启 |

| 拒绝（422） | 条件 |
|---|---|
| `timeout` | 大于 `max_timeout` |
| 可执行文件 | 给出的路径，或将要生效的 shell，在本机上找不到 |

## 浏览器模块（`client.js`）

| 右侧栏标签页类型 | 内容 |
|---|---|
| `terminal` | WebSocket 上的 PTY；xterm.js 加载成功时用它渲染，否则为纯行终端 |
| `jobs` | 后台作业及其日志 |

设置分区「Shell 工具」（`settings.sections`）：上表的各字段，及当前生效的 shell。
