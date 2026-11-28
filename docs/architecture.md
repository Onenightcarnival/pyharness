# 内核

`pyxis-harness-core`：服务容器、类型化事件、分层组合、Loader。

## 插件

插件：Python 分发包，entry point 组 `pyxis_harness.plugins`。

| 形式 | 契约 |
|---|---|
| 模块，或带 `apply` 的对象 | `apply(ctx[, config])`，同步或异步；可选 `name`、`inject`、`Config` |
| `Service` 子类 | 在 `key` 下提供一个服务；`start()`、`stop()` |
| `define_plugin(name, apply, inject=[...], config=Model)` | 属性同模块形式 |

| 属性 | 含义 |
|---|---|
| `name` | 插件名 |
| `inject` | 启动前必须存在的服务 key；`ctx.<key>` 只对这些 key 开放，可选服务用 `ctx.get(key, None)` |
| `Config` | pydantic 模型；校验条目的 `config` |

条目的 `name` 引用插件：entry point 名（`pyxis-harness-tools`）或 `module[:attr]`（`testkit.scripted`）。

```python
name = "my-plugin"
inject = ["tools"]


class Config(BaseModel):
    greeting: str = "hello"


def apply(ctx, config: Config):
    ctx.tools.register(make_tool(config))

    @ctx.on("tools/result")
    async def audit(call, result): ...
```

```python
class Cache(Service):
    key = "cache"
    inject: ClassVar[list[str]] = ["store"]

    async def start(self): ...

    def put(self, k, v):
        self.caller.on_dispose(...)  # caller: context of the calling plugin
```

## Context

每个插件一个 `Context`。经它完成的注册归属于该插件；插件停止时逆序撤销。

| API | 契约 |
|---|---|
| `ctx.provide(key, obj)` | 提供服务 |
| `ctx.get(key[, default])`、`ctx.<key>` | 按 key 查找服务（晚绑定），不 import 实现 |
| `ctx.define_event(name, mode, doc)` | 声明事件及其分发模式 |
| `ctx.on(name, fn)` | 监听，返回 disposer；可作装饰器 |
| `ctx.emit` / `parallel` / `serial` / `series` / `bail` / `waterfall` | 分发 |
| `ctx.on_dispose(fn)`、`ctx.effect(setup)`、`await ctx.enter(cm)` | 可逆副作用 |
| `ctx.lifecycle` | `hold()`、`request_restart(reason, resume=[...])`、`generation`、`supervised` |
| `ctx.loader` | 条目状态 |
| `Service.caller` | 服务方法内：调用方插件的 Context |

## 事件

每个事件一个分发模式，声明时固定。

| 分发 | 结果 |
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

事件清单：[plugins.md#事件](plugins.md#事件)。

## Loader

| 阶段 | 行为 |
|---|---|
| resolve | 导入每个启用的插件，校验 config；出错 → `FAILED` |
| start | 条目的 `inject` 全部在其 scope 可见时启动 |
| order | 就绪条目之间：配置顺序 |
| pending | 依赖始终不出现 → `PENDING`；启动继续 |
| required | `required: true` 的条目未启动（失败，或所需服务始终不出现）→ 启动失败，supervisor 回滚 |
| failure | `apply` / `start` 出错：撤销已做的注册 → `FAILED` |
| teardown | 启动顺序的逆序；每个插件内部的注册逆序撤销 |

组条目（`children`）带 `isolate: [key]` 时，组内看到这些 key 的独立服务实例。

## 组合

### 层

启动时从空列表起，依次应用：

1. profile 的 bundle，按 `profile.yaml` 顺序
2. profile patch
3. home patch
4. `--patch` 覆盖层

### patch 操作

每层是一组按条目 `id` 寻址的操作。

| `id` | 字段 | 操作 |
|---|---|---|
| 已存在 | `name`、`config`、`disabled`、`required`、`isolate`、`children` | 替换给出的字段；`config` 整体替换，`merge: true` 时深合并 |
| 已存在 | `remove: true` | 删除条目 |
| 不存在 | `name` 或 `children` | 插入条目：默认末尾；`parent` / `before` / `after` 定位 |

```yaml
- id: workspace
  config: {shell: true}
  merge: true
```

### 插值

| 占位符 | 值 |
|---|---|
| `${env:NAME}` | 环境变量；未设置 → `""` |
| `${env:NAME:-default}` | 环境变量，未设置时 `default`；默认值可嵌套 |
| `${profile}`、`${profile_dir}`、`${home}`、`${data_dir}`、`${runtime_dir}`、`${cwd}` | profile 变量 |

- 替换结果按字面使用，不再扫描。
- 整个字符串恰好是一个未设置的 `${env:NAME}` 时，值为 `None`。

### harness home

`$PYH_HOME`，默认 `~/.pyharness`：

```
$PYH_HOME/
  harness.patch.yaml       home patch, every profile
  profiles/<name>/
    profile.yaml           ordered bundle list
    harness.patch.yaml     profile patch; written by plugin_manager
    site/                  bundles installed into this profile (uv pip install --target)
    data/                  default SQLite location
    runtime/               ready markers, hand-off files, last-known-good, locks
```

| profile 模板 | bundle |
|---|---|
| `web`（默认） | `base` |
| `empty` | 无 |

`site/` 在 `sys.path` 中优先级最低。

### 边界

- 程序改写 `harness.patch.yaml` 时不保留注释。
