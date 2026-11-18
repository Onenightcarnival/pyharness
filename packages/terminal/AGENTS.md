# pyxis-harness-terminal

agent 的每会话持久 shell、后台作业、Web UI 的 PTY 终端。

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
| `service.py` | `TerminalService`：每会话的 shell、作业、终端、工具与路由注册 |
| `config.py` | 插件配置 |
| `shell.py` | 每会话的持久 shell：一个 bash 进程；命令逐条运行，读回退出码与 cwd |
| `jobs.py` | 后台作业：输出写入日志文件的 `bash -c` 进程，及其注册表 |
| `pty.py` | Web UI 的 PTY 终端：每个终端一个交互式 shell、一个回滚缓冲区、订阅者队列 |
| `tools.py` | 终端服务之上的 LangChain 工具：`bash`、`run_in_background`、`job_*` |
| `routes.py` | HTTP 路由：终端状态、作业、终端、终端 WebSocket |
| `prompts.toml` | 模型可见文本；`pyharness.package_prompts(__file__)` 加载 |
| `client.js` | 浏览器模块 |

## 工具

| 工具 | 契约 |
|---|---|
| `bash` | 在会话的持久 shell 中运行命令 |
| `run_in_background` | 启动 `bash -c`，输出写入日志文件 |
| `job_output`、`job_list`、`job_kill` | 后台作业的输出、列表、终止 |

| 项 | 规则 |
|---|---|
| `shell` 标签 | `bash`、`run_in_background` 携带；agent loop 在只读模式下不提供它们 |
| `approval` | 把守 `bash` 与 `run_in_background`：workspace-write 模式下弹出审批；full access 下无 |

## 持久 shell

| 项 | 契约 |
|---|---|
| 进程 | 每个 agent 会话（thread id）一个 bash 进程 |
| 起始目录 | workspace 根 |
| 状态 | 工作目录与环境变量在调用之间保留 |
| stdin | `/dev/null` |
| 超时 | 杀掉并重启 shell |

## 路由

| 对象 | 方法 | 路径 |
|---|---|---|
| 终端状态 | GET | `/terminal/status` |
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

## 浏览器模块（`client.js`）

| 右侧栏标签页类型 | 内容 |
|---|---|
| `terminal` | WebSocket 上的 PTY；xterm.js 加载成功时用它渲染，否则为纯行终端 |
| `jobs` | 后台作业及其日志 |
