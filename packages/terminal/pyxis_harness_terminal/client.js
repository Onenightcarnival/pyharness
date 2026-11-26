window.__PyhModules__.load({
  id: "terminal",
  factory(require) {
    const { h, icon, esc, toast, json } = require("pyxis-harness");
    const L = {
      zh: { terminal: "终端", terminalDesc: "在工作区里打开一个交互式 shell", jobs: "后台任务", jobsDesc: "agent 启动的后台命令与它们的输出", newTerminal: "新终端", exited: (c) => `shell 已退出（退出码 ${c}）`, reconnect: "重新打开", unavailable: "此平台不支持终端", noJobs: "还没有后台任务", running: "运行中", exitedTag: "已结束", failed: "失败", killed: "已停止", kill: "停止", refresh: "刷新", output: "输出", back: "返回列表", started: "开始于", connecting: "连接中…", fallback: "xterm.js 未能加载；使用简易终端", send: "发送", inputPlaceholder: "输入命令，回车发送" },
      en: { terminal: "Terminal", terminalDesc: "Open an interactive shell in the workspace", jobs: "Jobs", jobsDesc: "Background commands started by the agent and their output", newTerminal: "New terminal", exited: (c) => `The shell exited (code ${c})`, reconnect: "Open again", unavailable: "Terminals are unavailable on this platform", noJobs: "No background jobs yet", running: "Running", exitedTag: "Done", failed: "Failed", killed: "Stopped", kill: "Stop", refresh: "Refresh", output: "Output", back: "Back to list", started: "Started", connecting: "Connecting…", fallback: "xterm.js did not load; using the plain terminal", send: "Send", inputPlaceholder: "Type a command and press Enter" },
    };
    const XTERM_JS = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.js";
    const XTERM_CSS = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css";
    const FIT = "https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.js";
    let xtermLoad = null;
    function loadXterm() {
      if (xtermLoad) return xtermLoad;
      xtermLoad = new Promise((resolve, reject) => {
        if (window.Terminal && window.FitAddon) return resolve();
        const css = document.createElement("link"); css.rel = "stylesheet"; css.href = XTERM_CSS; document.head.appendChild(css);
        const s1 = document.createElement("script"); s1.src = XTERM_JS;
        s1.onerror = () => reject(new Error("xterm failed to load"));
        s1.onload = () => { const s2 = document.createElement("script"); s2.src = FIT; s2.onload = resolve; s2.onerror = () => reject(new Error("fit addon failed to load")); document.head.appendChild(s2); };
        document.head.appendChild(s1);
      }).catch((err) => { xtermLoad = null; throw err; });
      return xtermLoad;
    }
    const cssVar = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    const wsUrl = (id) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/terminals/${id}/ws`;
    const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleTimeString() : "");

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        const style = document.createElement("style");
        style.textContent = `
          .pyhTerm { display: flex; flex-direction: column; height: 100%; min-height: 0; }
          .pyhTerm .termHead { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 8px 0 12px; font: 12px/18px var(--mono); color: var(--label-secondary); border-bottom: 0.5px solid var(--border-l2); }
          .pyhTerm .termHead .spacer { flex: 1; }
          .pyhTerm .termBody { flex: 1; min-height: 0; padding: 6px 4px 6px 10px; background: var(--layer-1); }
          .pyhTerm .termBody .xterm { height: 100%; }
          .pyhTerm .termNote { padding: 10px 14px; font-size: 12px; color: var(--label-tertiary); display: flex; gap: 10px; align-items: center; }
          .pyhTerm .plain { flex: 1; min-height: 0; display: flex; flex-direction: column; }
          .pyhTerm .plain pre { flex: 1; margin: 0; padding: 10px 12px; overflow: auto; font: 12px/18px var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--label-primary); }
          .pyhTerm .plain form { display: flex; gap: 6px; padding: 8px; border-top: 0.5px solid var(--border-l2); }
          .pyhJobs { display: flex; flex-direction: column; height: 100%; min-height: 0; }
          .pyhJobs .list { flex: 1; overflow: auto; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
          .pyhJobs .job { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 12px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); cursor: pointer; }
          .pyhJobs .job:hover { background: var(--layer-3, var(--layer-2)); }
          .pyhJobs .job .main { flex: 1; min-width: 0; }
          .pyhJobs .job .cmd { font: 12px/18px var(--mono); color: var(--label-primary); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 54px; overflow: hidden; }
          .pyhJobs .job .meta { font-size: 11px; color: var(--label-tertiary); margin-top: 4px; }
          .pyhJobs pre.log { flex: 1; margin: 0; padding: 10px 12px; overflow: auto; font: 12px/18px var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--label-primary); background: var(--layer-1); }
        `;
        document.head.appendChild(style);
        ctx.effect(() => style.remove());

        // ------------------------------------------------------------ terminal tab
        function terminalTab(el, props) {
          const st = props.tab.store; let alive = true; let ws = null; let term = null; let fit = null; let ro = null;
          const root = h("div", { class: "pyhTerm" });
          const title = h("span", { class: "label" }, props.tab.title || t.terminal);
          const head = h("div", { class: "termHead" }, title, h("span", { class: "spacer" }));
          const body = h("div", { class: "termBody" });
          root.append(head, body); el.replaceChildren(root);
          const note = (text, action) => { const n = h("div", { class: "termNote" }, text); if (action) n.append(action); root.append(n); return n; };

          async function ensureTerminal() {
            if (st.terminalId) {
              try { const list = (await json("/terminals")).terminals; const found = list.find((x) => x.id === st.terminalId); if (found && found.alive) return found; } catch { /* re-create */ }
              st.terminalId = null;
            }
            const info = await json("/terminals", { method: "POST", body: JSON.stringify({ workspace: props.workspace || null, cols: 100, rows: 30, title: null }) });
            st.terminalId = info.id; if (props.tab.setTitle) props.tab.setTitle(info.title || t.terminal); title.textContent = info.title || t.terminal;
            return info;
          }
          function connect(id, onData, onExit) {
            ws = new WebSocket(wsUrl(id)); ws.binaryType = "arraybuffer";
            ws.onmessage = (e) => { if (typeof e.data === "string") { try { const m = JSON.parse(e.data); if (m.type === "exit") onExit(m.code); } catch { onData(e.data); } } else onData(new Uint8Array(e.data)); };
            ws.onclose = () => { if (alive && ws && ws.readyState === WebSocket.CLOSED) { /* exit handled by control frame */ } };
            return ws;
          }
          const send = (data) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(typeof data === "string" ? new TextEncoder().encode(data) : data); };
          const resize = (cols, rows) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", cols, rows })); };

          async function mountXterm(info) {
            const dark = (ctx.theme() || "dark") !== "light";
            term = new window.Terminal({ cursorBlink: true, fontSize: 12, fontFamily: cssVar("--mono", "Menlo, monospace"), scrollback: 5000, theme: { background: cssVar("--layer-1", dark ? "#111" : "#fff"), foreground: cssVar("--label-primary", dark ? "#eee" : "#111"), cursor: cssVar("--label-primary", "#888"), selectionBackground: dark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.15)" } });
            fit = new window.FitAddon.FitAddon(); term.loadAddon(fit); term.open(body);
            const dec = new TextDecoder();
            connect(info.id, (d) => term.write(typeof d === "string" ? d : dec.decode(d, { stream: true })), (code) => { term.write(`\r\n[${t.exited(code)}]\r\n`); note(t.exited(code), h("button", { type: "button", class: "btn outline sm", onClick: () => { st.terminalId = null; remount(); } }, t.reconnect)); });
            term.onData((d) => send(d));
            const doFit = () => { try { fit.fit(); resize(term.cols, term.rows); } catch { /* not visible */ } };
            ro = new ResizeObserver(doFit); ro.observe(body);
            ws.onopen = () => { doFit(); term.focus(); };
          }
          function mountPlain(info) {
            const out = h("pre"); const input = h("input", { class: "input mono", placeholder: t.inputPlaceholder, autocomplete: "off" });
            const form = h("form", { onSubmit: (e) => { e.preventDefault(); send(input.value + "\n"); input.value = ""; } }, input, h("button", { type: "submit", class: "btn primary sm" }, t.send));
            const plain = h("div", { class: "plain" }, out, form); body.replaceChildren(plain); body.style.padding = "0";
            const dec = new TextDecoder();
            connect(info.id, (d) => { out.textContent += (typeof d === "string" ? d : dec.decode(d, { stream: true })).replace(/\x1b\[[0-9;?]*[A-Za-z]/g, ""); out.scrollTop = out.scrollHeight; }, (code) => note(t.exited(code), h("button", { type: "button", class: "btn outline sm", onClick: () => { st.terminalId = null; remount(); } }, t.reconnect)));
            note(t.fallback);
          }
          async function remount() {
            root.querySelectorAll(".termNote").forEach((n) => n.remove());
            if (ws) { try { ws.close(); } catch { /* closed */ } ws = null; }
            if (term) { term.dispose(); term = null; }
            body.replaceChildren(h("div", { class: "termNote" }, t.connecting));
            let info;
            try { info = await ensureTerminal(); } catch (err) { body.replaceChildren(); note(err.message); return; }
            if (!alive) return;
            body.replaceChildren();
            try { await loadXterm(); if (!alive) return; await mountXterm(info); } catch { if (alive) mountPlain(info); }
          }
          remount();
          return () => { alive = false; if (ro) ro.disconnect(); if (ws) { try { ws.close(); } catch { /* closed */ } } if (term) term.dispose(); };
        }

        // ------------------------------------------------------------ jobs tab
        function jobsTab(el, props) {
          let alive = true; let timer = null; let selected = null;
          const root = h("div", { class: "pyhJobs" }); el.replaceChildren(root);
          const tag = (j) => { const map = { running: ["info", t.running], exited: ["success", t.exitedTag], failed: ["danger", t.failed], killed: ["quiet", t.killed] }; const [tone, label] = map[j.status] || ["outline", j.status]; return h("span", { class: "tag", "data-tone": tone }, label); };
          async function renderList() {
            let data; try { data = await json("/jobs"); } catch (err) { root.replaceChildren(h("div", { class: "rbEmpty" }, err.message)); return; }
            if (!alive || selected) return;
            const refresh = h("button", { type: "button", class: "iconButton sm", title: t.refresh, onClick: renderList }); refresh.innerHTML = icon("refresh");
            const head = h("div", { class: "termHead" }, h("span", {}, t.jobs), h("span", { class: "spacer" }), refresh);
            const list = h("div", { class: "list" }, ...(data.jobs.length ? data.jobs.map((j) => h("div", { class: "job", onClick: () => { selected = j.id; renderJob(); } },
              h("span", { class: "main" }, h("div", { class: "cmd" }, j.command), h("div", { class: "meta" }, `${t.started} ${fmtTime(j.started_at)}${j.exit_code != null ? ` · exit ${j.exit_code}` : ""} · ${j.cwd}`)),
              tag(j))) : [h("div", { class: "rbEmpty" }, t.noJobs)]));
            root.replaceChildren(head, list);
          }
          async function renderJob() {
            let j; try { j = await json(`/jobs/${selected}?tail=500`); } catch (err) { toast(err.message); selected = null; return renderList(); }
            if (!alive || !selected) return;
            const back = h("button", { type: "button", class: "btn outline sm", onClick: () => { selected = null; clearTimeout(timer); renderList(); } }, t.back);
            const kill = h("button", { type: "button", class: "btn outline sm danger", disabled: j.status !== "running", onClick: async () => { try { await json(`/jobs/${j.id}`, { method: "DELETE" }); renderJob(); } catch (err) { toast(err.message); } } }, t.kill);
            const head = h("div", { class: "termHead" }, back, h("span", { class: "spacer" }), tag(j), kill);
            const log = h("pre", { class: "log" }, j.output || "");
            const prev = root.querySelector("pre.log"); const atEnd = !prev || prev.scrollTop + prev.clientHeight >= prev.scrollHeight - 8;
            root.replaceChildren(head, h("div", { class: "termNote" }, h("span", { class: "mono" }, j.command)), log);
            if (atEnd) log.scrollTop = log.scrollHeight; else log.scrollTop = prev.scrollTop;
            clearTimeout(timer); if (j.status === "running") timer = setTimeout(renderJob, 2000);
          }
          renderList();
          const offRun = ctx.on("run", (ev) => { if (!selected && ev.type === "tool_result" && /^(bash|pwsh|job_kill)$/.test(ev.name || "")) renderList(); });
          return () => { alive = false; clearTimeout(timer); offRun(); };
        }

        ctx.slots.register({ slot: "rightbar.tabs", key: "terminal", label: t.terminal, icon: "terminal", guide: { title: t.terminal, description: t.terminalDesc, order: 30 } }, terminalTab);
        ctx.slots.register({ slot: "rightbar.tabs", key: "jobs", label: t.jobs, icon: "zap", guide: { title: t.jobs, description: t.jobsDesc, order: 40 } }, jobsTab);
      },
    };
  },
});
