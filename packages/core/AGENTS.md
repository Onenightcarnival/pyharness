# pyxis-harness-core

内核：一切皆插件的 agent harness，基于 FastAPI、deepagents、LangGraph。模型适配器、工具、agent loop、持久化、HTTP API 都是插件。

| 项 | 值 |
|---|---|
| 分发包 | `pyxis-harness-core` |
| 模块 | `pyxis_harness` |
| 命令 | `pyh`（`pyxis_harness.cli:main`） |
| 插件 entry point | 无 |
| entry point 组 | `pyxis_harness.plugins`、`pyxis_harness.bundles` |
| 数据根 | `$PYH_HOME`（默认 `~/.pyharness`） |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 公开名称 |
| `context.py` | 服务容器、注册、`Service` |
| `events.py` | 类型化事件，分发模式随声明固定 |
| `config.py` | 组合树、分层 patch、插值 |
| `plugin.py` | 插件形式、entry point 发现、bundle 加载 |
| `loader.py` | 按依赖启动、卸载 |
| `harness.py` | 进程内 harness：组合、启动、就绪、停止 |
| `lifecycle.py` | hold、重启、代与代之间的交接 |
| `profile.py` | harness home 中的 profile |
| `credentials.py` | 按名称引用的凭据库 |
| `resources.py` | 模块旁的 TOML 数据与提示词文件 |
| `manage.py` | 事务式 profile 变更 |
| `preflight.py` | 预检：独立进程中试启动 |
| `worker.py`、`supervisor.py` | 进程模型 |
| `cli.py` | `pyh` 命令行 |
| `config.toml` | `pyxis_harness` 的数据；每个模块一张表；`package_toml(__file__)` 加载 |

## Context（`context.py`）

每个插件收到一个 `Context`：服务容器。

| 概念 | 契约 |
|---|---|
| 服务 | 稳定 key 下的对象（`ctx.tools`）；消费方按 key 查找 |
| `ctx.<key>` | 可读的 key：插件 `inject` 里的、插件自己提供的、内核提供的（`lifecycle`、`events`、`profile`、`loader`）；其余抛 `AttributeError` |
| `ctx.get(key, default)` | 任意可见服务；用于可选服务 |
| host context | `Harness.ctx`：可读全部服务 |
| 注册 | `provide`、`on`、`effect`、`enter`、`on_dispose`；归属于插件 |
| 卸载 | 插件的注册逆序撤销 |
| 调用方 | `Service` 方法内，`self.caller` 是调用方插件的 context：普通方法、协程、生成器、异步生成器的每一步都成立 |
| `ctx.on(name, fn)` | 返回该监听的 disposer；`@ctx.on(name)` 返回被装饰的函数 |
| 根 | `Root`：全部 context 共享的事件总线、lifecycle、变量、profile、host context |

## 事件（`events.py`）

每个事件一个分发模式，由 `EventBus.define` 固定。

| 分发 | 抛出 |
|---|---|
| 未声明的事件 | `UndeclaredEventError` |
| 与声明模式不符的方法 | `EventModeError` |

| 模式 | 等待 | 顺序 | 结果 | 监听者异常 |
|---|---|---|---|---|
| `emit` | 否 | 注册顺序 | 无；异步监听者作为任务运行 | 记录日志 |
| `parallel` | 是 | 并发 | 无 | 记录日志 |
| `serial` | 是 | 注册顺序 | 第一个非 `None` 结果，随即停止 | 抛出 |
| `series` | 是 | 注册顺序 | 无；全部监听者运行 | 抛出 |
| `bail` | 否 | 注册顺序 | 第一个非 `None` 结果；仅同步监听者 | 抛出 |
| `waterfall` | 是 | 外层优先 | 链的返回值 | 抛出 |

waterfall 监听者 `listener(*args, next)`：

| 写法 | 效果 |
|---|---|
| `await next()` | 运行链的其余部分，返回其结果 |
| `await next(*new_args)` | 以新参数运行链的其余部分 |
| 不调用 `next` 直接返回 | 链在此结束 |

## 组合（`config.py`）

组合树在启动时从空列表起，依次应用各层：

| 顺序 | 层 |
|---|---|
| 1 | profile 的 bundle：`profile.yaml` 的 `bundles`（按其顺序），再是内置 bundle（`builtin: true`），再是未列入 `disabled` 的可选 bundle（`optional: true`） |
| 2 | profile patch |
| 3 | home patch |
| 4 | `--patch` 覆盖层 |

每层是一组按条目 `id` 寻址的 patch 操作：

| `id` | 操作 |
|---|---|
| 已存在 | 替换操作给出的字段（`name`、`config`、`disabled`、`required`、`isolate`、`children`）；`config` 整体替换，`merge: true` 时深合并 |
| 已存在 | `remove: true` 删除条目 |
| 不存在 | 插入条目（带 `name` 或 `children`）：末尾，或 `parent` / `before` / `after` 指定的位置 |

## 插件（`plugin.py`）

| 插件形式 | 契约 |
|---|---|
| 模块，或带 `apply` 的对象 | `apply(ctx[, config])`；可选 `name`、`inject`、`Config`、`doc` |
| `pyxis_harness.Service` 子类 | 在 `key` 下提供一个服务 |
| `define_plugin` 的返回值 | 属性同模块形式 |

| 属性 | 含义 |
|---|---|
| `inject` | 插件启动前必须存在的服务 key；`ctx.<key>` 只对这些 key 开放 |
| `Config` | pydantic 模型；校验条目的 `config` |
| `doc` | 一行描述；`Service` 子类取类的文档字符串 |

| `PluginSpec` 的位置信息 | 值 |
|---|---|
| `package_dir` | 插件模块所在目录 |
| `docs` | 包的 `AGENTS.md`：模块目录内（已安装的 wheel），否则上一级 `pyproject.toml` 旁（源码检出）；没有时为 `None` |
| `package_root(package_dir)` | 包的文件所在目录：`AGENTS.md` 所在的目录，没有时为模块目录 |

| entry point 组 | 内容 | 引用方式 |
|---|---|---|
| `pyxis_harness.plugins` | 插件 | 条目的 `name`：entry point 名，或 `module[:attr]` |
| `pyxis_harness.bundles` | bundle（组合层） | `profile.yaml` 中的 bundle 名 |

## Loader（`loader.py`）

组合树 → 运行中的插件。

| 阶段 | 行为 |
|---|---|
| resolve | 导入每个启用的插件，校验其 config；出错 → `FAILED` |
| start | 条目的 `inject` key 全部在其 scope 可见时启动 |
| order | 就绪条目之间：配置顺序 |
| pending | 所需服务始终不出现的条目停在 `PENDING`；启动继续 |
| failure | `apply` / `start` 出错：撤销已做的注册 → `FAILED` |
| required | `required: true` 的条目缺席 → `Harness.start` 抛 `BootError`；预检把它列入 `errors` |
| teardown | 启动顺序的逆序；每个插件的注册逆序撤销 |

`required` 条目缺席（`Loader.down`）：状态为 `FAILED`，或因所需服务始终不出现而停在 `PENDING`。

| 运行 | `required` 条目缺席 |
|---|---|
| 启动（worker、`async with Harness`） | `BootError` |
| 预检 | 列入 `errors`；变更被拒绝 |
| `Harness(partial=True)`：有意关闭部分条目的运行（`pyh exec` 关闭 `http`） | 不检查 |

## Harness（`harness.py`）

| 使用方 | 运行的阶段 |
|---|---|
| worker | start → ready → serve → started → stop |
| 预检 | start → ready → stop |
| `pyh exec`、测试 | `async with`：start → ready → serve → started → stop |

```python
async with Harness(Profile("web")) as h:
    agents = h.get("agents")
```

## Profile（`profile.py`）

profile：harness home 中具名、持久的装配。harness home：`$PYH_HOME`，默认 `~/.pyharness`。

| 路径 | 内容 |
|---|---|
| `$PYH_HOME/harness.patch.yaml` | home patch；作用于每个 profile |
| `$PYH_HOME/profiles/<name>/profile.yaml` | 有序的 bundle 列表 |
| `$PYH_HOME/profiles/<name>/harness.patch.yaml` | profile patch；`plugin_manager` 与 settings API 写入 |
| `$PYH_HOME/profiles/<name>/credentials.yaml` | 凭据库（0600）；patch 按名称引用其中的值 |
| `$PYH_HOME/profiles/<name>/site/` | 安装进该 profile 的 bundle（`pip --target`） |
| `$PYH_HOME/profiles/<name>/data/` | SQLite 的默认位置 |
| `$PYH_HOME/profiles/<name>/runtime/` | 当前代的 ready 标记、交接文件、last-known-good、锁 |
| `~/Documents/pyharness/<name>/` | `Profile.documents`：用户可见的文件，在 home 之外；插件各占一个子目录 |

## 凭据（`credentials.py`）

| 项 | 契约 |
|---|---|
| 配置 | 只写凭据的名称（`api_key_env: OPENAI_API_KEY`）；密钥值不写入配置 |
| 值 | 在环境变量或凭据库中 |

| 引用的解析顺序 | 来源 |
|---|---|
| 1 | 同名环境变量 |
| 2 | profile 目录下的 `credentials.yaml`（0600） |

## 包内数据文件（`resources.py`）

随包分发的数据文件：模块旁的 TOML 表。

| 函数 | 文件 | 用途 |
|---|---|---|
| `package_toml(file, name)` | `config.toml` | 数据表：端点、目录、类型映射 |
| `package_prompts(file, name)` | `prompts.toml` | 模型可见的文本；字符串叶子去除首尾空白 |

| 提示词文本 | 写法 |
|---|---|
| 占位符 | `string.Template` 语法：`${name}` |
| 字面 `$` | `$$` |

## 生命周期（`lifecycle.py`）

| 退出码 | 含义 |
|---|---|
| `0` | 停止 |
| `RESTART_EXIT_CODE`（75） | 启动下一代 |
| `BOOT_FAILURE_EXIT_CODE`（3） | 启动失败 |

重启：

1. `Lifecycle.request_restart` 记录原因与待续跑会话。
2. 每个 `Lifecycle.hold` 都释放后，进程退出 75。
3. 重启挂起期间 `Lifecycle.accepting_work` 为 `False`。

交接文件（runtime 目录）：

| 文件 | 写入方 | 内容 |
|---|---|---|
| `resume.json` | `request_restart` | 原因、待续跑会话 |
| `rollback.json` | supervisor，启动失败之后 | 失败的代、错误 |

| 步骤 | 方法 | 效果 |
|---|---|---|
| 读取 | `handoff` | 两个文件各读一次；文件保留 |
| 提交 | `commit_handoff` | 本代启动成功之后，worker 删除两个文件 |
| 放弃 | `discard_pending_restart` | 非重启退出：删除本代的 `resume.json` |

## Worker（`worker.py`）

worker 进程：一代 harness。`python -m pyxis_harness.worker --profile web`

1. 组合 profile；启动全部插件
2. `app/ready`、`app/serve`
3. 保存 last-known-good，写 ready 标记，提交交接（受 supervisor 管理时）
4. `app/started`；运行至停止

| 信号 | 效果 |
|---|---|
| SIGINT、SIGTERM | 停止，退出 0 |
| SIGHUP | hold 全部释放后重启，退出 75 |

退出码：见「生命周期」。

## Supervisor（`supervisor.py`）

一次运行一代 worker；重启与回滚归 supervisor。

| worker 结果 | supervisor 动作 |
|---|---|
| 写出 ready 标记 | 记录 `ready` |
| 退出 75 | 启动下一代 |
| 退出 0，或收到 SIGINT / SIGTERM | 停止 |
| 启动失败（阶段抛出异常，或 `required` 条目缺席） | 恢复 last-known-good，写 `rollback.json`，再启动；仅一次 |
| 启动失败，无可恢复配置 | 退出 3 |
| 启动中被转发的信号终止 | 再启动；不回滚 |
| 启动后其他退出 | 退避重启；`crash_window` 内超过 `max_crashes` 次则停止 |

| supervisor 收到的信号 | 效果 |
|---|---|
| SIGINT、SIGTERM | 停止 worker，退出 0 |
| SIGHUP | 转发；worker 在 hold 全部释放后重启 |

事件追加写入 `runtime/supervisor.log.jsonl`。

## 预检（`preflight.py`）

在独立进程中启动候选配置。

| 步骤 | 运行 |
|---|---|
| 导入插件、校验 config | 是 |
| 启动全部插件 | 是 |
| `app/ready` | 是 |
| `app/serve`（端口、续跑的工作） | 否 |
| 卸载 | 是 |

报告：`ok`、`errors`（stage、entry、error）、`pending`、`warnings`、`entries`。

## Profile 变更（`manage.py`）

CLI 与 `plugin_manager` 工具共用。每次变更是一个事务：

1. 快照：profile 文件；安装、卸载时另含 `site/`
2. 变更：安装分发包（本地 bundle 目录，或索引中的包）或移除分发包，改 `profile.yaml` 或 profile patch
3. 在新解释器中预检结果配置
4. 结果：

| 预检 | 效果 | `application` |
|---|---|---|
| 出现新的失败 | 恢复快照：文件与 `site/` | `rejected` |
| 无新的失败 | 保留变更 | `saved` |

`saved` 的变更随下一代生效。

| 锁 | 范围 |
|---|---|
| `asyncio.Lock` | 同一进程内的变更 |
| profile 文件锁 | 跨进程的变更；轮询，不阻塞事件循环 |
