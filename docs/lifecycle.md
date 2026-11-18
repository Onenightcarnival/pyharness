# 生命周期

配置在启动时组合一次。变更经新一代 worker 进程生效。

| 角色 | 进程 | 职责 |
|---|---|---|
| supervisor | `pyh run` | 一次运行一代 worker；重启、回滚 |
| worker | `python -m pyharness.worker` | 一代 harness：组合、启动插件、提供服务 |
| 预检 | 独立解释器 | 启动候选配置，不对外服务 |

状态在进程外：

| 状态 | 位置 |
|---|---|
| 会话历史 | LangGraph thread，`ctx.checkpointer` |
| 会话元数据 | `ctx.store`，命名空间 `("pyharness", "sessions")` |
| 交接、last-known-good | `runtime/` |

## 一代 worker

1. 组合 profile，启动全部插件
2. `app/ready`，`app/serve`
3. 保存 last-known-good，写 ready 标记，提交交接文件（受 supervisor 管理时）
4. `app/started`；运行至停止

| 退出码 | 含义 |
|---|---|
| `0` | 停止 |
| `75` | 启动下一代 |
| `3` | 启动失败 |

| 信号 | 效果 |
|---|---|
| SIGINT、SIGTERM | 停止，退出 0 |
| SIGHUP | 活动 hold 全部释放后重启，退出 75 |

停止顺序：`app/stopping`（取消运行中的轮次；HTTP 停止接收，进行中的请求最多 `shutdown_timeout` 秒）→ 插件逆序卸载。

## 重启

1. `ctx.lifecycle.request_restart(reason, resume=[session])`：记录原因与待续跑会话，写 `resume.json`。
2. 每个运行中的轮次持有 `lifecycle.hold()`；全部释放后 worker 退出 75。
3. 重启挂起期间 `accepting_work` 为 `False`：新运行被拒绝，API 返回 503（`Retry-After: 2`）。

SIGHUP（`pyh restart`、`pyh plugin ...`）走同一路径，不触发回滚。

## supervisor

| worker 结果 | supervisor 动作 |
|---|---|
| 写出 ready 标记 | 记录 `ready` |
| 退出 75 | 启动下一代 |
| 退出 0，或 supervisor 收到 SIGINT / SIGTERM | 停止 |
| 启动失败 | 恢复 last-known-good，写 `rollback.json`，再启动一次 |
| 启动失败，无可恢复配置 | 退出 3 |
| 启动中被 supervisor 转发的信号终止 | 再启动；不回滚 |
| 启动后其他退出 | 退避重启；`crash_window` 60 秒内超过 `max_crashes` 3 次则放弃 |

| 参数 | 默认 |
|---|---|
| `--boot-timeout` | 120 秒；超时 = 启动失败 |

事件日志：`runtime/supervisor.log.jsonl`。

## 预检

| 步骤 | 运行 |
|---|---|
| 导入插件、校验配置 | 是 |
| 启动全部插件 | 是 |
| `app/ready` | 是 |
| `app/serve`（端口、续跑） | 否 |
| 卸载 | 是 |

报告字段：`ok`、`errors`（stage、entry、error）、`pending`、`warnings`、`entries`。

## 变更事务

CLI 与 `plugin_manager` 工具共用 `pyharness.manage`。

1. 快照：profile 文件；安装、卸载时另含 `site/`
2. 变更：安装或移除分发包，改 `profile.yaml` 或 profile patch
3. 在新解释器中预检结果配置
4. 结论：

| 预检 | 效果 | `application` |
|---|---|---|
| 出现新的失败 | 恢复快照：文件与 `site/` | `rejected` |
| 无新的失败 | 保留变更 | `saved` |

| 锁 | 范围 |
|---|---|
| `asyncio.Lock` | 进程内 |
| profile 文件锁 | 跨进程；轮询，不阻塞事件循环 |

`saved` 的变更在下一代生效。

## 交接与续跑

| 文件 | 写入方 | 内容 |
|---|---|---|
| `resume.json` | `request_restart` | 原因、待续跑会话 |
| `rollback.json` | supervisor，启动失败之后 | 失败的代、错误 |

| 步骤 | 时机 | 效果 |
|---|---|---|
| 读取 | 启动时 | 两个文件各读一次，文件保留 |
| 提交 | 本代启动成功之后 | worker 删除两个文件 |
| 放弃 | 非重启退出 | 删除本代写出的 `resume.json` |

- 续跑：受 supervisor 管理的一代在 `app/started` 时，向每个待续跑会话发送一条续跑消息。
- 回滚发生时：交接文件留给回滚后的一代；续跑消息附失败的代与错误。
- 不受 supervisor 管理的 harness（`pyh exec`、嵌入、测试）不读取、不删除交接文件。

续跑消息：

```
[PyxisHarness] Restarted into generation {generation}.
Reason: {reasons}.
Rollback: generation {gen} failed to boot ({err}). The previous configuration is active; the change is not applied.
Task: the task in progress continues. Tools of newly enabled plugins are available; harness_inspect shows the active plugins.
```

`Rollback` 行仅在回滚时出现。

## 边界

- 长连接资源（终端进程、MCP 连接、后台子 agent）不跨代保留。
- last-known-good 包含 `profile.yaml` 与 profile patch；不含 `site/` 中的代码、home patch、`--patch` 覆盖层。
- 已启用 bundle 的升级：预检通过、真实启动在 `app/serve` 失败时，supervisor 回滚配置，`site/` 中的新代码保留。
