# pyharness-terminal

`ctx.terminal`：agent 每会话一个持久 shell（`bash` 工具）、后台任务（background jobs）、Web UI 右侧栏的 PTY 终端。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | 包契约文档字符串；从子模块导出 `__all__` |
| `shell` | `END_MARK`；`ShellSession`：一个长生命周期 bash 进程，命令逐条执行并读回退出码与工作目录；`clip` 截断输出 |
| `jobs` | `Job`（命令、日志文件、状态、`describe` / `read`）；`JobRegistry`：`start` / `get` / `list` / `kill` / `wait` / `close` |
| `pty` | `Terminal`：PTY 上的交互 shell，scrollback 缓冲与订阅队列，`open` / `write` / `resize` / `close`；`pty_available` |
| `tools` | `_thread_id`；LangChain 工具工厂 `bash_tool`、`background_tool`、`job_tools` |
| `routes` | 请求模型 `NewTerminal`、`Resize`；`make_router`：状态、任务、终端路由与终端 WebSocket |
| `service` | `Config`、`TerminalService`：shell 池、任务启动、终端打开 / 关闭、工具与路由注册、`status` |
| `client.js` | 浏览器模块 `terminal`：右侧栏标签 `terminal`（xterm.js 渲染的 WebSocket PTY，加载失败时为行终端）与 `jobs`（后台任务及其日志） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `Config` | 模型 | 服务配置；字段见「服务」 |
| `TerminalService` | 类 | `Service` 子类，key `terminal`；entry point `pyharness-terminal` |
| `ShellSession` | 类 | `ShellSession(shell, cwd, env=None)`：`run(command, timeout)` → `{"output", "exit_code", "cwd", "timed_out"}`；`close()` |
| `Job` | 类 | 后台任务：`id`、`name`、`command`、`cwd`、`log`、`status`（`running` / `exited` / `failed` / `killed`）、`describe()`、`read(tail_lines=, since=)` |
| `JobRegistry` | 类 | `JobRegistry(log_dir, shell)`：`start(command, cwd, *, session_id=, name=)` → `Job`；`get` / `list(session_id=)` / `kill` / `wait(job, timeout)` / `close` |
| `Terminal` | 类 | `Terminal(id, shell, cwd, cols, rows, scrollback, title=None)`：`open` / `write` / `resize` / `subscribe` / `unsubscribe` / `close` / `describe`；`alive` |
| `clip` | 函数 | `clip(text, limit)`：超限时保留首尾各 `limit // 2` 字符，中间标注省略的字符数 |
| `pty_available` | 函数 | POSIX 且可导入 `pty` 时为 `True` |

## 服务

| 项 | 值 |
|---|---|
| key | `terminal` |
| inject | `tools`、`http` |
| `shell_tool` | `True`；注册 `bash` 工具 |
| `shell` | `"bash"`；持久 shell 的可执行文件（bash 语义） |
| `timeout` | `120`（≥1）；`bash` 默认超时（秒） |
| `max_timeout` | `900`（≥1）；超时与 `job_output` 等待的上限（秒） |
| `max_output_chars` | `16000`（≥1000）；工具返回的输出上限 |
| `approval` | `{"allowed_decisions": ["approve", "reject"]}`；`bash` 与 `run_in_background` 的审批设置 |
| `jobs_tool` | `True`；注册 `run_in_background` 与 `job_*` 工具 |
| `job_tail_lines` | `200`（≥10）；`job_output` 默认行数 |
| `terminal_tab` | `True`；允许 PTY 终端 |
| `terminal_shell` | `None`；PTY 终端的交互 shell，默认 `$SHELL`，再默认 `/bin/bash` |
| `scrollback_bytes` | `200000`（≥10000）；终端 scrollback 缓冲 |
| `max_shells` | `16`（≥1）；shell 池上限，超出时关闭最久未用的 |
| start | 注册工具；挂载 `/api` 路由；有 `webui` 时注册 `client.js`；监听 `app/stopping` → `stop` |
| stop | 关闭全部 shell、终端与后台任务 |

## 事件 / 工具 / 路由 / Web UI

| 事件 | 角色 | 行为 |
|---|---|---|
| `app/stopping` | 监听 | `stop()` |

| 工具 | 审批 | 标签 | 行为 |
|---|---|---|---|
| `bash(command, timeout=None)` | `config.approval` | `shell` | 在会话（thread id）的持久 shell 中运行；返回截断后的输出与退出码、cwd；超时杀掉 shell，下次调用重启 |
| `run_in_background(command, name=None)` | `config.approval` | `shell`、`jobs` | 在 shell 当前目录启动 `bash -c` 后台任务；返回 `job_id`、`name`、`cwd`、`status`、`log` 的 JSON |
| `job_output(job_id, tail_lines=None, wait=False, timeout=60)` | 无 | `jobs` | 任务状态与末尾输出；`wait` 时阻塞至结束或超时 |
| `job_list()` | 无 | `jobs` | 全部任务的 id、状态、名称、开始时间 |
| `job_kill(job_id)` | 无 | `jobs` | 停止运行中的任务（SIGTERM，3 秒后 SIGKILL） |

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/terminal/status` | `shells`、`jobs`、`terminals` 计数、`pty`、`terminal_shell` |
| GET | `/api/jobs?session=` | 任务列表（`describe()`），按开始时间倒序 |
| GET | `/api/jobs/{job_id}?tail=200` | 任务描述与末尾输出（1–5000 行）；不存在 → 404 |
| DELETE | `/api/jobs/{job_id}` | 停止任务；`killed` 与描述；不存在 → 404 |
| GET | `/api/terminals` | 终端列表与 `available` |
| POST | `/api/terminals` | `NewTerminal`（`workspace`、`cols`、`rows`、`title`）→ 终端描述；禁用或无 PTY → 409，工作区无效 → 422 |
| POST | `/api/terminals/{terminal_id}/resize` | `Resize`（`cols` 2–500、`rows` 1–300）→ 终端描述；不存在 → 404 |
| DELETE | `/api/terminals/{terminal_id}` | 关闭终端 → `{"closed": true}`；不存在 → 404 |
| WebSocket | `/api/terminals/{terminal_id}/ws` | 先发 scrollback；二进制帧为终端输入 / 输出；文本帧为 JSON 控制（`resize`、`input`），非 JSON 原样输入；退出时发 `{"type": "exit", "code"}`；不存在 → 关闭码 4404 |

| Web UI slot | key | 位置 |
|---|---|---|
| `rightbar.tabs` | `terminal` | guide order 30 |
| `rightbar.tabs` | `jobs` | guide order 40 |

## 数据

| 项 | 内容 |
|---|---|
| 任务日志 | `<profile.runtime>/jobs/<8 位 hex>.log`（无 profile：`~/.pyharness/runtime/jobs/`）；stdout 与 stderr 合流 |
| shell 进程 | `bash --noprofile --norc`，工作区根目录启动，独立进程组，stdin 为 `/dev/null`；环境继承进程并设 `TERM=dumb`、`PS1=`、`PAGER=cat`、`GIT_PAGER=cat` |
| 终端进程 | `TERM=xterm-256color`、`COLORTERM=truecolor`、`LANG`；bash / zsh / sh / fish 以 `-l` 启动；子进程为会话首进程并持有控制终端 |
| `Job.describe()` | `id`、`name`、`command`、`cwd`、`session_id`、`status`、`exit_code`、`started_at`、`ended_at`、`pid` |
| `Terminal.describe()` | `id`、`title`、`cwd`、`cols`、`rows`、`alive`、`exit_code`、`created_at`、`pid` |
