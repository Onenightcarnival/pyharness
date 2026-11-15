window.__PyhModules__.load({
  id: "gateway",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: {
        title: "API 网关", entry: "API 网关", close: "关闭",
        intro: "以 OpenAI Chat Completions、OpenAI Responses 与 Anthropic Messages 协议提供已配置的模型，带独立监听、API key 与逐请求用量统计。",
        tabs: { overview: "概览", keys: "API key", usage: "用量" },
        endpointModels: "可用模型清单", endpointChat: "OpenAI Chat Completions", endpointResponses: "OpenAI Responses",
        endpointMessages: "Anthropic Messages", endpointAuthHint: "请求头 Authorization: Bearer <key> 或 x-api-key: <key>。",
        loading: "正在读取…", refresh: "刷新", save: "保存", saved: "已保存", cancel: "取消", confirm: "确定",
        listenerTitle: "监听", listenerEnabled: "启用网关", listenerHost: "地址", listenerPort: "端口",
        listenerHostHint: "非回环地址对局域网开放，所有请求都需要 API key。",
        listenerOn: (url) => `监听中：${url}`, listenerOff: "未启用", listenerError: (error) => `无法监听：${error}`,
        listenerEndpoints: "端点",
        modelsTitle: "模型", modelsEmpty: "尚未配置模型。",
        keysTitle: "API key", keysName: "名称", keysModels: "可用模型", keysModelsAll: "全部模型",
        keysModelsHint: "未勾选任何模型时允许全部模型。", keysModelsCount: (count) => `${count} 个模型`,
        keysPickTitle: "选择可用模型", keysPickHint: "勾选该 key 可以调用的模型；全部不勾选表示不限制。",
        keysPickAll: "清空（全部模型）", keysPickStale: "当前未提供此模型", keysSearch: "搜索模型…",
        keysPickExpand: "展开", keysPickCollapse: "收起", keysPickGroupCount: (picked, total) => `${picked} / ${total}`,
        keysCreate: "新建 key", keysCreated: "新 key 已创建，请立即复制：", keysCopy: "复制", keysCopied: "已复制",
        keysReveal: "显示", keysHide: "隐藏", keysDisable: "停用", keysEnable: "启用", keysDelete: "删除",
        keysDeleteConfirm: "删除此 key？使用它的客户端将立即失效。", keysDisabled: "已停用", keysLastUsed: "最近使用",
        keysNever: "从未使用", keysEmpty: "暂无 API key。",
        usageTitle: "用量", usageRange: { today: "今日", "7d": "7 日", "30d": "30 日" },
        usageRequests: "请求", usageErrors: "失败", usageInput: "输入 token", usageOutput: "输出 token",
        usageCacheRead: "缓存命中", usageReasoning: "推理 token", usageCost: "费用",
        usageTime: "时间", usageProtocol: "协议", usageModel: "模型", usageKey: "key",
        usageTtft: "首字节", usageDuration: "耗时", usageStatus: "状态", usageEmpty: "所选范围内没有请求。", usageStream: "流式",
        usageFilterKey: "key", usageFilterModel: "模型", usageFilterProtocol: "协议", usageFilterOutcome: "结果",
        usageFilterAll: "全部", usageOutcomeOk: "成功", usageOutcomeError: "失败", usageReset: "重置筛选",
        usageDetails: "请求明细", usageMatched: (shown, total) => `${shown} / ${total} 条`,
        usageTruncated: (limit) => `仅显示最新 ${limit} 条，请收窄筛选条件。`,
        usageInputShort: "输入", usageOutputShort: "输出", usageCacheShort: "缓存", usageReasoningShort: "推理",
        usageError: "错误码", errorGeneric: (message) => `操作失败：${message}`,
      },
      en: {
        title: "API gateway", entry: "API gateway", close: "Close",
        intro: "Serves the configured models over the OpenAI Chat Completions, OpenAI Responses and Anthropic Messages protocols, on a listener of its own with API keys and per-request usage accounting.",
        tabs: { overview: "Overview", keys: "API keys", usage: "Usage" },
        endpointModels: "Available models", endpointChat: "OpenAI Chat Completions", endpointResponses: "OpenAI Responses",
        endpointMessages: "Anthropic Messages", endpointAuthHint: "Send Authorization: Bearer <key> or x-api-key: <key>.",
        loading: "Loading…", refresh: "Refresh", save: "Save", saved: "Saved", cancel: "Cancel", confirm: "Confirm",
        listenerTitle: "Listener", listenerEnabled: "Enable gateway", listenerHost: "Address", listenerPort: "Port",
        listenerHostHint: "A non-loopback address is reachable from the local network; every request needs an API key.",
        listenerOn: (url) => `Listening: ${url}`, listenerOff: "Disabled", listenerError: (error) => `Cannot listen: ${error}`,
        listenerEndpoints: "Endpoints",
        modelsTitle: "Models", modelsEmpty: "No models are configured.",

        keysTitle: "API keys", keysName: "Name", keysModels: "Allowed models", keysModelsAll: "All models",
        keysModelsHint: "A key with no models selected may use every model.", keysModelsCount: (count) => `${count} models`,
        keysPickTitle: "Select available models",
        keysPickHint: "Tick the models this key may call; leaving every box empty allows all of them.",
        keysPickAll: "Clear (all models)", keysPickStale: "Not offered right now", keysSearch: "Search models…",
        keysPickExpand: "Expand", keysPickCollapse: "Collapse", keysPickGroupCount: (picked, total) => `${picked} / ${total}`,
        keysCreate: "Create key", keysCreated: "New key created; copy it now:", keysCopy: "Copy", keysCopied: "Copied",
        keysReveal: "Show", keysHide: "Hide", keysDisable: "Disable", keysEnable: "Enable", keysDelete: "Delete",
        keysDeleteConfirm: "Delete this key? Clients using it stop working immediately.", keysDisabled: "Disabled",
        keysLastUsed: "Last used", keysNever: "Never used", keysEmpty: "No API keys.",
        usageTitle: "Usage", usageRange: { today: "Today", "7d": "7 days", "30d": "30 days" },
        usageRequests: "Requests", usageErrors: "Failed", usageInput: "Input tokens", usageOutput: "Output tokens",
        usageCacheRead: "Cache hits", usageReasoning: "Reasoning tokens", usageCost: "Cost",
        usageTime: "Time", usageProtocol: "Protocol", usageModel: "Model", usageKey: "Key",
        usageTtft: "First byte", usageDuration: "Duration", usageStatus: "Status",
        usageEmpty: "No requests in the selected range.", usageStream: "stream",
        usageFilterKey: "Key", usageFilterModel: "Model", usageFilterProtocol: "Protocol", usageFilterOutcome: "Outcome",
        usageFilterAll: "All", usageOutcomeOk: "Succeeded", usageOutcomeError: "Failed", usageReset: "Reset filters",
        usageDetails: "Request details", usageMatched: (shown, total) => `${shown} / ${total} rows`,
        usageTruncated: (limit) => `Only the newest ${limit} rows are shown; narrow the filters.`,
        usageInputShort: "Input", usageOutputShort: "Output", usageCacheShort: "Cache", usageReasoningShort: "Reasoning",
        usageError: "Error code", errorGeneric: (message) => `Operation failed: ${message}`,

      },
    };
    const TABS = ["overview", "keys", "usage"];
    const TAB_KEY = "pyh-gateway:tab";
    const RANGES = ["today", "7d", "30d"];
    const PROTOCOLS = ["chat", "responses", "messages"];
    const ENDPOINTS = [
      ["GET /v1/models", "endpointModels"], ["POST /v1/chat/completions", "endpointChat"],
      ["POST /v1/responses", "endpointResponses"], ["POST /v1/messages", "endpointMessages"],
    ];
    // Usage filter fields; each is sent as the query parameter of the same name, the empty string matches every row.
    const FILTERS = ["key", "model", "protocol", "outcome"];
    const DETAIL_LIMIT = 200;

    async function call(path, opts) {
      const init = { headers: { "content-type": "application/json" }, cache: "no-store", ...(opts || {}) };
      const res = await fetch("/api/gateway" + path, init);
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const d = (await res.json()).detail;
          // FastAPI: a string from HTTPException, a list of { loc, msg } from request validation.
          const issue = (item) => (item && item.msg ? `${(item.loc || []).slice(1).join(".")}: ${item.msg}` : "");
          if (typeof d === "string") detail = d;
          else if (Array.isArray(d)) detail = d.map(issue).filter(Boolean).join("; ") || detail;
        } catch { /* no body */ }
        throw new Error(detail);
      }
      return res.json();
    }
    const send = (method, path, body) => call(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
    const keyPath = (id) => `/keys?id=${encodeURIComponent(id)}`;

    // 1 234 → 1.23K, 5 600 000 → 5.6M; values under 1 000 stay exact.
    const compact = new Intl.NumberFormat("en-US", { notation: "compact", compactDisplay: "short", maximumSignificantDigits: 3 });
    const fmtNumber = (value) => Number(value || 0).toLocaleString();
    const fmtCompact = (value) => (Math.abs(Number(value || 0)) < 1000 ? fmtNumber(value) : compact.format(value));
    const fmtCost = (value) => value.toFixed(value >= 1 ? 2 : 4);
    const fmtTime = (ms) => new Date(ms).toLocaleString();
    const listenUrl = (at) => `http://${at.host.includes(":") ? `[${at.host}]` : at.host}:${at.port}/v1`;
    const readTab = () => {
      try { const stored = localStorage.getItem(TAB_KEY); return TABS.includes(stored) ? stored : "overview"; } catch { return "overview"; }
    };
    const freshKeys = () => ({ name: "", models: null, created: null, createdCopied: null, revealed: {}, copied: null });
    const freshUsage = () => (
      { range: "today", filter: { key: "", model: "", protocol: "", outcome: "" }, summary: null, error: "", gen: 0 });
    function groupByProvider(models) {
      const groups = new Map();
      for (const model of models) {
        if (!groups.has(model.provider)) groups.set(model.provider, { provider: model.provider, name: model.providerName, models: [] });
        groups.get(model.provider).models.push(model);
      }
      return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
    }

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        const style = document.createElement("style");
        style.textContent = `
          .gw-page > * { max-width: 1120px; }
          .gw-titleRow { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-width: 0; }
          .gw-badge { display: inline-block; max-width: min(100%, 520px); overflow: hidden; text-overflow: ellipsis; }
          .gw-tabs { display: flex; gap: 2px; margin-top: 8px; border-bottom: 0.5px solid var(--border-l2); }
          .gw-tabs button { padding: 6px 12px; margin-bottom: -1px; border: none; border-bottom: 2px solid transparent; background: transparent; font-size: 13px; color: var(--label-secondary); }
          .gw-tabs button[aria-selected="true"] { color: var(--label-primary); font-weight: 500; border-bottom-color: var(--info); }
          .gw-body { display: flex; flex-direction: column; gap: 14px; padding-top: 14px; }
          .gw-body .group { margin-top: 10px; gap: 10px; }
          .gw-notice { display: flex; align-items: center; gap: 8px; padding: 7px 12px; border-radius: 8px; font-size: 12.5px; line-height: 18px; background: var(--hover); color: var(--label-secondary); }
          .gw-notice > span { flex: 1; min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
          .gw-notice[data-kind="ok"] { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }
          .gw-notice[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .gw-row { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; }
          .gw-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--label-secondary); }
          .gw-field .input, .gw-field .select, .gw-field > .btn, .gw-row > .btn, .gw-filters > .btn { height: 32px; }
          .gw-field .selectWrap .chev { top: 8px; }
          .gw-switch { display: inline-flex; align-items: center; gap: 8px; align-self: flex-start; font-size: 13px; cursor: pointer; }
          .gw-hint { font-size: 12px; line-height: 18px; color: var(--label-tertiary); }
          .gw-empty { padding: 6px 0; font-size: 12.5px; color: var(--label-tertiary); }
          .gw-mono { font-family: var(--mono); font-size: 12px; }
          .gw-code { padding: 1px 5px; border-radius: 4px; background: var(--hover); font: 12px var(--mono); overflow-wrap: anywhere; }
          .gw-tableWrap { overflow-x: auto; border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .gw-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
          .gw-table th { text-align: left; padding: 8px 10px; font-weight: 500; color: var(--label-secondary); white-space: nowrap; border-bottom: 0.5px solid var(--border-l2); }
          .gw-table td { padding: 7px 10px; border-bottom: 0.5px solid var(--border-l2); vertical-align: middle; overflow-wrap: anywhere; }
          .gw-table tbody tr:last-child td { border-bottom: none; }
          .gw-table tr[data-off] { opacity: .6; }
          .gw-table td.gw-actions { white-space: nowrap; text-align: right; }
          .gw-table td.gw-fit { width: 1%; white-space: nowrap; }
          .gw-table td.gw-actions .btn { margin-left: 4px; }
          .gw-table .btn { white-space: nowrap; }
          .gw-table .gw-num { text-align: right; font-family: var(--mono); }
          .gw-table td[data-bad] { color: var(--error); }
          .gw-wide th, .gw-wide td { white-space: nowrap; }
          .gw-wide td.gw-wrap { white-space: normal; min-width: 220px; }
          .gw-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
          .gw-stat { padding: 10px 12px; border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .gw-statLabel { margin-bottom: 4px; font-size: 11px; color: var(--label-tertiary); }
          .gw-statValue { font: 18px/24px var(--mono); }
          .gw-filters { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; padding: 12px 14px; border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .gw-filters .selectWrap { min-width: 140px; max-width: 260px; }
          .gw-filters .select { font-size: 12.5px; }
          .gw-ranges { display: inline-flex; align-self: flex-start; padding: 3px; border-radius: 8px; background: var(--hover); }
          .gw-ranges button { height: 26px; padding: 0 12px; border: none; border-radius: 6px; background: transparent; font-size: 12px; color: var(--label-secondary); }
          .gw-ranges button[aria-pressed="true"] { background: var(--bg-layer-3); color: var(--label-primary); box-shadow: 0 0 0 0.5px var(--border-l2); }
          .gw-pickHead { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
          .gw-pickBody { display: flex; flex-direction: column; gap: 10px; overflow: hidden; }
          .gw-pickBody > .gw-hint { margin: 0 4px; }
          .gw-pickTools { display: flex; align-items: center; gap: 8px; margin: 0 4px; }
          .gw-pickTools .input { flex: 1; min-width: 160px; width: auto; margin: 0; }
          .gw-list { flex: 0 1 auto; min-height: 120px; overflow: auto; margin: 0 4px 2px; border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .gw-list > .gw-empty { padding: 12px; }
          .gw-list input[type="checkbox"] { flex: none; margin: 0; accent-color: var(--info); }
          .gw-groupHead { display: flex; align-items: center; gap: 6px; padding: 6px 10px; background: var(--hover); border-bottom: 0.5px solid var(--border-l2); }
          .gw-groupLabel { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; cursor: pointer; }
          .gw-groupCount { font-size: 11.5px; font-weight: 400; color: var(--label-tertiary); }
          .gw-checkRow { display: flex; align-items: center; gap: 10px; padding: 7px 12px; border-bottom: 0.5px solid var(--border-l2); font-size: 13px; cursor: pointer; }
          .gw-checkRow:last-child { border-bottom: none; }
          .gw-checkRow:hover { background: var(--hover); }
          .gw-checkRow[data-child] { padding-left: 44px; }
          .gw-checkRow[data-stale] { opacity: .6; }
          .gw-checkMain { display: flex; flex-direction: column; min-width: 0; }
          .gw-checkMain .gw-mono { overflow-wrap: anywhere; }
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
        const allowlistLabel = (models) => (models == null ? t.keysModelsAll : t.keysModelsCount(models.length));
        const box = (kind, role, ...children) => h("div", { class: "gw-notice", "data-kind": kind, role }, children);
        const stat = (label, value, exact) => h("div", { class: "gw-stat" },
          h("div", { class: "gw-statLabel" }, label), h("div", { class: "gw-statValue", title: exact }, value));
        const group = (title, meta, ...children) => h("section", { class: "group" },
          h("div", { class: "groupHead" }, h("h2", { class: "groupTitle" }, title), meta == null ? null : h("span", { class: "groupMeta" }, meta)), children);
        // The node that carries the same data-k after a redraw takes the focus (and the caret) of the one it replaced.
        function redraw(container, draw) {
          const active = container.contains(document.activeElement) ? document.activeElement : null;
          const key = active ? active.dataset.k : undefined;
          const caret = key && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
          draw();
          if (!key) return;
          const next = [...container.querySelectorAll("[data-k]")].find((node) => node.dataset.k === key);
          if (!next || next.disabled) return;
          next.focus({ preventScroll: true });
          if (caret) next.setSelectionRange(caret[0], caret[1]);
        }

        // ------------------------------------------------------------ model picker
        // Provider → model tree with checkboxes. A provider box selects or clears every model under it and shows the
        // partial state. An empty selection means every model and is handed back as null.
        function openPicker(models, selected, onConfirm) {
          const picked = new Set(selected || []);
          const known = new Set(models.map((model) => model.id));
          const groups = groupByProvider(models);
          // One provider opens by itself; otherwise providers with a picked model open.
          const opened = groups.length <= 1 ? groups : groups.filter((g) => g.models.some((m) => picked.has(m.id)));
          const expanded = new Set(opened.map((g) => g.provider));
          let query = "";
          const { el, close } = modal("", true);
          const card = el.firstChild; card.setAttribute("aria-labelledby", "gw-picker-title");
          const list = h("div", { class: "gw-list" });
          const summary = h("span", { class: "count" });
          const clear = h("button", { type: "button", class: "btn outline sm", onClick: () => { picked.clear(); draw(); } }, t.keysPickAll);
          const search = h("input", { class: "input", placeholder: t.keysSearch, spellcheck: "false",
            onInput: () => { query = search.value; draw(); } });
          const flip = (set, value, on) => { if (on) set.add(value); else set.delete(value); };
          const check = (key, checked, onChange) => {
            const input = h("input", { type: "checkbox", "data-k": key, onChange }); input.checked = checked; return input;
          };
          const row = (id, hint, attr) => h("label", { class: "gw-checkRow", [attr]: "" },
            check(`model:${id}`, picked.has(id), () => { flip(picked, id, !picked.has(id)); draw(); }),
            h("span", { class: "gw-checkMain" }, h("span", { class: "gw-mono" }, id), h("span", { class: "gw-hint" }, hint)));
          function tree() {
            const needle = query.trim().toLowerCase();
            const rows = models.length ? [] : [h("div", { class: "gw-empty" }, t.modelsEmpty)];
            for (const g of groups) {
              const shown = g.models.filter((m) => `${m.id} ${m.name} ${m.providerName}`.toLowerCase().includes(needle));
              if (!shown.length) continue;
              const count = g.models.filter((m) => picked.has(m.id)).length;
              const all = count === g.models.length;
              const open = needle !== "" || expanded.has(g.provider);
              const every = check(`group:${g.provider}`, all, () => {
                for (const m of g.models) flip(picked, m.id, every.checked);
                draw();
              });
              every.indeterminate = !all && count > 0;
              const caret = h("button", { type: "button", class: "iconButton sm", "data-k": `caret:${g.provider}`,
                "aria-label": open ? t.keysPickCollapse : t.keysPickExpand, "aria-expanded": String(open),
                onClick: () => { flip(expanded, g.provider, !expanded.has(g.provider)); draw(); } }, ico(open ? "chev-down" : "chev-right"));
              rows.push(h("div", { role: "group", "aria-label": g.name },
                h("div", { class: "gw-groupHead" }, caret, h("label", { class: "gw-groupLabel" }, every, h("span", null, g.name),
                  h("span", { class: "gw-groupCount" }, t.keysPickGroupCount(count, g.models.length)))),
                open ? shown.map((m) => row(m.id, m.name, "data-child")) : null));
            }
            // Ids of a stored allowlist that are not offered now stay selectable so saving does not drop them silently.
            for (const id of picked) if (!known.has(id)) rows.push(row(id, t.keysPickStale, "data-stale"));
            return rows;
          }
          function draw() {
            const top = list.scrollTop;
            redraw(list, () => list.replaceChildren(...tree()));
            list.scrollTop = top;
            clear.disabled = picked.size === 0;
            summary.textContent = allowlistLabel(picked.size === 0 ? null : [...picked]);
          }
          card.append(
            h("div", { class: "modalHead gw-pickHead" }, h("span", { id: "gw-picker-title" }, t.keysPickTitle),
              h("button", { type: "button", class: "iconButton sm", title: t.close, "aria-label": t.close, onClick: close }, ico("x"))),
            h("div", { class: "modalBody gw-pickBody" },
              h("div", { class: "gw-hint" }, t.keysPickHint), h("div", { class: "gw-pickTools" }, search, clear), list),
            h("div", { class: "modalFoot" }, summary, h("span", { class: "spacer" }),
              h("button", { type: "button", class: "btn outline", onClick: close }, t.cancel),
              h("button", { type: "button", class: "btn primary",
                onClick: () => { close(); onConfirm(picked.size === 0 ? null : [...picked]); } }, t.confirm)));
          draw(); search.focus();
          return close;
        }

        // ------------------------------------------------------------ page
        function page(el) {
          let alive = true; let closeDialog = null;
          const st = { status: null, notice: null, busy: false, tab: readTab() };
          // Tab-local state lives while its tab is selected: leaving a tab drops the listener draft, the revealed and
          // freshly created keys, and the usage range and filters.
          let draft = null; let ks = freshKeys(); let us = freshUsage();
          const root = h("div", { class: "page gw-page" }); el.replaceChildren(root);
          const fail = (err) => { st.notice = { kind: "error", text: t.errorGeneric((err && err.message) || String(err)) }; };
          const resetDraft = () => { const s = st.status.settings; draft = { enabled: s.enabled, host: s.host, port: String(s.port) }; };

          async function fetchStatus() { st.status = await call("/status"); resetDraft(); }
          async function refresh() {
            try { await fetchStatus(); st.notice = null; } catch (err) { fail(err); }
            render();
            if (st.status && st.tab === "usage") loadUsage();
          }
          async function run(action, ok) {
            st.busy = true; render();
            try { await action(); st.notice = ok === undefined ? null : { kind: "ok", text: ok }; } catch (err) { fail(err); }
            st.busy = false; render();
          }
          function selectTab(tab) {
            if (tab === st.tab) return;
            st.tab = tab; try { localStorage.setItem(TAB_KEY, tab); } catch { /* optional */ }
            if (st.status) resetDraft();
            ks = freshKeys(); us = freshUsage();
            render();
            if (st.status && tab === "usage") loadUsage();
          }
          // A timed flag (the "copied" label): set now, cleared after 1.5 s unless it changed in between.
          function flash(state, field, value) {
            state[field] = value; render();
            setTimeout(() => { if (state[field] !== value) return; state[field] = null; if (state === ks) render(); }, 1500);
          }

          // -------------------------------------------------------- head, tabs
          function listenerState() {
            const s = st.status;
            if (s.listening) return { kind: "ok", tone: "success", text: t.listenerOn(listenUrl(s.listening)) };
            if (s.listenError) return { kind: "error", tone: "danger", text: t.listenerError(s.listenError) };
            return { kind: "info", tone: "outline", text: t.listenerOff };
          }
          function head() {
            const state = st.status ? listenerState() : null;
            return h("div", { class: "pageHead" },
              h("div", null,
                h("div", { class: "gw-titleRow" }, h("h1", { class: "pageTitle" }, t.title),
                  state ? h("span", { class: "tag gw-badge", "data-tone": state.tone, title: state.text }, state.text) : null),
                h("p", { class: "pageIntro" }, t.intro)),
              h("div", { class: "headTools" },
                h("button", { type: "button", class: "btn outline sm", "data-k": "refresh", disabled: st.busy, onClick: refresh },
                  ico("refresh"), h("span", null, t.refresh))));
          }
          function tabsBar() {
            return h("div", { class: "gw-tabs", role: "tablist", "aria-label": t.title },
              TABS.map((tab) => h("button", { type: "button", role: "tab", id: `gw-tab-${tab}`, "data-k": `tab:${tab}`,
                "aria-selected": String(st.tab === tab), "aria-controls": `gw-panel-${tab}`, onClick: () => selectTab(tab) }, t.tabs[tab])));
          }

          // -------------------------------------------------------- overview
          function save() {
            return run(async () => {
              const settings = { ...st.status.settings, enabled: draft.enabled, host: draft.host, port: Number(draft.port) };
              st.status = await send("PUT", "/settings", settings);
              resetDraft();
            }, t.saved);
          }
          function overview() {
            const s = st.status; const state = listenerState(); const d = draft;
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(d.enabled), "data-k": "enabled",
              onClick: () => { d.enabled = !d.enabled; sw.setAttribute("aria-checked", String(d.enabled)); } }, h("span", { class: "knob" }));
            const field = (label, key, width, attrs) => h("label", { class: "gw-field" }, label,
              h("input", { class: "input mono", style: { width }, value: d[key], "data-k": key, ...attrs, onInput: (e) => { d[key] = e.target.value; } }));
            return [
              group(t.listenerTitle, null,
                box(state.kind, null, h("span", null, state.text)),
                h("label", { class: "gw-switch" }, sw, h("span", null, t.listenerEnabled)),
                h("div", { class: "gw-row" },
                  field(t.listenerHost, "host", "220px", { spellcheck: "false" }), field(t.listenerPort, "port", "110px", { inputmode: "numeric" })),
                h("div", { class: "gw-hint" }, t.listenerHostHint),
                h("div", { class: "gw-row" },
                  h("button", { type: "button", class: "btn primary sm", "data-k": "save", disabled: st.busy, onClick: save }, t.save))),
              group(t.listenerEndpoints, null,
                h("div", { class: "gw-tableWrap" }, h("table", { class: "gw-table" }, h("tbody", null,
                  ENDPOINTS.map(([route, key]) => h("tr", null, h("td", { class: "gw-fit" }, h("code", { class: "gw-code" }, route)), h("td", null, t[key])))))),
                h("div", { class: "gw-hint" }, t.endpointAuthHint)),
              h("div", { class: "gw-stats" },
                stat(t.modelsTitle, s.models.length), stat(t.keysTitle, `${s.keys.filter((key) => key.enabled).length} / ${s.keys.length}`)),
            ];
          }

          // -------------------------------------------------------- keys
          const reveal = (key) => run(async () => {
            const k = ks;
            if (k.revealed[key.id] !== undefined) { delete k.revealed[key.id]; return; }
            k.revealed[key.id] = (await call(keyPath(key.id))).key;
          });
          const copyKey = (key) => run(async () => {
            const k = ks;
            const value = k.revealed[key.id] !== undefined ? k.revealed[key.id] : (await call(keyPath(key.id))).key;
            await navigator.clipboard.writeText(value);
            flash(k, "copied", key.id);
          });
          const toggleKey = (key) => run(async () => {
            await send("PATCH", "/keys", { id: key.id, enabled: !key.enabled });
            await fetchStatus();
          });
          const createKey = () => run(async () => {
            const k = ks;
            const result = await send("POST", "/keys", { name: k.name.trim() === "" ? "key" : k.name.trim(), models: k.models });
            k.created = result.key; k.name = ""; k.models = null;
            await fetchStatus();
          });
          async function copyCreated() {
            const k = ks;
            try { await navigator.clipboard.writeText(k.created); flash(k, "createdCopied", k.created); } catch (err) { fail(err); render(); }
          }
          function removeKey(key) {
            const k = ks;
            const { el: dialog, close } = modal(`<div class="modalHead">${esc(`${t.keysDelete} ${key.name}`)}</div>`
              + `<div class="modalBody"><p>${esc(t.keysDeleteConfirm)}</p></div>`
              + `<div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button>`
              + `<button type="button" class="btn primary" data-yes style="background:var(--error)">${esc(t.keysDelete)}</button></div>`);
            closeDialog = close;
            dialog.querySelector("[data-no]").onclick = close;
            dialog.querySelector("[data-yes]").onclick = () => {
              close();
              run(async () => { await call(keyPath(key.id), { method: "DELETE" }); delete k.revealed[key.id]; await fetchStatus(); });
            };
          }
          // Picker target: the creation form (null) or an existing key.
          function pickModels(target) {
            const k = ks;
            closeDialog = openPicker(st.status.models, target ? target.models : k.models, (next) => {
              if (!target) { k.models = next; render(); return; }
              run(async () => { await send("PATCH", "/keys", { id: target.id, models: next }); await fetchStatus(); }, t.saved);
            });
          }
          function keysTab() {
            const s = st.status; const k = ks;
            const act = (focusKey, label, onClick, cls) => h("button", { type: "button", class: `btn outline sm${cls || ""}`,
              "data-k": focusKey, disabled: st.busy, onClick }, label);
            const picker = (focusKey, models, target) => h("button", { type: "button", class: "btn outline sm", "data-k": focusKey,
              disabled: st.busy, title: models == null ? null : models.join(", "), onClick: () => pickModels(target) },
            h("span", null, allowlistLabel(models)), ico("chev-down"));
            const rows = s.keys.map((key) => h("tr", { "data-off": key.enabled ? null : "" },
              h("td", null, key.enabled ? key.name : `${key.name} (${t.keysDisabled})`),
              h("td", { class: "gw-mono" }, k.revealed[key.id] !== undefined ? k.revealed[key.id] : `${key.prefix}…`),
              h("td", null, picker(`models:${key.id}`, key.models, key)),
              h("td", null, key.lastUsedAt == null ? t.keysNever : fmtTime(key.lastUsedAt)),
              h("td", { class: "gw-actions" },
                act(`reveal:${key.id}`, k.revealed[key.id] === undefined ? t.keysReveal : t.keysHide, () => reveal(key)),
                act(`copy:${key.id}`, k.copied === key.id ? t.keysCopied : t.keysCopy, () => copyKey(key)),
                act(`toggle:${key.id}`, key.enabled ? t.keysDisable : t.keysEnable, () => toggleKey(key)),
                act(`delete:${key.id}`, t.keysDelete, () => removeKey(key), " danger"))));
            return [
              group(t.keysTitle, null,
                k.created ? box("ok", null, h("span", null, t.keysCreated, " ", h("code", { class: "gw-code" }, k.created)),
                  h("button", { type: "button", class: "btn outline sm", "data-k": "copyCreated", onClick: copyCreated },
                    k.createdCopied === k.created ? t.keysCopied : t.keysCopy)) : null,
                rows.length ? h("div", { class: "gw-tableWrap" }, h("table", { class: "gw-table" },
                  h("thead", null, h("tr", null, [t.keysName, t.usageKey, t.keysModels, t.keysLastUsed, ""].map((label) => h("th", null, label)))),
                  h("tbody", null, rows)))
                  : h("div", { class: "gw-empty" }, t.keysEmpty)),
              group(t.keysCreate, null,
                h("div", { class: "gw-row" },
                  h("label", { class: "gw-field" }, t.keysName,
                    h("input", { class: "input", style: { width: "180px" }, value: k.name, "data-k": "name", onInput: (e) => { k.name = e.target.value; } })),
                  h("div", { class: "gw-field" }, t.keysModels, picker("models:new", k.models, null)),
                  h("button", { type: "button", class: "btn primary sm", "data-k": "create", disabled: st.busy, onClick: createKey }, t.keysCreate)),
                h("div", { class: "gw-hint" }, t.keysModelsHint)),
            ];
          }

          // -------------------------------------------------------- usage
          // A reply is applied only while its request is the newest one of the usage state that issued it.
          async function loadUsage() {
            const u = us; const gen = ++u.gen;
            const params = new URLSearchParams({ range: u.range });
            for (const field of FILTERS) if (u.filter[field] !== "") params.set(field, u.filter[field]);
            try { const next = await call(`/usage?${params}`); if (u !== us || gen !== u.gen) return; u.summary = next; u.error = ""; }
            catch (err) { if (u !== us || gen !== u.gen) return; u.error = (err && err.message) || String(err); }
            render();
          }
          function usageTab() {
            const s = st.status; const u = us; const sum = u.summary;
            const facets = sum ? sum.facets
              : { keys: s.keys.map((key) => ({ id: key.id, name: key.name })), models: s.models.map((model) => model.id), protocols: PROTOCOLS };
            const named = (keys, id) => (keys.find((key) => key.id === id) || {}).name;
            const keyName = (row) => named(facets.keys, row.keyId) ?? named(s.keys, row.keyId) ?? row.keyName ?? row.keyId;
            const query = (change) => { change(); render(); loadUsage(); };
            // The current value stays listed even when the range no longer carries it.
            const filterSelect = (label, field, options) => {
              const value = u.filter[field];
              const listed = value === "" || options.some((option) => option.value === value) ? options : [...options, { value, label: value }];
              return h("label", { class: "gw-field" }, label, h("span", { class: "selectWrap" },
                h("select", { class: "select", "data-k": `filter:${field}`, onChange: (e) => query(() => { u.filter[field] = e.target.value; }) },
                  h("option", { value: "", selected: value === "" }, t.usageFilterAll),
                  listed.map((option) => h("option", { value: option.value, selected: option.value === value }, option.label))),
                ico("chev-down", "ico chev")));
            };
            const same = (id) => ({ value: id, label: id });
            const rangeButton = (range) => h("button", { type: "button", "data-k": `range:${range}`, "aria-pressed": String(range === u.range),
              onClick: () => { if (range !== u.range) query(() => { u.range = range; }); } }, t.usageRange[range]);
            const parts = [h("div", { class: "gw-filters" },
              h("div", { class: "gw-field" }, t.usageTitle,
                h("div", { class: "gw-ranges", role: "group", "aria-label": t.usageTitle }, RANGES.map(rangeButton))),
              filterSelect(t.usageFilterKey, "key", facets.keys.map((key) => ({ value: key.id, label: key.name }))),
              filterSelect(t.usageFilterModel, "model", facets.models.map(same)),
              filterSelect(t.usageFilterProtocol, "protocol", facets.protocols.map(same)),
              filterSelect(t.usageFilterOutcome, "outcome",
                [{ value: "ok", label: t.usageOutcomeOk }, { value: "error", label: t.usageOutcomeError }]),
              h("button", { type: "button", class: "btn outline sm", "data-k": "reset", disabled: FILTERS.every((field) => u.filter[field] === ""),
                onClick: () => query(() => { u.filter = freshUsage().filter; }) }, t.usageReset))];
            if (u.error) parts.push(box("error", "alert", h("span", null, u.error)));
            if (!sum) { if (!u.error) parts.push(h("div", { class: "gw-empty" }, t.loading)); return parts; }
            const totals = sum.totals;
            const metric = (label, value) => stat(label, fmtCompact(value), fmtNumber(value));
            parts.push(h("div", { class: "gw-stats" },
              metric(t.usageRequests, totals.requests), metric(t.usageErrors, totals.errors),
              metric(t.usageInput, totals.inputTokens), metric(t.usageOutput, totals.outputTokens),
              metric(t.usageCacheRead, totals.cacheReadTokens), metric(t.usageReasoning, totals.reasoningTokens),
              totals.cost != null ? stat(t.usageCost, fmtCost(totals.cost), fmtCost(totals.cost)) : null));
            const th = (label) => h("th", null, label);
            const thNum = (label) => h("th", { class: "gw-num" }, label);
            const tdNum = (value) => h("td", { class: "gw-num", title: fmtNumber(value) }, fmtCompact(value));
            const rows = sum.rows.map((row) => h("tr", null,
              h("td", null, fmtTime(row.time)),
              h("td", null, row.stream ? `${row.protocol} · ${t.usageStream}` : row.protocol),
              h("td", { class: "gw-mono gw-wrap" }, row.modelId),
              h("td", null, keyName(row)),
              [row.inputTokens, row.outputTokens, row.cacheReadTokens, row.reasoningTokens].map(tdNum),
              h("td", { class: "gw-num" }, row.ttftMs == null ? "—" : `${row.ttftMs} ms`),
              h("td", { class: "gw-num" }, `${row.durationMs} ms`),
              h("td", { "data-bad": row.status >= 400 ? "" : null }, row.status),
              h("td", { class: "gw-mono" }, row.errorCode ?? "")));
            parts.push(group(t.usageDetails, t.usageMatched(sum.rows.length, sum.matched),
              rows.length ? h("div", { class: "gw-tableWrap" }, h("table", { class: "gw-table gw-wide" },
                h("thead", null, h("tr", null, [t.usageTime, t.usageProtocol, t.usageModel, t.usageKey].map(th),
                  [t.usageInputShort, t.usageOutputShort, t.usageCacheShort, t.usageReasoningShort, t.usageTtft, t.usageDuration].map(thNum),
                  th(t.usageStatus), th(t.usageError))),
                h("tbody", null, rows))) : h("div", { class: "gw-empty" }, t.usageEmpty),
              sum.matched > sum.rows.length ? h("div", { class: "gw-hint" }, t.usageTruncated(DETAIL_LIMIT)) : null));
            return parts;
          }

          // -------------------------------------------------------- render
          function body() {
            const parts = [];
            const dismiss = () => { st.notice = null; render(); };
            if (st.notice) parts.push(box(st.notice.kind, st.notice.kind === "error" ? "alert" : "status", h("span", null, st.notice.text),
              h("button", { type: "button", class: "iconButton sm", title: t.close, "aria-label": t.close, onClick: dismiss }, ico("x"))));
            if (!st.status) parts.push(h("div", { class: "gw-empty" }, t.loading));
            else parts.push(...(st.tab === "overview" ? overview() : st.tab === "keys" ? keysTab() : usageTab()));
            return h("div", { class: "gw-body", role: "tabpanel", id: `gw-panel-${st.tab}`, "aria-labelledby": `gw-tab-${st.tab}` }, parts);
          }
          function render() {
            if (!alive) return;
            redraw(root, () => root.replaceChildren(head(), tabsBar(), body()));
          }
          render(); refresh();
          return () => { alive = false; if (closeDialog) closeDialog(); };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "gateway", label: t.entry, icon: "plug", description: t.intro, order: 70 });
        ctx.slots.register({ slot: "main", key: "gateway", label: t.entry }, page);
      },
    };
  },
});
