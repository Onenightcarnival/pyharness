# pyharness-core

内核（kernel）：服务容器（service container）、类型化事件（typed events）、分层组合（layered composition）、Loader、代际生命周期（generation lifecycle）、profile、CLI；模型适配、工具、agent loop、持久化与 HTTP API 都是插件。

## 模块

| 模块 | 职责 |
|---|---|
| `context` | 每插件一个 `Context`：服务的提供与查找、事件注册与分发、可逆副作用；`Service` 基类；`Scope` 服务命名空间；`_Bound` 代理绑定 `Service.caller` |
| `events` | `EventBus`：声明事件及其分发模式，`emit` / `parallel` / `serial` / `series` / `bail` / `waterfall` |
| `config` | 组合树 `Entry` / `PatchOp`、按 `id` 寻址的 patch 操作、`compose`、`${...}` 插值、YAML 读写 |
| `plugin` | 插件形式识别（`to_spec`）、entry point 发现、`load_plugin` / `load_bundle`、`BundleInfo` |
| `loader` | `Loader`：resolve → 依赖驱动启动 → 逆序卸载；`EntryRuntime`、`EntryState`；`Root` 进程级状态与内核事件声明 |
| `lifecycle` | `Lifecycle`：活动 hold、重启请求、退出码、交接文件 `resume.json` / `rollback.json` |
| `harness` | `Harness`：进程内组合并运行一代（start → ready → serve → started → stop）；`async with` 用法 |
| `profile` | `Profile`：harness home 下的具名 profile，清单、patch、site、快照、last-known-good、文件锁 |
| `credentials` | `CredentialStore`：按引用名查找凭据，环境变量优先于 `credentials.yaml`（0600） |
| `manage` | profile 变更事务：快照 → 变更 → 独立进程预检 → 保留或恢复；安装 / 卸载 / 启停 / 改配置 |
| `preflight` | 在独立解释器中试启动候选配置；`python -m pyharness.preflight` |
| `worker` | 一代 worker 进程：`python -m pyharness.worker`；信号、ready 标记、`boot-error.json`、`overlays.json` |
| `supervisor` | 一次运行一代 worker：重启、回滚、崩溃退避；`supervisor.log.jsonl`、`supervisor.pid`、`signal_restart` |
| `cli` | `pyh` 命令行：`init`、`run`、`dump-config`、`preflight`、`plugin`、`restart`、`exec` |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `BOOT_FAILURE_EXIT_CODE` | 常量 | `3`，启动失败 |
| `BUNDLE_GROUP` | 常量 | `"pyharness.bundles"` entry point 组 |
| `ConfigError` | 类 | 配置、patch 或插值错误；`ValueError` 子类 |
| `Context` | 类 | 插件的服务容器视图；未知属性解析为服务（`ctx.tools`） |
| `CredentialStore` | 类 | 凭据库：`get` / `describe` / `set` / `delete` / `names` |
| `Entry` | 模型 | 组合树条目：`id`、`name`、`config`、`disabled`、`isolate`、`children`、`source`；`extra="forbid"` |
| `EntryState` | 类 | `str` 枚举：`planned`、`pending`、`active`、`disabled`、`failed`、`stopped` |
| `EventModeError` | 类 | 声明或分发与事件模式矛盾 |
| `Harness` | 类 | 进程内 harness：`start` / `ready` / `started` / `stop`、`get`、`report`、`failed` |
| `Lifecycle` | 类 | `hold`、`request_restart`、`accepting_work`、`handoff` / `commit_handoff`、`describe` |
| `Loader` | 类 | `resolve` / `start` / `stop`、`get`、`snapshot`、`summary` |
| `PLUGIN_GROUP` | 常量 | `"pyharness.plugins"` entry point 组 |
| `PatchOp` | 模型 | patch 操作：`id`、`name`、`config`、`merge`、`disabled`、`isolate`、`children`、`remove`、`parent`、`before`、`after` |
| `PluginDef` | 类 | 以值定义的插件：`name`、`apply`、`inject`、`Config`、`doc` |
| `PluginError` | 类 | 插件导入或定义失败；子类 `PluginNotFound` |
| `Profile` | 类 | profile 目录、清单、patch、组合、快照、锁 |
| `RESTART_EXIT_CODE` | 常量 | `75`，启动下一代 |
| `Scope` | 类 | 服务命名空间；`isolate` 的 key 在组内独立 |
| `Service` | 类 | 在 `key` 下提供一个服务的插件基类：`start()`、`stop()`、`caller` |
| `ServiceConflict` | 类 | 目标 scope 已提供同名服务 |
| `ServiceNotFound` | 类 | scope 内不可见的服务 key；`LookupError` 子类 |
| `UndeclaredEventError` | 类 | 分发未声明的事件 |
| `define_plugin` | 函数 | `define_plugin(name, apply, *, inject=(), config=None, doc="")` → `PluginDef` |
| `unwrap` | 函数 | 去掉 `ctx.get()` 返回的绑定代理，得到原始 `Service` |

## 内核契约

### Context 与 Service

| API | 契约 |
|---|---|
| `ctx.provide(key, obj)` | 在 `scope.owner_scope(key)` 提供服务；重复 → `ServiceConflict`；返回 disposer |
| `ctx.get(key[, default], bind=True)` | 查找服务；缺失且无默认 → `ServiceNotFound`；`Service` 实例返回绑定 `caller` 的代理 |
| `ctx.has(key)`、`ctx.<key>` | 存在性；属性访问等同 `get`，缺失 → `AttributeError` |
| `ctx.define_event(name, mode, doc)` | 声明事件，归属本插件 |
| `ctx.on(name, fn, prepend=False)` | 监听；可作装饰器 |
| `ctx.emit` / `parallel` / `serial` / `series` / `bail` / `waterfall(..., final=)` | 分发 |
| `ctx.on_dispose(fn)` | 登记同步或异步 disposer；插件停止时运行 |
| `ctx.effect(setup)` | 运行 `setup()`，其返回的可调用对象作为 disposer；异步 setup → `TypeError` |
| `await ctx.enter(cm)` | 进入同步或异步上下文管理器；插件停止时退出 |
| `ctx.entry_id`、`ctx.plugin_name`、`ctx.logger`、`ctx.root`、`ctx.events`、`ctx.scope` | 身份与进程级对象；host 上下文的 `entry_id` 为 `"<host>"` |
| `Service` | 类属性 `key`、`name`、`inject`、`Config`；`cls(ctx, config)` → `await start()` → provide；卸载：撤回服务 → `await stop()` → 撤销 `start()` 内的注册 |
| `Service.caller` | 绑定调用内：调用方插件的 Context；其他情况：所有者的 Context |
| 内核服务 | `lifecycle`、`events`、`loader`、`profile`（有 profile 时）在根 scope 下由 `<core>` 提供 |

### 事件与分发模式

| 模式 | 等待 | 顺序 | 结果 | 监听者异常 |
|---|---|---|---|---|
| `emit` | 否 | 注册顺序 | 无；异步监听者作为任务运行 | 记录日志 |
| `parallel` | 是 | 并发 | 无 | 记录日志 |
| `serial` | 是 | 注册顺序 | 第一个非 `None` 结果，随即停止 | 抛出 |
| `series` | 是 | 注册顺序 | 无；全部监听者运行 | 抛出 |
| `bail` | 否 | 注册顺序 | 第一个非 `None` 结果；仅同步监听者 | 抛出 |
| `waterfall` | 是 | 外层优先 | 链的返回值；`listener(*args, next)` | 抛出 |

| 规则 | 结果 |
|---|---|
| 分发未声明事件 | `UndeclaredEventError` |
| 分发方法与声明模式不符 | `EventModeError` |
| 以不同模式再次声明 | `EventModeError`；同模式多声明方累加 `owners`，最后一个撤销时删除声明 |
| waterfall `await next()` / `await next(*new_args)` / 不调用 `next` | 运行其余链 / 以新参数运行 / 链在此结束 |

### 配置分层

| 层序 | 来源 |
|---|---|
| 1 | profile 的 bundle，按 `Profile.bundles()` 顺序（清单 `bundles` → `builtin: true` → 未列入 `disabled` 的 `optional: true`） |
| 2 | profile patch `profiles/<name>/harness.patch.yaml` |
| 3 | home patch `$PYH_HOME/harness.patch.yaml` |
| 4 | `--patch` 覆盖层，按给出顺序 |

| `id` | 字段 | 操作 |
|---|---|---|
| 已存在 | `name`、`config`、`disabled`、`isolate`、`children` | 替换给出的字段；`config` 整体替换，`merge: true` 时深合并；位置字段被忽略并告警 |
| 已存在 | `remove: true` | 删除条目 |
| 不存在 | `name` 或 `children` | 插入：默认末尾；`before` / `after` 定位，`parent` 追加进组；锚点不存在则追加到根并告警 |
| 不存在 | 无 `name` 与 `children` | 跳过并告警 |

| 校验 | 结果 |
|---|---|
| 重复 `id` | `ConfigError` |
| 既无 `name` 也无 `children` | `ConfigError` |

| 占位符 | 值 |
|---|---|
| `${env:NAME}` | 环境变量；未设置或空 → `""`；整串恰为一个未设置的 `${env:NAME}` → `None` |
| `${env:NAME:-default}` | 未设置时 `default`；默认值可嵌套 |
| `${profile}`、`${profile_dir}`、`${home}`、`${data_dir}`、`${runtime_dir}`、`${cwd}` | profile 变量；`cwd` 取参数、`PYH_CWD` 或当前目录 |
| 未知变量 | `ConfigError` |
| 替换结果 | 按字面使用，不再扫描 |

### 插件形式

| 形式 | 契约 |
|---|---|
| 模块或带 `apply` 的对象 | `apply(ctx[, config])`，同步或异步；可选 `name`、`inject`、`Config`、`doc` |
| `Service` 子类 | 在 `key` 下提供一个服务；无 `key` → `PluginError` |
| `define_plugin(...)` 结果 | 属性同模块形式 |
| `Config` | pydantic `BaseModel` 子类；否则 `PluginError`；无 `Config` 时 config 原样作 `dict` |

| entry point 组 | 内容 | 条目 `name` 的写法 |
|---|---|---|
| `pyharness.plugins` | 插件 | entry point 名，或 `module[:attr]` |
| `pyharness.bundles` | bundle（组合层） | `profile.yaml` 中的 bundle 名 |

| bundle 对象 | 解析 |
|---|---|
| 字符串 / `Path` | YAML 文件；缺失或为空 → `ConfigError` |
| 可调用对象 | 调用结果 |
| 列表 | `{"patch": list}` |
| 映射 | `title`、`description`、`patch`、`optional`、`builtin` |

### Loader

| 阶段 | 行为 |
|---|---|
| plan | 遍历树；组条目带 `isolate` 时创建子 `Scope`；`disabled` 条目及其组内条目 → `DISABLED` |
| resolve | 导入每个 `PLANNED` 条目并插值、校验 config；出错 → `FAILED`；成功 → `PENDING` |
| start | `inject` 全部在其 scope 可见的 `PENDING` 条目启动；就绪条目之间按配置顺序，每启动一个重新扫描 |
| pending | 依赖始终不出现 → 保持 `PENDING` 并记录 `missing`；启动继续 |
| failure | `apply` / `start` 出错：撤销已做的注册 → `FAILED` |
| stop | `app/stopping`（parallel）→ 按启动逆序卸载，每个插件的 disposer 逆序运行 → `STOPPED` → host disposer |

### 生命周期与代

| 退出码 | 含义 |
|---|---|
| `0` | 停止 |
| `75` | 启动下一代 |
| `3` | 启动失败 |

| 成员 | 契约 |
|---|---|
| `hold(label, session=)` | 异步上下文管理器；全部释放且有待处理重启时退出 75 |
| `request_restart(reason, resume=[...])` | 记录 `reasons`、`resume`、`from_generation`；非预检时写 `resume.json` |
| `accepting_work` | 重启挂起或正在停止时为 `False` |
| `stop(code)` / `wait_stopped()` | 设置退出码并唤醒等待者 |
| `handoff()` | 读 `resume.json`（`from_generation` 不等于本代时）与 `rollback.json` 各一次；文件保留 |
| `commit_handoff()` | 删除两个文件；本代自己的 `resume.json` 留给下一代 |
| `discard_pending_restart()` | 非重启退出时删除本代写出的 `resume.json` |
| `generation`、`supervised`、`preflight` | 构造参数 |

### profile 目录

```
$PYH_HOME/                         默认 ~/.pyharness
  harness.patch.yaml               home patch
  profiles/<name>/
    profile.yaml                   title、bundles、disabled
    harness.patch.yaml             profile patch；程序改写，不保留注释
    credentials.yaml               凭据库（0600）
    site/                          装进此 profile 的 bundle（pip --target）；sys.path 最低优先级
    data/                          默认 SQLite 位置
    runtime/                       ready 标记、交接文件、last-known-good、锁
```

| 模板 | bundles |
|---|---|
| `web`（默认） | `base` |
| `creator` | `base`、`creator` |
| `empty` | 无 |

| 规则 | 内容 |
|---|---|
| profile 名 | 非空、不含 `/`、不以 `.` 开头；否则 `ConfigError` |
| `set_bundle_enabled` | 可选 bundle 进出 `disabled`；其他进出 `bundles`；`builtin` 禁用 → `ConfigError` |
| `set_entry_disabled` / `set_entry_config` | 复用 patch 中该 `id` 的最后一个非 `remove` 操作，否则追加 |
| `installed_bundles()` | site 与环境中的 bundle：`enabled`、`installed`（`profile` / `environment`）、`optional`、`builtin` |
| last-known-good | `profile.yaml` 与 `harness.patch.yaml`；不含 `site/` |
| `lock()` / `alock()` | `runtime/profile.lock` 上的 `flock`；异步版轮询 |

### 凭据

| 项 | 值 |
|---|---|
| 引用名 | `^[A-Z][A-Z0-9_]{0,127}$` |
| 解析顺序 | 环境变量 → `credentials.yaml` |
| 值 | 非空、可打印 ASCII、无空格 |
| `reference_for(route)` | `<ROUTE>_API_KEY`；非字母数字替换为 `_`，数字开头前缀 `P_` |
| `describe(ref)` | `{"reference", "configured", "source": "env" / "store" / None}`，不含值 |

### manage 事务

| 步骤 | 内容 |
|---|---|
| 快照 | profile 文件；`install_bundle` / `install_package` / `uninstall_bundle` 另含 `site/`（`runtime/site-backup-<pid>-<ns>`） |
| 变更 | pip（无 pip 时 uv）装进 `site/`；本地目录 `--no-deps` 后补装未满足依赖；包名安装含依赖；卸载删除分发文件 |
| 预检 | `run_preflight`：新解释器；`baseline` 中已 `failed` 的条目不算新失败 |
| 结论 | 新失败 → 恢复快照，`application: rejected`，`stage`；无新失败 → `saved`，附 `preflight` 摘要 |

| 操作 | 拒绝条件 |
|---|---|
| `install_bundle(profile, path)` | 路径不存在；目录无 `pyproject.toml` / `setup.py`；分发包无 `pyharness.bundles` entry point |
| `install_package(profile, requirement, index_url=)` | 不是 PEP 508 需求；包未装进 site |
| `uninstall_bundle(profile, bundle)` | bundle 不在 site 中 |
| `set_bundle_enabled(profile, bundle, enabled)` | 启用未安装的 bundle；builtin 禁用；无变化 → `unchanged` |
| `set_entry_enabled(profile, id, enabled)`、`set_entry_config(profile, id, config, merge=True)` | 组合树中无此条目 |

| 锁 | 范围 |
|---|---|
| `asyncio.Lock` | 进程内 |
| `Profile.alock()` | 跨进程；轮询 |

### 预检

| 步骤 | 运行 |
|---|---|
| 导入插件、校验配置 | 是 |
| 启动全部插件 | 是 |
| `app/ready` | 是 |
| `app/serve` | 否 |
| 卸载 | 是 |

| 项 | 值 |
|---|---|
| 报告字段 | `ok`、`errors`（`stage`、`entry`、`error`）、`pending`（`entry`、`missing`）、`warnings`、`entries` |
| `run_preflight(profile, extra_patches=None, timeout=180)` | `python -m pyharness.preflight --json`；`extra_patches=None` 取 `runtime/overlays.json`；超时 → `stage: preflight` 错误 |
| 子进程环境 | `PYH_CWD` 继承或当前目录；`PYH_LOG_LEVEL` 取 `PYH_PREFLIGHT_LOG_LEVEL`，默认 `WARNING` |

### worker 与 supervisor

| worker 步骤 | 内容 |
|---|---|
| 1 | 记录 `overlays.json`；组合 profile，启动全部插件 |
| 2 | `app/ready`、`app/serve` |
| 3 | 保存 last-known-good（组合前读取的文件）、写 ready 标记、受管时读取并提交交接 |
| 4 | `app/started`；运行至 `wait_stopped()` |
| 启动失败 | 写 `boot-error.json`（`generation`、`stage`、`error`、`traceback`、`at`、`entries`），退出 3 |

| 信号（worker） | 效果 |
|---|---|
| SIGINT、SIGTERM | 停止，退出 0 |
| SIGHUP | `request_restart("restart signal")`，hold 释放后退出 75 |

| worker 结果 | supervisor 动作 |
|---|---|
| 写出 ready 标记 | 记录 `ready` |
| 退出 75 | 启动下一代 |
| 退出 0，或 supervisor 收到 SIGINT / SIGTERM | 停止 |
| 启动失败 | 恢复 last-known-good，写 `rollback.json`，再启动一次（连续只回滚一次） |
| 启动失败且无可恢复配置 | 退出 3 |
| 启动中被转发信号终止 | 记录 `interrupted-boot`，再启动，不回滚 |
| 启动后其他退出 | 退避 `min(2^(n-1), 10)` 秒重启；`crash_window` 60 秒内超过 `max_crashes` 3 次则退出 |

| 参数 | 默认 |
|---|---|
| `boot_timeout` | 120 秒；超时 = 启动失败 |
| `max_crashes` / `crash_window` | 3 / 60 秒 |
| worker 命令 | `python -m pyharness.worker --profile <p> --home <h> --generation <n> --ready-file runtime/ready-<n>.json --supervised [--patch ...]`；环境 `PYH_GENERATION`、`PYH_CWD` |
| `signal_restart(profile)` | 向 `runtime/supervisor.pid` 发 SIGHUP；无 SIGHUP、无进程或 `/proc` 显示非 pyharness 进程 → `False` |

### CLI

| 命令 | 效果 |
|---|---|
| `pyh init [-p name] [--template web/creator/empty] [--force]` | 从模板创建 profile |
| `pyh run [-p name] [--patch f]... [--no-supervisor] [--boot-timeout 120] [--log-level L]` | supervisor 下运行；profile 不存在时按默认模板创建；`--no-supervisor` 只跑一代 |
| `pyh dump-config [--patch f]...` | 打印组合后的树（含 `source`）；告警到 stderr |
| `pyh preflight [--patch f]... [-v]` | 进程内预检；`ok` 为假时退出 1 |
| `pyh plugin list` | 预检报告中的条目与已安装 bundle |
| `pyh plugin install <dir 或 需求> [--index-url U] [--no-preflight]` | 安装 bundle；`saved` 时向运行中的 supervisor 发 SIGHUP |
| `pyh plugin uninstall / enable / disable / enable-bundle / disable-bundle <target>` | manage 事务；非 `saved` / `unchanged` 退出 1 |
| `pyh restart` | SIGHUP 到 supervisor；无 supervisor 退出 1 |
| `pyh exec <prompt> [--patch f]... [--http-entry http]` | 无 HTTP 运行一个提示；token 到 stdout，工具与错误到 stderr；待审批退出 2，错误退出 1 |
| 全局 | `--home`（默认 `$PYH_HOME` 或 `~/.pyharness`）；`-p` 默认 `$PYH_PROFILE` 或 `web`；`PYH_LOG_LEVEL` |

## 事件

| 事件 | 模式 | 时机 |
|---|---|---|
| `app/ready` | series | 全部插件已 apply；组装，不绑定外部资源；预检运行它；监听者出错 → 启动失败 |
| `app/serve` | series | `app/ready` 之后；接收外部输入；监听者出错 → 启动失败 |
| `app/started` | parallel | 本代已提交：ready 标记已写、last-known-good 已保存、交接已消费；后台工作 |
| `app/stopping` | parallel | 卸载之前 |

## 数据

| 文件 | 写入方 | 内容 |
|---|---|---|
| `profiles/<name>/profile.yaml` | `Profile.init`、`save_manifest` | `title`、`bundles`、`disabled` |
| `profiles/<name>/harness.patch.yaml` | `save_patch` | patch 操作列表；首行固定注释头 |
| `profiles/<name>/credentials.yaml` | `CredentialStore` | `引用名: 值`；0600 |
| `runtime/resume.json` | `request_restart` | `reasons`、`resume`、`requested_at`、`from_generation` |
| `runtime/rollback.json` | supervisor | `failed_generation` + `boot-error.json` 内容 |
| `runtime/boot-error.json` | worker | 启动失败的 `generation`、`stage`、`error`、`traceback`、`at`、`entries` |
| `runtime/ready-<n>.json` | worker | `pid`、`generation`、`summary` |
| `runtime/overlays.json` | worker | 本代 `--patch` 文件的绝对路径列表 |
| `runtime/last-known-good/` | worker | `profile.yaml`、`harness.patch.yaml` 副本 |
| `runtime/supervisor.log.jsonl` | supervisor | 每行 `generation`、`event`、`at` 及附加字段 |
| `runtime/supervisor.pid` | supervisor | supervisor 进程号；退出时删除 |
| `runtime/profile.lock` | `Profile.lock` / `alock` | `flock` 文件 |
| `runtime/site-backup-<pid>-<ns>/` | `manage` | 事务期间的 `site/` 副本；提交时删除 |
