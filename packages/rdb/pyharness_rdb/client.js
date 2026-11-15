window.__PyhModules__.load({
  id: "rdb",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: { entry: "数据库", intro: "关系数据库工作台：SQLite / PostgreSQL / MySQL / GaussDB。连接、浏览结构、编辑数据、运行 SQL。", agentTools: "允许 Agent 使用", conn: "连接", add: "新增", connEmpty: "还没有连接。", edit: "编辑", del: "删除", test: "测试连接", deleteConfirm: (n) => `删除连接「${n}」？只移除本机保存的连接信息。`, testing: "连接中…", testOk: (node, v, ms) => `已连接 ${node}：${v}（${ms} ms）`, testOkFile: (v, ms) => `已连接：${v}（${ms} ms）`, testFail: (e) => `连接失败：${e}`, writeOn: "可写", formCreate: "新增连接", formEdit: (n) => `编辑连接「${n}」`, kind: "类型", file: "数据库文件", host: "主机（多个节点用逗号分隔）", port: "端口", database: "数据库", user: "用户名", password: "密码", passwordKeep: "留空保留原密码", ssl: "使用 SSL", target: "目标节点", targets: { any: "任意节点", "read-write": "可读写", "read-only": "只读", primary: "主库", standby: "备库", "prefer-standby": "优先备库" }, loadBalance: "随机选择节点", optional: "可选", name: "显示名称", namePlaceholder: "默认用 数据库@主机", allowWrite: "允许 Agent 写入", cancel: "取消", save: "保存", saving: "保存中…", objects: "对象", loading: "加载中…", noTables: "没有表", views: "视图", tables: "表", tabData: "数据", tabStructure: "结构", tabSql: "SQL", pick: "在左侧选择一张表。", rows: (a, b, t) => `第 ${a}–${b} 行，共 ${t} 行`, rowsNoTotal: (a, b) => `第 ${a}–${b} 行`, prev: "上一页", next: "下一页", refresh: "刷新", addRow: "新增行", deleteRows: "删除所选", pending: (n) => `${n} 处改动`, saveChanges: "保存改动", discard: "放弃", filter: "过滤", filterPlaceholder: "值", noPk: "该表没有主键，只能查看；请在 SQL 中修改。", confirmTitle: "确认执行", confirmBody: (n) => `以下 ${n} 条语句将在一个事务中执行：`, confirmOk: "执行", applied: (n, a) => `已执行 ${n} 条语句，影响 ${a} 行`, failed: (e) => `执行失败，已回滚：${e}`, exportCsv: "导出 CSV", setNull: "设为 NULL", ddl: "DDL", run: "执行（Ctrl+Enter）", running: "执行中…", sqlPlaceholder: "SELECT * FROM …", result: (n, ms) => `${n} 行，${ms} ms`, affected: (c, n, ms) => `${c}：影响 ${n} 行，${ms} ms`, truncated: (n) => `（结果已截断，只显示前 ${n} 行）`, exportResult: "导出结果", sqlError: (e) => `错误：${e}`, confirmWrite: (c) => `这条语句会修改数据（${c}）。执行？`, colName: "列", colType: "类型", colNullable: "可空", colDefault: "默认值", colPk: "主键", indexes: "索引", approxRows: (n) => `约 ${n} 行`, toolsOn: "agent 工具已开启", toolsOff: "agent 工具已关闭", close: "关闭" },
      en: { entry: "Database", intro: "Relational database workbench: SQLite / PostgreSQL / MySQL / GaussDB. Connect, browse structure, edit data, run SQL.", agentTools: "Allow agent access", conn: "Connections", add: "Add", connEmpty: "No connections yet.", edit: "Edit", del: "Delete", test: "Test connection", deleteConfirm: (n) => `Remove the connection "${n}"? Only the locally saved connection is removed.`, testing: "Connecting…", testOk: (node, v, ms) => `Connected to ${node}: ${v} (${ms} ms)`, testOkFile: (v, ms) => `Connected: ${v} (${ms} ms)`, testFail: (e) => `Connection failed: ${e}`, writeOn: "writable", formCreate: "Add connection", formEdit: (n) => `Edit connection "${n}"`, kind: "Type", file: "Database file", host: "Host (comma-separated nodes)", port: "Port", database: "Database", user: "User", password: "Password", passwordKeep: "Leave empty to keep the stored password", ssl: "Use SSL", target: "Target node", targets: { any: "Any", "read-write": "Read-write", "read-only": "Read-only", primary: "Primary", standby: "Standby", "prefer-standby": "Prefer standby" }, loadBalance: "Pick nodes in random order", optional: "Optional", name: "Display name", namePlaceholder: "defaults to database@host", allowWrite: "Allow agent writes", cancel: "Cancel", save: "Save", saving: "Saving…", objects: "Objects", loading: "Loading…", noTables: "No tables", views: "Views", tables: "Tables", tabData: "Data", tabStructure: "Structure", tabSql: "SQL", pick: "Pick a table on the left.", rows: (a, b, t) => `Rows ${a}–${b} of ${t}`, rowsNoTotal: (a, b) => `Rows ${a}–${b}`, prev: "Previous", next: "Next", refresh: "Refresh", addRow: "Add row", deleteRows: "Delete selected", pending: (n) => `${n} change(s)`, saveChanges: "Save changes", discard: "Discard", filter: "Filter", filterPlaceholder: "value", noPk: "This table has no primary key; it is read-only here. Edit it with SQL.", confirmTitle: "Confirm execution", confirmBody: (n) => `These ${n} statement(s) run in one transaction:`, confirmOk: "Execute", applied: (n, a) => `Executed ${n} statement(s), ${a} row(s) affected`, failed: (e) => `Execution failed and was rolled back: ${e}`, exportCsv: "Export CSV", setNull: "Set NULL", ddl: "DDL", run: "Run (Ctrl+Enter)", running: "Running…", sqlPlaceholder: "SELECT * FROM …", result: (n, ms) => `${n} row(s), ${ms} ms`, affected: (c, n, ms) => `${c}: ${n} row(s) affected, ${ms} ms`, truncated: (n) => `(result truncated to the first ${n} rows)`, exportResult: "Export result", sqlError: (e) => `Error: ${e}`, confirmWrite: (c) => `This statement modifies data (${c}). Run it?`, colName: "Column", colType: "Type", colNullable: "Nullable", colDefault: "Default", colPk: "PK", indexes: "Indexes", approxRows: (n) => `~${n} rows`, toolsOn: "Agent tools are on", toolsOff: "Agent tools are off", close: "Close" },
    };
    const KINDS = [["postgres", "PostgreSQL"], ["mysql", "MySQL"], ["gaussdb", "GaussDB"], ["sqlite", "SQLite"]];
    const PORTS = { postgres: 5432, mysql: 3306, gaussdb: 8000, sqlite: "" };
    const BADGE = { sqlite: "sqlite", postgres: "pg", gaussdb: "gauss", mysql: "mysql" };
    const OPS = ["=", "!=", ">", ">=", "<", "<=", "like", "is null", "is not null"];
    const PAGE = 100;
    const READ_START = /^\s*(?:--[^\n]*\n\s*|#[^\n]*\n\s*|\/\*[\s\S]*?\*\/\s*)*(select|with|explain|show|values|table|describe|desc|pragma)\b/i;
    const WRITE_WORDS = /\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|vacuum|reindex|attach|detach|copy|call|lock|refresh)\b|\bselect\b[\s\S]*\binto\b|\bfor\s+update\b/i;
    const looksReadOnly = (sql) => READ_START.test(sql) && !WRITE_WORDS.test(sql.replace(/'(?:[^']|'')*'/g, "''"));
    const firstWord = (sql) => { const m = sql.replace(/--[^\n]*/g, " ").replace(/\/\*[\s\S]*?\*\//g, " ").trim().match(/^[A-Za-z]+/); return m ? m[0].toUpperCase() : "SQL"; };
    const q = (kind, name) => (kind === "mysql" ? "`" + name.replace(/`/g, "``") + "`" : '"' + name.replace(/"/g, '""') + '"');

    async function call(path, opts) {
      const res = await fetch("/api/rdb" + path, { headers: { "content-type": "application/json" }, ...(opts || {}) });
      if (!res.ok) { let detail = `HTTP ${res.status}`; try { const d = (await res.json()).detail; if (typeof d === "string") detail = d; } catch { /* no body */ } throw new Error(detail); }
      return res.json();
    }
    const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none"><symbol id="i-grid" viewBox="0 0 16 16"><rect x="2.25" y="2.25" width="11.5" height="11.5" rx="1.5"/><path d="M2.25 6.25h11.5M2.25 9.75h11.5M6.25 2.25v11.5"/></symbol><symbol id="i-play" viewBox="0 0 16 16"><path d="M4.25 2.75v10.5l8.5-5.25z"/></symbol></svg>`;

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        if (!document.getElementById("i-grid")) document.body.insertAdjacentHTML("beforeend", sprite);
        const style = document.createElement("style");
        style.textContent = `
          .rdbPage { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0 24px 16px; }
          .rdbPage .pageHead { flex: none; flex-wrap: wrap; padding-bottom: 10px; }
          .rdbPage .headTools { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--label-secondary); }
          .rdbBanner { margin: 0 0 10px; padding: 7px 12px; border-radius: 8px; font-size: 12px; display: flex; align-items: center; gap: 8px; flex: none; }
          .rdbBanner span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
          .rdbBanner[data-kind="ok"] { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }
          .rdbBanner[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .rdbBanner[data-kind="info"] { background: color-mix(in srgb, var(--info) 10%, transparent); color: var(--info); }
          .rdbBody { flex: 1; min-height: 0; display: flex; gap: 12px; }
          .rdbSide { width: 240px; flex: none; display: flex; flex-direction: column; gap: 8px; min-height: 0; border-right: 0.5px solid var(--border-l2); padding-right: 12px; }
          .rdbSide .blockHead { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: var(--label-secondary); padding: 2px 0; }
          .rdbSide .blockHead span { flex: 1; }
          .rdbConns { max-height: 40%; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
          .rdbConn { display: block; width: 100%; text-align: left; padding: 7px 8px; border: none; border-radius: 8px; background: transparent; color: var(--label-primary); }
          .rdbConn:hover { background: var(--hover); }
          .rdbConn[data-active] { background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .rdbConn .l1 { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; }
          .rdbConn .l1 .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .rdbConn .badge { font-size: 10px; text-transform: uppercase; padding: 0 5px; border-radius: 4px; background: var(--layer-3, var(--layer-2)); color: var(--label-tertiary); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .rdbConn .w { font-size: 10px; color: var(--warn); }
          .rdbConn .l2 { font-size: 11px; color: var(--label-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 1px; }
          .rdbActions { display: flex; gap: 10px; padding: 0 8px; }
          .rdbLink { background: none; border: none; padding: 0; font-size: 12px; color: var(--info); cursor: pointer; }
          .rdbLink[data-danger] { color: var(--error); }
          .rdbLink:disabled { opacity: .5; cursor: default; }
          .rdbTree { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
          .rdbTree .items { flex: 1; overflow: auto; }
          .rdbTree .group { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--label-tertiary); padding: 6px 8px 2px; }
          .rdbObj { display: flex; align-items: center; gap: 6px; width: 100%; text-align: left; padding: 5px 8px; border: none; border-radius: 6px; background: transparent; color: var(--label-primary); font: 12px/18px var(--mono); }
          .rdbObj:hover { background: var(--hover); }
          .rdbObj[aria-current="true"] { background: color-mix(in srgb, var(--info) 12%, transparent); color: var(--info); }
          .rdbObj .ico { width: 14px; height: 14px; flex: none; color: var(--label-tertiary); }
          .rdbObj span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .rdbWork { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
          .rdbTabs { display: flex; align-items: center; gap: 2px; border-bottom: 0.5px solid var(--border-l2); flex: none; }
          .rdbTabs button { padding: 6px 12px; margin-bottom: -1px; border: none; border-bottom: 2px solid transparent; background: transparent; font-size: 13px; color: var(--label-secondary); }
          .rdbTabs button[aria-selected="true"] { color: var(--label-primary); font-weight: 500; border-bottom-color: var(--info); }
          .rdbTabs .cur { margin-left: auto; font: 12px var(--mono); color: var(--label-tertiary); }
          .rdbPane { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
          .rdbToolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex: none; }
          .rdbToolbar .spacer { flex: 1; }
          .rdbToolbar .select, .rdbToolbar .input { width: auto; height: 28px; font-size: 12px; padding: 0 8px; }
          .rdbToolbar .selectWrap .select { padding-right: 26px; }
          .rdbTableWrap { flex: 1; min-height: 0; overflow: auto; border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); background: var(--layer-1); }
          .rdbTable { border-collapse: separate; border-spacing: 0; min-width: 100%; font-size: 12px; }
          .rdbTable th { position: sticky; top: 0; z-index: 1; text-align: left; padding: 8px 10px; background: var(--layer-2); font-weight: 500; color: var(--label-secondary); white-space: nowrap; border-bottom: 0.5px solid var(--border-l2); cursor: default; }
          .rdbTable th[data-sortable] { cursor: pointer; }
          .rdbTable th .pk { font-size: 10px; color: var(--warn); margin-left: 4px; }
          .rdbTable td { padding: 6px 10px; border-bottom: 0.5px solid var(--border-l2); font-family: var(--mono); max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: top; }
          .rdbTable tr:hover td { background: var(--hover); }
          .rdbTable td[data-null] { font-style: italic; color: var(--label-tertiary); }
          .rdbTable tr[data-deleted] td { text-decoration: line-through; background: color-mix(in srgb, var(--error) 8%, transparent); }
          .rdbTable tr[data-new] td { background: color-mix(in srgb, var(--success) 8%, transparent); }
          .rdbTable td[data-dirty] { background: color-mix(in srgb, var(--warn) 14%, transparent); }
          .rdbTable td .cellInput { width: 100%; min-width: 80px; height: 22px; padding: 0 6px; border: 0.5px solid var(--info); border-radius: 4px; background: var(--bg-layer-1); color: var(--label-primary); font: 12px var(--mono); outline: none; }
          .rdbTable td .nullBtn { margin-left: 4px; border: none; background: transparent; color: var(--label-tertiary); cursor: pointer; }
          .rdbTable td.sel { width: 24px; text-align: center; }
          .rdbFoot { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--label-tertiary); flex: none; }
          .rdbFoot .spacer { flex: 1; }
          .rdbEmpty { padding: 32px 12px; text-align: center; font-size: 12.5px; color: var(--label-tertiary); }
          .rdbStruct { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 12px; }
          .rdbStruct h3 { margin: 0; font-size: 13px; font-weight: 500; display: flex; gap: 8px; align-items: baseline; }
          .rdbStruct h3 small { font-weight: 400; color: var(--label-tertiary); }
          .rdbStruct pre { margin: 0; padding: 10px 12px; border-radius: 10px; background: var(--layer-2); font: 12px/18px var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
          .rdbSql textarea { width: 100%; min-height: 160px; padding: 10px 12px; border: 0.5px solid var(--border-l4); border-radius: var(--r-md); background: var(--bg-layer-1); color: var(--label-primary); font: 13px/20px var(--mono); resize: vertical; outline: none; }
          .rdbSql textarea:focus { border-color: var(--info); }
          .rdbSql .status { font-size: 12px; color: var(--label-tertiary); display: flex; gap: 10px; align-items: center; }
          .rdbForm { display: flex; flex-direction: column; gap: 12px; padding: 4px 4px 8px; }
          .rdbForm label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--label-secondary); }
          .rdbForm .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
          .rdbForm .row.port { grid-template-columns: 1fr 120px; }
          .rdbForm .check { flex-direction: row; align-items: center; gap: 6px; }
          .rdbForm .divider { font-size: 11px; color: var(--label-tertiary); text-transform: uppercase; letter-spacing: .04em; padding-top: 4px; }
          .rdbForm .err { font-size: 12px; color: var(--error); }
          .rdbSeg { display: inline-flex; padding: 3px; border-radius: 8px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .rdbSeg button { height: 26px; padding: 0 12px; border: none; border-radius: 6px; background: transparent; font-size: 12px; color: var(--label-secondary); }
          .rdbSeg button[aria-checked="true"] { background: var(--layer-1); color: var(--label-primary); box-shadow: 0 1px 2px rgba(0,0,0,.08); }
          .rdbPre { margin: 4px; padding: 10px 12px; border-radius: 8px; background: var(--layer-1); font: 12px/18px var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 300px; overflow: auto; }
          @container (max-width: 760px) { .rdbBody { flex-direction: column; } .rdbSide { width: auto; border-right: none; padding-right: 0; max-height: 40%; } }
        `;
        document.head.appendChild(style);
        ctx.effect(() => style.remove());

        function modal(inner, wide) {
          const el = h("div", { class: "modal" }); el.innerHTML = `<div class="modalCard${wide ? "" : " narrow"}" role="dialog" aria-modal="true">${inner}</div>`;
          document.body.appendChild(el);
          const close = () => { el.remove(); document.removeEventListener("keydown", onKey, true); };
          const onKey = (e) => { if (e.key === "Escape") close(); };
          document.addEventListener("keydown", onKey, true);
          el.addEventListener("mousedown", (e) => { if (e.target === el) close(); });
          return { el, close };
        }
        function confirmSql(title, bodyText, statements, okLabel) {
          return new Promise((resolve) => {
            const { el, close } = modal(`<div class="modalHead">${esc(title)}</div><div class="modalBody"><p>${esc(bodyText)}</p><pre class="rdbPre">${esc(statements)}</pre></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes style="background:var(--error)">${esc(okLabel)}</button></div>`, true);
            el.querySelector("[data-no]").onclick = () => { close(); resolve(false); };
            el.querySelector("[data-yes]").onclick = () => { close(); resolve(true); };
          });
        }

        // ------------------------------------------------------------ page
        function page(el) {
          let alive = true;
          const st = { profiles: null, settings: { agentTools: false }, active: null, schemas: [], schema: null, tables: undefined, table: null, info: null, tab: "data", filterText: "", banner: null, testing: false };
          const root = h("div", { class: "rdbPage" }); el.replaceChildren(root);
          const setBanner = (kind, text) => { st.banner = kind ? { kind, text } : null; renderBanner(); };
          const fail = (err) => setBanner("error", err.message || String(err));

          async function load() {
            try {
              const [p, s] = await Promise.all([call("/profiles"), call("/settings")]);
              if (!alive) return;
              st.profiles = p.profiles; st.settings = s.settings;
              const keep = st.profiles.find((x) => x.id === st.active);
              if (!keep) await selectProfile(st.profiles[0] ? st.profiles[0].id : null); else render();
            } catch (err) { fail(err); render(); }
          }
          async function selectProfile(id) {
            st.active = id; st.schemas = []; st.schema = null; st.tables = undefined; st.table = null; st.info = null; st.filterText = "";
            render();
            if (!id) return;
            try { const d = await call(`/schemas?id=${encodeURIComponent(id)}`); if (!alive || st.active !== id) return; st.schemas = d.schemas; await selectSchema(d.defaultSchema); }
            catch (err) { fail(err); }
          }
          async function selectSchema(schema) {
            st.schema = schema; st.tables = undefined; st.table = null; st.info = null; render();
            try { const d = await call(`/tables?id=${encodeURIComponent(st.active)}&schema=${encodeURIComponent(schema)}`); if (!alive || st.schema !== schema) return; st.tables = d.tables; render(); }
            catch (err) { st.tables = []; fail(err); render(); }
          }
          async function selectTable(tbl) {
            st.table = tbl; st.info = null; if (st.tab === "sql") st.tab = "data"; render();
            try { const d = await call(`/columns?id=${encodeURIComponent(st.active)}&schema=${encodeURIComponent(tbl.schema)}&table=${encodeURIComponent(tbl.name)}&kind=${tbl.kind}`); if (!alive || st.table !== tbl) return; st.info = d.info; render(); }
            catch (err) { fail(err); }
          }
          const profile = () => (st.profiles || []).find((p) => p.id === st.active) || null;

          // ---------------------------------------------------------- header, banner
          function header() {
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(!!st.settings.agentTools), disabled: !st.profiles, onClick: async () => {
              const next = !st.settings.agentTools; st.settings.agentTools = next; render();
              try { const d = await call("/settings", { method: "POST", body: JSON.stringify({ agentTools: next }) }); st.settings = d.settings; setBanner("ok", next ? t.toolsOn : t.toolsOff); }
              catch (err) { st.settings.agentTools = !next; fail(err); } render();
            } }, h("span", { class: "knob" }));
            return h("div", { class: "pageHead" }, h("div", null, h("h1", { class: "pageTitle" }, t.entry), h("p", { class: "pageIntro" }, t.intro)), h("div", { class: "headTools" }, h("span", null, t.agentTools), sw));
          }
          const bannerBox = h("div");
          function renderBanner() { bannerBox.replaceChildren(); if (st.banner) bannerBox.append(h("div", { class: "rdbBanner", "data-kind": st.banner.kind }, h("span", null, st.banner.text), h("button", { type: "button", class: "iconButton sm", title: t.close, onClick: () => setBanner(null) }, ico("x")))); }

          // ---------------------------------------------------------- side
          function side() {
            const p = profile();
            const conns = h("div", { class: "rdbConns" });
            if (st.profiles && !st.profiles.length) conns.append(h("div", { class: "rdbEmpty", style: { padding: "12px" } }, t.connEmpty));
            for (const c of st.profiles || []) {
              const meta = c.kind === "sqlite" ? c.file : `${c.host.split(/\s*,\s*/)[0]}${c.host.includes(",") ? ` +${c.host.split(",").length - 1}` : ""}/${c.database}${c.targetSessionAttrs !== "any" ? ` · ${t.targets[c.targetSessionAttrs]}` : ""}`;
              conns.append(h("button", { type: "button", class: "rdbConn", "data-active": c.id === st.active ? "" : null, title: c.kind === "sqlite" ? c.file : `${c.host}/${c.database}`, onClick: () => { if (c.id !== st.active) selectProfile(c.id); } },
                h("div", { class: "l1" }, h("span", { class: "badge" }, BADGE[c.kind]), h("span", { class: "name" }, c.name), c.allowWrite ? h("span", { class: "w" }, t.writeOn) : null), h("div", { class: "l2" }, meta)));
            }
            const actions = p ? h("div", { class: "rdbActions" },
              h("button", { type: "button", class: "rdbLink", disabled: st.testing, onClick: testActive }, t.test),
              h("button", { type: "button", class: "rdbLink", onClick: () => openForm(p) }, t.edit),
              h("button", { type: "button", class: "rdbLink", "data-danger": "", onClick: () => deleteProfile(p) }, t.del)) : null;
            const tree = p ? objectTree() : null;
            return h("aside", { class: "rdbSide" }, h("div", { class: "blockHead" }, h("span", null, t.conn), h("button", { type: "button", class: "rdbLink", onClick: () => openForm(null) }, "+ " + t.add)), conns, actions, tree);
          }
          function objectTree() {
            const items = h("div", { class: "items" });
            if (st.tables === undefined) items.append(h("div", { class: "rdbEmpty" }, t.loading));
            else {
              const f = st.filterText.toLowerCase(); const list = st.tables.filter((x) => !f || x.name.toLowerCase().includes(f));
              if (!list.length) items.append(h("div", { class: "rdbEmpty" }, t.noTables));
              for (const [kind, label] of [["table", t.tables], ["view", t.views]]) {
                const group = list.filter((x) => x.kind === kind); if (!group.length) continue;
                items.append(h("div", { class: "group" }, `${label} · ${group.length}`));
                for (const tbl of group) items.append(h("button", { type: "button", class: "rdbObj", "aria-current": st.table && st.table.name === tbl.name && st.table.schema === tbl.schema ? "true" : null, title: `${tbl.schema}.${tbl.name}`, onClick: () => selectTable(tbl) }, ico(kind === "view" ? "eye" : "grid", "ico"), h("span", null, tbl.name)));
              }
            }
            const head = h("div", { class: "blockHead" }, h("span", null, t.objects));
            if (st.schemas.length > 1) head.append(h("span", { class: "selectWrap" }, h("select", { class: "select", style: { height: "26px", width: "auto", fontSize: "12px", padding: "0 24px 0 8px" }, onChange: (e) => selectSchema(e.target.value) }, st.schemas.map((s) => h("option", { value: s, selected: s === st.schema }, s))), ico("chev-down", "ico chev")));
            const filter = h("input", { class: "input", placeholder: t.filter, value: st.filterText, style: { height: "28px", fontSize: "12px" }, onInput: (e) => { st.filterText = e.target.value; const fresh = objectTree(); treeBox.replaceWith(fresh); treeBox = fresh; filter.focus(); } });
            return h("div", { class: "rdbTree" }, head, filter, items);
          }
          let treeBox = null;
          async function testActive() {
            const p = profile(); if (!p) return;
            st.testing = true; setBanner("info", t.testing); render();
            try { const r = (await call("/test", { method: "POST", body: JSON.stringify({ id: p.id }) })).result; setBanner(r.ok ? "ok" : "error", r.ok ? (r.node ? t.testOk(r.node, r.serverVersion, r.latencyMs) : t.testOkFile(r.serverVersion, r.latencyMs)) : t.testFail(r.error || "?")); }
            catch (err) { fail(err); }
            st.testing = false; render();
          }
          function deleteProfile(p) {
            const { el, close } = modal(`<div class="modalHead">${esc(t.del)}</div><div class="modalBody"><p>${esc(t.deleteConfirm(p.name))}</p></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes style="background:var(--error)">${esc(t.del)}</button></div>`);
            el.querySelector("[data-no]").onclick = close;
            el.querySelector("[data-yes]").onclick = async () => { try { await call(`/profiles?id=${encodeURIComponent(p.id)}`, { method: "DELETE" }); close(); if (st.active === p.id) st.active = null; await load(); } catch (err) { close(); fail(err); } };
          }

          // ---------------------------------------------------------- profile form
          function openForm(existing) {
            const d = existing ? { ...existing } : { kind: "postgres", name: "", file: "", host: "", port: PORTS.postgres, database: "", user: "", ssl: false, targetSessionAttrs: "any", loadBalanceHosts: false, allowWrite: false };
            let password = "";
            const { el, close } = modal(`<div class="modalHead">${esc(existing ? t.formEdit(existing.name) : t.formCreate)}</div><div class="modalBody"><div class="rdbForm" data-form></div></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes>${esc(t.save)}</button></div>`);
            const form = el.querySelector("[data-form]"); const err = h("div", { class: "err" });
            const input = (key, attrs = {}) => h("input", { class: "input" + (attrs.mono ? " mono" : ""), value: d[key] == null ? "" : d[key], ...attrs, onInput: (e) => { d[key] = attrs.type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value; } });
            const check = (key, label) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!d[key], onChange: (e) => { d[key] = e.target.checked; } }), label);
            function draw() {
              form.replaceChildren();
              const seg = h("div", { class: "rdbSeg", role: "radiogroup", "aria-label": t.kind }, KINDS.map(([k, label]) => h("button", { type: "button", role: "radio", "aria-checked": String(d.kind === k), onClick: () => { const prev = d.kind; if (d.port === "" || d.port === PORTS[prev]) d.port = PORTS[k]; d.kind = k; draw(); } }, label)));
              form.append(h("label", null, t.kind, seg));
              if (d.kind === "sqlite") form.append(h("label", null, t.file, input("file", { mono: true, placeholder: "/path/to/data.sqlite", autofocus: true })));
              else {
                form.append(h("div", { class: "row port" }, h("label", null, t.host, input("host", { mono: true, placeholder: "db1.example.com, db2.example.com", autofocus: true })), h("label", null, t.port, input("port", { type: "number", placeholder: String(PORTS[d.kind]) }))));
                form.append(h("label", null, t.database, input("database", { mono: true, placeholder: d.kind === "mysql" ? "mydb" : "postgres" })));
                const pw = h("input", { class: "input", type: "password", autocomplete: "new-password", placeholder: existing ? "••••••••" : "", onInput: (e) => { password = e.target.value; } });
                form.append(h("div", { class: "row" }, h("label", null, t.user, input("user", { autocomplete: "off" })), h("label", null, t.password, pw, existing ? h("small", { style: { color: "var(--label-tertiary)" } }, t.passwordKeep) : null)));
                form.append(check("ssl", t.ssl));
              }
              form.append(h("div", { class: "divider" }, t.optional));
              if (d.kind !== "sqlite") {
                form.append(h("label", null, t.target, h("span", { class: "selectWrap" }, h("select", { class: "select", onChange: (e) => { d.targetSessionAttrs = e.target.value; } }, Object.keys(t.targets).map((v) => h("option", { value: v, selected: d.targetSessionAttrs === v }, t.targets[v]))), ico("chev-down", "ico chev"))));
                form.append(check("loadBalanceHosts", t.loadBalance));
              }
              form.append(h("label", null, t.name, input("name", { placeholder: t.namePlaceholder })), check("allowWrite", t.allowWrite), err);
              const first = form.querySelector("input[autofocus]"); if (first) first.focus();
            }
            draw();
            form.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); submit(); } });
            async function submit() {
              const yes = el.querySelector("[data-yes]"); yes.disabled = true; yes.textContent = t.saving;
              const payload = { kind: d.kind, name: d.name || "", ssl: !!d.ssl, allowWrite: !!d.allowWrite };
              if (d.kind === "sqlite") payload.file = d.file || "";
              else { Object.assign(payload, { host: d.host || "", database: d.database || "", user: d.user || "", port: d.port === "" || d.port == null ? PORTS[d.kind] : Number(d.port), targetSessionAttrs: d.targetSessionAttrs, loadBalanceHosts: !!d.loadBalanceHosts }); if (password || !existing) payload.password = password; }
              try {
                const r = existing ? await call(`/profiles?id=${encodeURIComponent(existing.id)}`, { method: "PATCH", body: JSON.stringify(payload) }) : await call("/profiles", { method: "POST", body: JSON.stringify(payload) });
                close(); const p = await call("/profiles"); st.profiles = p.profiles; await selectProfile(r.profile.id);
              } catch (e2) { err.textContent = e2.message; yes.disabled = false; yes.textContent = t.save; }
            }
            el.querySelector("[data-no]").onclick = close; el.querySelector("[data-yes]").onclick = submit;
          }

          // ---------------------------------------------------------- work area
          function work() {
            const p = profile();
            if (!p) return h("div", { class: "rdbWork" }, h("div", { class: "rdbEmpty" }, st.profiles && !st.profiles.length ? t.connEmpty : ""));
            const tabs = h("div", { class: "rdbTabs", role: "tablist" }, [["data", t.tabData], ["structure", t.tabStructure], ["sql", t.tabSql]].map(([k, label]) => h("button", { type: "button", role: "tab", "aria-selected": String(st.tab === k), onClick: () => { st.tab = k; render(); } }, label)), st.table ? h("span", { class: "cur" }, `${st.table.schema}.${st.table.name}`) : null);
            let pane;
            if (st.tab === "sql") pane = sqlEditor(p);
            else if (!st.table) pane = h("div", { class: "rdbEmpty" }, t.pick);
            else if (!st.info) pane = h("div", { class: "rdbEmpty" }, t.loading);
            else pane = st.tab === "data" ? dataGrid(p) : structure(p);
            return h("div", { class: "rdbWork" }, tabs, pane);
          }

          // ---------------------------------------------------------- data grid
          const gridState = { key: null, offset: 0, sort: null, filter: null, page: null, loading: false, edits: {}, inserts: [], deletes: new Set(), selected: new Set() };
          function dataGrid(p) {
            const key = `${p.id}/${st.table.schema}.${st.table.name}`;
            if (gridState.key !== key) { Object.assign(gridState, { key, offset: 0, sort: null, filter: null, page: null, loading: false, edits: {}, inserts: [], deletes: new Set(), selected: new Set() }); loadPage(); }
            const info = st.info; const editable = info.primaryKey.length > 0 && info.table.kind === "table";
            const cols = info.columns.map((c) => c.name);
            const pane = h("div", { class: "rdbPane" });
            if (!editable && info.table.kind === "table") pane.append(h("div", { class: "rdbBanner", "data-kind": "info" }, h("span", null, t.noPk)));
            // toolbar
            const fcol = h("select", { class: "select", "aria-label": t.filter }, cols.map((c) => h("option", { value: c, selected: gridState.filter && gridState.filter.column === c }, c)));
            const fop = h("select", { class: "select" }, OPS.map((o) => h("option", { value: o, selected: gridState.filter && gridState.filter.op === o }, o)));
            const fval = h("input", { class: "input", placeholder: t.filterPlaceholder, value: gridState.filter ? gridState.filter.value || "" : "", onKeydown: (e) => { if (e.key === "Enter") applyFilter(); } });
            const syncVal = () => { fval.hidden = fop.value.startsWith("is "); }; fop.onchange = syncVal; syncVal();
            const applyFilter = () => { gridState.filter = { column: fcol.value, op: fop.value, value: fval.value }; gridState.offset = 0; loadPage(); };
            const toolbar = h("div", { class: "rdbToolbar" }, h("span", { class: "selectWrap" }, fcol, ico("chev-down", "ico chev")), h("span", { class: "selectWrap" }, fop, ico("chev-down", "ico chev")), fval, h("button", { type: "button", class: "btn outline sm", onClick: applyFilter }, t.filter),
              gridState.filter ? h("button", { type: "button", class: "rdbLink", onClick: () => { gridState.filter = null; gridState.offset = 0; loadPage(); } }, "×") : null,
              h("span", { class: "spacer" }),
              h("button", { type: "button", class: "btn outline sm", disabled: gridState.loading, onClick: () => loadPage() }, t.refresh),
              h("a", { class: "btn outline sm", href: `/api/rdb/export.csv?id=${encodeURIComponent(p.id)}&sql=${encodeURIComponent(`SELECT * FROM ${q(p.kind, st.table.schema)}.${q(p.kind, st.table.name)}`)}&name=${encodeURIComponent(`${st.table.schema}.${st.table.name}`)}`, download: "" }, t.exportCsv),
              editable ? h("button", { type: "button", class: "btn outline sm", onClick: () => { gridState.inserts.push({ values: {}, nulls: new Set() }); render(); } }, t.addRow) : null,
              editable ? h("button", { type: "button", class: "btn outline sm", disabled: !gridState.selected.size, onClick: () => { for (const i of gridState.selected) gridState.deletes.add(i); gridState.selected.clear(); render(); } }, t.deleteRows) : null);
            pane.append(toolbar);
            // table
            const wrap = h("div", { class: "rdbTableWrap" });
            const pg = gridState.page;
            if (!pg && gridState.loading) wrap.append(h("div", { class: "rdbEmpty" }, t.loading));
            else if (pg) {
              const pkSet = new Set(pg.primaryKey);
              const thead = h("tr", null, editable ? h("th", null, "") : null, pg.columns.map((c) => h("th", { "data-sortable": "", title: c.type, onClick: () => { const s = gridState.sort; gridState.sort = !s || s.column !== c.name ? { column: c.name, desc: false } : s.desc ? null : { column: c.name, desc: true }; gridState.offset = 0; loadPage(); } }, c.name, pkSet.has(c.name) ? h("span", { class: "pk" }, "PK") : null, gridState.sort && gridState.sort.column === c.name ? (gridState.sort.desc ? " ▼" : " ▲") : "")));
              const tbody = h("tbody");
              pg.rows.forEach((row, ri) => {
                const deleted = gridState.deletes.has(ri); const tr = h("tr", { "data-deleted": deleted ? "" : null });
                if (editable) tr.append(h("td", { class: "sel" }, h("input", { type: "checkbox", checked: gridState.selected.has(ri), onChange: (e) => { if (e.target.checked) gridState.selected.add(ri); else gridState.selected.delete(ri); render(); } })));
                row.forEach((v, ci) => {
                  const name = pg.columns[ci].name; const patch = gridState.edits[ri] && name in gridState.edits[ri] ? gridState.edits[ri][name] : undefined;
                  const val = patch === undefined ? v : patch;
                  const td = h("td", { "data-null": val === null ? "" : null, "data-dirty": patch !== undefined ? "" : null, title: typeof val === "string" ? val : null }, val === null ? "NULL" : typeof val === "object" ? JSON.stringify(val) : String(val));
                  if (editable && !deleted) td.ondblclick = () => editCell(td, ri, name, v, val);
                  tr.append(td);
                });
                tbody.append(tr);
              });
              gridState.inserts.forEach((ins, ii) => {
                const tr = h("tr", { "data-new": "" });
                tr.append(h("td", { class: "sel" }, h("button", { type: "button", class: "rdbLink", "data-danger": "", onClick: () => { gridState.inserts.splice(ii, 1); render(); } }, "×")));
                for (const c of pg.columns) tr.append(h("td", null, h("input", { class: "cellInput", value: ins.values[c.name] == null ? "" : ins.values[c.name], placeholder: ins.nulls.has(c.name) ? "NULL" : "", onInput: (e) => { ins.values[c.name] = e.target.value; ins.nulls.delete(c.name); } })));
                tbody.append(tr);
              });
              if (!pg.rows.length && !gridState.inserts.length) wrap.append(h("div", { class: "rdbEmpty" }, t.noTables));
              else wrap.append(h("table", { class: "rdbTable" }, h("thead", null, thead), tbody));
            }
            pane.append(wrap);
            // footer
            const total = pg && pg.total != null ? pg.total : null; const from = pg && pg.rows.length ? gridState.offset + 1 : 0; const to = pg ? gridState.offset + pg.rows.length : 0;
            const pendingCount = Object.values(gridState.edits).filter((e) => Object.keys(e).length).length + gridState.inserts.length + gridState.deletes.size;
            pane.append(h("div", { class: "rdbFoot" }, h("span", null, pg ? (total != null ? t.rows(from, to, total) : t.rowsNoTotal(from, to)) : ""),
              h("button", { type: "button", class: "rdbLink", disabled: gridState.offset === 0 || gridState.loading, onClick: () => { gridState.offset = Math.max(0, gridState.offset - PAGE); loadPage(); } }, t.prev),
              h("button", { type: "button", class: "rdbLink", disabled: gridState.loading || !pg || pg.rows.length < PAGE, onClick: () => { gridState.offset += PAGE; loadPage(); } }, t.next),
              h("span", { class: "spacer" }),
              pendingCount ? h("span", null, t.pending(pendingCount)) : null,
              pendingCount ? h("button", { type: "button", class: "rdbLink", onClick: () => { gridState.edits = {}; gridState.inserts = []; gridState.deletes.clear(); gridState.selected.clear(); render(); } }, t.discard) : null,
              pendingCount ? h("button", { type: "button", class: "btn primary sm", onClick: () => saveChanges(p) }, t.saveChanges) : null));
            return pane;
          }
          async function loadPage() {
            gridState.loading = true; render();
            try { const d = await call("/rows", { method: "POST", body: JSON.stringify({ id: st.active, schema: st.table.schema, table: st.table.name, offset: gridState.offset, limit: PAGE, sort: gridState.sort || undefined, filters: gridState.filter ? [gridState.filter] : [] }) }); gridState.page = d.page; gridState.edits = {}; gridState.deletes.clear(); gridState.selected.clear(); }
            catch (err) { fail(err); }
            gridState.loading = false; render();
          }
          function editCell(td, ri, name, original, current) {
            const input = h("input", { class: "cellInput", value: current === null ? "" : typeof current === "object" ? JSON.stringify(current) : String(current) });
            let isNull = current === null;
            const commit = (cancel) => {
              if (cancel) { render(); return; }
              const value = isNull ? null : input.value;
              const same = (value === null && original === null) || (value !== null && original !== null && String(original) === value);
              const row = (gridState.edits[ri] ||= {});
              if (same) delete row[name]; else row[name] = value;
              render();
            };
            const nullBtn = h("button", { type: "button", class: "nullBtn", title: t.setNull, onMousedown: (e) => { e.preventDefault(); isNull = true; input.value = ""; commit(false); } }, "∅");
            input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); input.onblur = null; commit(false); } else if (e.key === "Escape") { input.onblur = null; commit(true); } };
            input.oninput = () => { isNull = false; };
            input.onblur = () => commit(false);
            td.replaceChildren(input, nullBtn); td.removeAttribute("data-null"); input.focus(); input.select();
          }
          async function saveChanges(p) {
            const pg = gridState.page; const pk = pg.primaryKey; const names = pg.columns.map((c) => c.name);
            const keyOf = (row) => Object.fromEntries(pk.map((k) => [k, row[names.indexOf(k)]]));
            const changes = [];
            for (const [ri, values] of Object.entries(gridState.edits)) if (Object.keys(values).length && !gridState.deletes.has(+ri)) changes.push({ kind: "update", key: keyOf(pg.rows[+ri]), values });
            for (const ins of gridState.inserts) changes.push({ kind: "insert", values: Object.fromEntries(Object.entries(ins.values).filter(([, v]) => v !== "")), nulls: [...ins.nulls] });
            for (const ri of gridState.deletes) changes.push({ kind: "delete", key: keyOf(pg.rows[ri]) });
            const base = { id: p.id, schema: st.table.schema, table: st.table.name, changes };
            try {
              const preview = (await call("/changes", { method: "POST", body: JSON.stringify({ ...base, apply: false }) })).result;
              if (!(await confirmSql(t.confirmTitle, t.confirmBody(preview.statements.length), preview.statements.join(";\n") + ";", t.confirmOk))) return;
              const r = (await call("/changes", { method: "POST", body: JSON.stringify({ ...base, apply: true }) })).result;
              if (r.applied) { setBanner("ok", t.applied(r.statements.length, r.affected)); gridState.edits = {}; gridState.inserts = []; gridState.deletes.clear(); loadPage(); }
              else setBanner("error", t.failed(r.error || "?"));
            } catch (err) { fail(err); }
          }

          // ---------------------------------------------------------- structure
          function structure(p) {
            const info = st.info;
            const table = (head, rows) => h("div", { class: "rdbTableWrap", style: { flex: "none", maxHeight: "40vh" } }, h("table", { class: "rdbTable" }, h("thead", null, h("tr", null, head.map((x) => h("th", null, x)))), h("tbody", null, rows.map((r) => h("tr", null, r.map((c) => h("td", { "data-null": c === null ? "" : null }, c === null ? "" : c)))))));
            const box = h("div", { class: "rdbStruct" },
              h("h3", null, t.colName, info.estimatedRows != null ? h("small", null, t.approxRows(info.estimatedRows)) : null),
              table([t.colName, t.colType, t.colNullable, t.colDefault, t.colPk], info.columns.map((c) => [c.name, c.type, c.nullable ? "YES" : "NO", c.defaultValue, c.primaryKey ? "PK" : ""])));
            if (info.indexes.length) box.append(h("h3", null, t.indexes), table([t.colName, t.colName === "Column" ? "Columns" : "列", ""], info.indexes.map((i) => [i.name, i.columns.join(", "), i.primary ? "PRIMARY" : i.unique ? "UNIQUE" : ""])));
            const pre = h("pre", null, t.loading); box.append(h("h3", null, t.ddl), pre);
            call(`/ddl?id=${encodeURIComponent(p.id)}&schema=${encodeURIComponent(info.table.schema)}&table=${encodeURIComponent(info.table.name)}&kind=${info.table.kind}`).then((d) => { pre.textContent = d.ddl; }).catch((err) => { pre.textContent = err.message; });
            return box;
          }

          // ---------------------------------------------------------- sql editor
          const sqlState = { key: null, text: "", result: null, ran: "" };
          function sqlEditor(p) {
            if (sqlState.key !== p.id) { sqlState.key = p.id; sqlState.result = null; sqlState.text = st.table ? `SELECT * FROM ${q(p.kind, st.table.schema)}.${q(p.kind, st.table.name)} LIMIT 100` : ""; }
            const ta = h("textarea", { placeholder: t.sqlPlaceholder, spellcheck: "false", onInput: (e) => { sqlState.text = e.target.value; runBtn.disabled = !sqlState.text.trim(); } }, sqlState.text);
            ta.onkeydown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); } };
            const runBtn = h("button", { type: "button", class: "btn primary sm", disabled: !sqlState.text.trim(), onClick: () => run() }, ico("play", "ico"), h("span", null, t.run));
            const status = h("div", { class: "status" });
            const out = h("div", { class: "rdbTableWrap" });
            const pane = h("div", { class: "rdbPane rdbSql" }, ta, h("div", { class: "rdbToolbar" }, runBtn, status), out);
            function drawResult() {
              status.replaceChildren(); out.replaceChildren();
              const r = sqlState.result; if (!r) return;
              const text = r.columns.length ? t.result(r.rowCount, r.durationMs) : t.affected(r.command, r.rowCount, r.durationMs);
              status.append(h("span", null, text + (r.truncated ? " " + t.truncated(r.rowCount) : "")));
              if (r.columns.length && looksReadOnly(sqlState.ran)) status.append(h("a", { class: "rdbLink", href: `/api/rdb/export.csv?id=${encodeURIComponent(p.id)}&sql=${encodeURIComponent(sqlState.ran)}&name=query`, download: "" }, t.exportResult));
              if (r.columns.length) {
                if (!r.rows.length) out.append(h("div", { class: "rdbEmpty" }, t.noTables));
                else out.append(h("table", { class: "rdbTable" }, h("thead", null, h("tr", null, r.columns.map((c) => h("th", { title: c.type }, c.name)))), h("tbody", null, r.rows.map((row) => h("tr", null, row.map((v) => h("td", { "data-null": v === null ? "" : null }, v === null ? "NULL" : typeof v === "object" ? JSON.stringify(v) : String(v))))))));
              }
            }
            async function run() {
              const sel = ta.value.substring(ta.selectionStart, ta.selectionEnd).trim(); const sql = sel || ta.value.trim(); if (!sql) return;
              if (!looksReadOnly(sql) && !(await confirmSql(t.confirmTitle, t.confirmWrite(firstWord(sql)), sql, t.confirmOk))) return;
              runBtn.disabled = true; runBtn.lastChild.textContent = t.running;
              try { sqlState.result = (await call("/query", { method: "POST", body: JSON.stringify({ id: p.id, sql, maxRows: 1000 }) })).result; sqlState.ran = sql; if (st.banner && st.banner.kind === "error") setBanner(null); drawResult(); }
              catch (err) { setBanner("error", t.sqlError(err.message)); }
              runBtn.disabled = false; runBtn.lastChild.textContent = t.run;
            }
            drawResult();
            return pane;
          }

          // ---------------------------------------------------------- render
          let sideBox = null;
          function render() {
            if (!alive) return;
            const s = side(); treeBox = s.querySelector(".rdbTree");
            root.replaceChildren(header(), bannerBox, h("div", { class: "rdbBody" }, s, work()));
            renderBanner(); sideBox = s;
          }
          render(); load();
          return () => { alive = false; };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "rdb", label: t.entry, icon: "database", description: t.intro, order: 40 });
        ctx.slots.register({ slot: "main", key: "rdb", label: t.entry }, page);
      },
    };
  },
});
