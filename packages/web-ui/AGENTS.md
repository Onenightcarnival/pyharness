# pyxis-harness-web-ui

Web UI 页面，以及供插件使用的客户端模块注册表。

| 项 | 值 |
|---|---|
| 条目 | `web-ui`（`base` bundle） |
| 服务 | `WebUIService`，`ctx.webui` |
| 注入 | `http` |
| 页面 | `ctx.http` 上的 `config.path` |
| 数据 | `<profile data>/web-ui/prefs.json` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `WebUIService`、`Config`、`SLOTS`、`ClientModule`、`PrefsStore`、路由 |
| `index.html` | 页面 |
| `vendor/` | `VENDOR_FILES` 的脚本 |

## 服务

| 成员 | 契约 |
|---|---|
| `register_client(path, calls=, inject=)` | 为调用方提供 `path`；`calls` 应答 `ctx.host.call` |
| `clients()` | 已注册的客户端模块：条目 id、修订号、calls |
| `slots()` | 页面的扩展槽及其种类与 props（`SLOTS`） |
| `prefs` | profile 的页面偏好（`PrefsStore`） |

## 路由

| 路由 | 内容 |
|---|---|
| `GET /` | 页面；`window.__PYH_BOOT__` 携带客户端模块清单 |
| `GET /plugins/boot.json` | 同一份清单；供未内嵌清单的页面获取 |
| `GET /plugins/{entry}/client.js` | 插件的浏览器模块（`?rev=`：文件的 mtime 与大小） |
| `POST /plugins/{entry}/call/{m}` | JSON body → `calls[m](args)` → `{"result": ...}` |
| `GET /vendor/{name}` | `VENDOR_FILES` 中的脚本，可缓存一年；其余 404 |
| `GET /api/webui/prefs` | `{"unpinnedPanels": [ids]}` |
| `PUT /api/webui/prefs` | `{"unpinnedPanels": [ids]}` → 存储后的对象；body 非法 → 400 |

## 页面偏好

| 键 | 值 |
|---|---|
| `unpinnedPanels` | 列在「更多」菜单中的 `sidebar.panellist` id |

| `unpinnedPanels` | 规则 |
|---|---|
| 数量 | 至多 200 个字符串 |
| 长度 | 每个至多 200 个字符 |
| 没有已注册面板的 id | 保留在存储中 |

## 浏览器模块

纯 JavaScript，无打包器。

```js
window.__PyhModules__.load({
  id: "<entry id>",
  factory(require) {
    const { h, icon, esc, toast } = require("pyxis-harness");
    return { apply(ctx) {
        ctx.slots.register({ slot: "main", key: "my-panel", label: "My panel", icon: "box" },
                           (el, props) => { el.textContent = "hi"; return () => {}; });
    } };
  },
});
```

| `id` | 规则 |
|---|---|
| 值 | patch 条目的 id |
| 只注册一个模块的文件 | 按其条目 id 接受 |

| 页面中的 `ctx` | 成员 |
|---|---|
| `slots` | `register(spec, mount?)` |
| `api` | `api(path, init)` |
| `host` | `call(method, args)` |
| `on` | `on(event, fn)`；事件：`session`、`run`、`health` |
| `effect` | `effect(cleanup)` |
| `locale` | 属性 |
| `theme` | `theme()` |
| `rightbar` | `openTab(kind, {params})`、`openFile(path)`、`close(tabId)`、`isExpanded()`、`toggle()` |
