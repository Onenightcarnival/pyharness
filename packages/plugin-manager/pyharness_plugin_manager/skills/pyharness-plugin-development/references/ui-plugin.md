# Web UI plugins: panels, rows, tabs

The Web UI (`pyharness-web-ui`, service key `webui`) loads one browser module per plugin and offers named slots the module fills. A plugin that extends the page lists `"webui"` in `inject`; without the service (headless runs) it stays `pending`, which is the intended behavior.

## Server side

| member | contract |
|---|---|
| `ctx.webui.register_client(path, calls={name: fn})` | serve the file at `path` as this plugin's module; `fn(args: dict)` (sync or async) answers `ctx.host.call(name, args)` from the page; `ValueError` becomes HTTP 422; removed when the plugin stops |
| `ctx.webui.clients()` | registered modules; `harness_inspect topic=ui` shows them with the slot list |
| `ctx.webui.slots()` | the slots below, with their kinds and mount props |

The page gets the module list in `window.__PYH_BOOT__` at load (or from `GET /plugins/boot.json`) and loads each module in configuration order; the module's URL is `/plugins/<entry id>/client.js`. A change to `client.js` needs a page reload; a change to `calls` needs a restart.

## Browser side

The module is plain JavaScript (no bundler, no imports) and registers itself once; `id` is the entry id (the `id` of the bundle's patch entry, not the distribution name). A file that registers exactly one module is accepted under its entry id whatever `id` says.

```js
window.__PyhModules__.load({
  id: "<entry id>",
  factory(require) {
    const { h, icon, esc, toast, api, markdown } = require("pyharness");
    return { apply(ctx) { /* register slots */ } };
  },
});
```

`require("pyharness")`: `h(tag, attrs, ...children)` builds elements (`class`, `style` object, `onClick`-style handlers); `icon(name)` returns the SVG markup of a page icon (`box`, `folder`, `file`, `eye`, `plug`, `gear`, `terminal`, `refresh`, `copy`, `pencil`, `x-circle`, …; the sprite in the page lists them as `id="i-<name>"`); `esc(text)` escapes HTML; `toast(text)`; `api(path, init)` fetches `/api<path>` and resolves to the `Response`, `json(path, init)` to its parsed JSON body; both reject with an `Error` whose `message` is the response's `detail` and whose `status` is the HTTP status; `markdown(text)` renders Markdown to HTML; `locale` is `zh` or `en`.

`ctx` passed to `apply`:

| member | contract |
|---|---|
| `ctx.slots.register(spec, mount?)` | fill a slot; `spec.slot` names it; returns the disposer |
| `ctx.host.call(method, args)` | `POST /plugins/<entry>/call/<method>`; resolves to the handler's result; rejects with the error detail |
| `ctx.api(path, init)` | same as `require("pyharness").json`: the parsed JSON body |
| `ctx.on("session" \| "run" \| "health", fn)` | current session changed (record or `null`); a run event (`{type: "token" \| "tool_call" \| "tool_result" \| "done" …}`); health polled; returns the disposer |
| `ctx.effect(cleanup)` | register a cleanup run when the module is disposed |
| `ctx.session()` | the current session record or `null` |
| `ctx.locale`, `ctx.theme()` | `zh`/`en`; `light`/`dark` |
| `ctx.rightbar.openTab(kind, {params})`, `openFile(path)`, `close(tabId)`, `isExpanded()`, `toggle()` | drive the right sidebar of the current session, for example open a file the plugin produced |

`mount(el, props)` renders into `el` and returns a cleanup function; the page calls the cleanup when the seat is left. A thrown error shows inside the seat and does not affect the rest of the page.

## Slots

| slot | kind | spec | props | note |
|---|---|---|---|---|
| `sidebar.panellist` | list | `{id, label, icon?, order?}` | — | a row under "Plugins"; selecting it opens the `main` panel with the same key |
| `sidebar.more` | list | `{id, label, icon?, order?, onPick()}` | — | a row of the sidebar More menu; without `onPick`, opens the `main` panel with the same key |
| `main` | keyed | `{key, label?}` + mount | `{session}` | a page in the center column; `conversation` and `plugins` are built in |
| `conversation.composer.dock` | list | `{id, order?}` + mount | `{session}` | inline beside the composer's mode chip; keep it to one small control |
| `settings.sections` | keyed | `{key, label, icon?, order?}` + mount | `{}` | a tab of the Settings dialog |
| `rightbar.tabs` | keyed | `{key, label, icon?, guide?, multiple?, contentId?(params), title?(params)}` + mount | `{session, workspace, tab}` | a right-sidebar **tab type**. The sidebar holds a per-session list of open tabs; `guide: {title, description?, order?}` adds a card to the Start page that opens the type. `multiple: true` gives every open its own tab; otherwise `contentId(params)` (default: the key) de-duplicates. `title(params)` names the chip. `props.tab` is the open tab: `params`, `store` (survives tab switches), `setTitle`, `close`, `openTab`, `openFile(path)`, `replaceWith(kind)`. Built in: `guide`, `files`, `preview` (one per file path), `info` |

A keyed slot refuses a second registration with the same key (the error names the owner). Keys and ids are namespaced by convention with the bundle name.

## Page classes

Reuse the page's styles instead of shipping CSS where possible: `page`, `pageHead`, `pageTitle`, `pageIntro`, `group`, `groupHead`, `groupTitle`, `groupMeta`, `cards`, `pcard`, `kvTable`, `btn` (`primary`, `outline`, `sm`), `iconButton`, `tag` (`data-tone` of `info`, `success`, `danger`, `outline`), `tip`. Colors are CSS variables (`--label-primary`, `--label-secondary`, `--label-tertiary`, `--bg-base`, `--bg-layer-1` … `--bg-layer-3`, `--hover`, `--border-l2`, `--info`, `--error`, `--mono`) and follow the theme.

## Verify after the restart

`harness_inspect topic=ui` lists the module under `clients`. Request `http://127.0.0.1:<port>/plugins/<entry>/client.js` through the shell when available. The Plugins page shows the module under "Client modules" with its load state; a module that failed to load shows the error there and in a toast. Ask the user to reload the page and open the panel; the page cannot be driven from here.
