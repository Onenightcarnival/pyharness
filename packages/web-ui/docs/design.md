# pyharness-web-ui

`ctx.webui`：`/` 下的单页 Web 界面（数据来自 `/api`），以及插件浏览器模块（client module）注册表。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `WebUIService`、`ClientModule`、`Config`、`SLOTS`、`INDEX`；页面与 `/plugins/*` 路由 |
| `index.html` | 自包含页面：布局、会话、设置、右侧栏、插件页；`window.__PyhModules__.load` 模块加载器与 `require("pyharness")` 页面库；中英文案 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `INDEX` | 常量 | `index.html` 的路径 |
| `SLOTS` | 常量 | 页面声明的扩展槽位列表（`name`、`kind`、`entry`、`props`） |
| `ClientModule` | 类 | `entry`、`path`、`calls`、`inject`；`rev`（mtime-size）；`describe()` |
| `Config` | 模型 | `path`、`plugins_prefix` |
| `WebUIService` | 类 | `Service`，key `webui` |

## 服务

| 项 | 值 |
|---|---|
| key | `webui` |
| name | `pyharness-web-ui` |
| inject | `http` |
| `Config.path` | `"/"`；页面路径 |
| `Config.plugins_prefix` | `"/plugins"` |
| 构造 | 读入 `index.html` 一次 |
| `start()` | `ctx.http.include_router(router, include_in_schema=False)` |
| `stop()` | 无 |
| `register_client(path, *, calls=None, inject=None)` | 以 `caller.entry_id` 为模块 id 提供文件；文件不存在或该条目已注册 → `ValueError`；返回 disposer |
| `clients()` | `ClientModule.describe()` 列表 |
| `slots()` | `SLOTS` 副本 |
| `boot_manifest()` | `{"plugins": [{"id", "url": "<prefix>/<entry>/client.js?rev=", "inject", "calls"}], "generation"}` |

## 路由

| 方法 | 路径 | 响应 |
|---|---|---|
| GET | `/`（`config.path`） | 页面；`</head>` 前注入 `<script>window.__PYH_BOOT__ = {manifest}</script>`，`<` 转义为 `<` |
| GET | `/plugins/boot.json` | 同一清单；供不含内联清单的页面拉取 |
| GET | `/plugins/{entry}/client.js` | 模块文件，`application/javascript`，`Cache-Control: no-cache`；未注册 404 |
| POST | `/plugins/{entry}/call/{method}` | JSON 对象 → `calls[method](args)`（同步或异步）→ `{"result"}`；非对象 422；`ValueError` 422；未注册 404 |

## Web UI 槽位

| 槽位 | 类型 | 条目 | props |
|---|---|---|---|
| `sidebar.panellist` | list | `{id, label, icon?, description?, order?}`；选中打开同 key 的 `main` 面板；设置 → 通用可隐藏 | 无 |
| `sidebar.more` | list | `{id, label, icon?, order?, onPick()}`；侧边栏「更多」菜单行 | 无 |
| `main` | keyed | `{key, label?} + mount(el, props)`；全局面板；内置 `conversation`、`plugins` | `session` |
| `conversation.composer.dock` | list | `{id, order?} + mount(el, props)`；输入框控件旁 | `session` |
| `settings.sections` | keyed | `{key, label, icon?, order?} + mount(el, props)`；设置页签 | 无 |
| `rightbar.tabs` | keyed | `{key, label, icon?, guide?, multiple?, contentId?(params), title?(params)} + mount(el, props)`；内置 `guide`、`files`、`preview`、`info` | `session`、`workspace`、`tab` |

| 浏览器模块契约 | 内容 |
|---|---|
| 登记 | `window.__PyhModules__.load({ id, factory(require) })`；`id` 为条目 id；`factory` 返回 `{ apply(ctx) }` |
| `require("pyharness")` | `h`、`icon`、`esc`、`toast`、`json`、`api`、`markdown`、`copyText`、`confirmDialog`、`promptDialog`、`waitForRestart`、`T`、`locale` |
| 页面 `ctx` | `slots.register(spec, mount?)`、`api(path, init)`、`host.call(method, args)`、`on(event, fn)`（`session`、`run`、`health`）、`effect(cleanup)`、`locale`、`theme()`、`rightbar.openTab` / `openFile` / `close` / `isExpanded` / `toggle` |
| 加载 | 页面按 `__PYH_BOOT__.plugins` 顺序加载 `url`；缺清单时拉取 `/plugins/boot.json`；状态显示在插件页「客户端模块」卡片 |

## 数据

| 项 | 位置 | 内容 |
|---|---|---|
| 主题 | `localStorage["pyh-theme"]` | `light` / `dark`；跟随系统时删除 |
| 侧边栏视图 | `localStorage["pyh-sidebar"]` | 分组、排序、折叠状态 |
| 界面偏好 | `localStorage["pyh-ui"]` | `workDetails`、`collapseWhen`、`perfUsage`、`hiddenPanels` |
| 右侧栏 | `localStorage["pyh-rightbar"]`、`localStorage["pyh.rightbar.v1.<session>"]` | `open`、`width`；每会话 tab 布局 |
