window.__PyhModules__.load({
  id: "memory",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: { entry: "记忆", intro: "agent 自己的职业履历：个人信息与能力、工作经历、项目与经验，带版本历史。", addLesson: "新增经验", selectWork: "选择工作经历", selectProject: "选择项目", content: "内容", resumeView: "简历", directory: "目录", view: "视图", sort: "排序", createdAt: "创建时间", newest: "最新在前", oldest: "最早在前", addWork: "新增工作经历", addProject: "新增项目", path: "路径", viewProjects: "查看项目", resume: "职业履历", personal: "个人信息与能力", work: "工作经历", project: "项目经历", lesson: "经验", name: "姓名", position: "职业定位", specialties: "擅长领域", abilities: "能力项", title: "名称", startDate: "开始日期", endDate: "截至日期", present: "至今", experienceTime: "经历时间", organization: "公司", jobTitle: "岗位", highlights: "主要事迹", role: "承担角色", workId: "所属工作经历", parentId: "所属项目", edit: "编辑", add: "新增", save: "保存", cancel: "取消", close: "关闭", lessons: "查看经验", history: "版本历史", refresh: "刷新", export: "导出", import: "导入", remove: "移除", restore: "恢复此版本", back: "返回", emptyWork: "暂无工作经历", emptyProject: "暂无项目经历", emptyLessons: "暂无经验", emptyHistory: "暂无版本", agentTools: "允许 Agent 使用", revision: "版本", human: "人工", agent: "Agent", before: "修改前", after: "修改后", none: "未填写", noWork: "独立项目", clear: "清空记忆", confirmClear: "确认清空", clearTitle: "清空全部记忆？", clearHint: "全部履历、经验和版本历史将被删除，无法恢复。Agent 使用开关保持不变。", removeTitle: "移除这条记录？", removeHint: "当前履历将移除此条目，版本历史仍然保留。有下级条目时，请先移除或更改关联。", restoreTitle: "恢复整个履历到此版本？", restoreHint: "将覆盖当前履历，并创建新版本。", importTitle: "导入并替换当前履历？", importHint: "文件中的履历将成为新版本，原有版本历史保留。", confirm: "确认", loading: "正在读取履历…", deleteSummary: "移除履历条目", restoreSummary: "恢复历史履历", importSummary: "导入履历", noDiff: "此版本没有字段变化", error: { date: "请选择有效日期。", dateRange: "截至日期不能早于开始日期。", conflict: "内容已更新。你的编辑仍保留，请关闭编辑、刷新后重新修改。", protected: "此操作仅支持在界面中执行。", busy: "记忆正在写入，请稍后重试。", invalid: "内容格式无效，请检查字段或导入文件。", content: "请填写必要内容：工作经历至少一项、项目名称或经验正文。", reference: "所属条目不存在，或仍有其他条目引用此条目。", missing: "此版本不存在。", disabled: "Agent 工具已关闭。", storage: "无法读取或保存记忆，请检查文件权限与宿主日志。", generic: "操作失败，请刷新后重试。" } },
      en: { entry: "Memory", intro: "The agent's own career record: profile and capabilities, work experience, projects and lessons, with version history.", addLesson: "Add lesson", selectWork: "Select work experience", selectProject: "Select a project", content: "Content", resumeView: "Resume", directory: "Directory", view: "View", sort: "Sort", createdAt: "Created", newest: "Newest first", oldest: "Oldest first", addWork: "Add work experience", addProject: "Add project", path: "Path", viewProjects: "View projects", resume: "Career record", personal: "Profile & capabilities", work: "Work experience", project: "Projects", lesson: "Lesson", name: "Name", position: "Professional focus", specialties: "Specialties", abilities: "Capabilities", title: "Title", startDate: "Start date", endDate: "End date", present: "Present", experienceTime: "Experience date", organization: "Company", jobTitle: "Position", highlights: "Highlights", role: "Role", workId: "Work experience", parentId: "Project", edit: "Edit", add: "Add", save: "Save", cancel: "Cancel", close: "Close", lessons: "View lessons", history: "Version history", refresh: "Refresh", export: "Export", import: "Import", remove: "Remove", restore: "Restore this version", back: "Back", emptyWork: "No work experience", emptyProject: "No projects", emptyLessons: "No lessons", emptyHistory: "No revisions", agentTools: "Allow agent access", revision: "Revision", human: "Human", agent: "Agent", before: "Before", after: "After", none: "Not provided", noWork: "Independent project", clear: "Clear memory", confirmClear: "Confirm clear", clearTitle: "Clear all memory?", clearHint: "Deletes all resume content, lessons and revision history. This cannot be undone. The agent access setting stays unchanged.", removeTitle: "Remove this record?", removeHint: "This entry will leave the current resume. Version history remains. Remove or reassign its children first.", restoreTitle: "Restore the entire resume to this revision?", restoreHint: "Replaces the current resume, creating a new revision.", importTitle: "Import and replace the current resume?", importHint: "The imported resume becomes a new revision. Existing history remains.", confirm: "Confirm", loading: "Loading career record…", deleteSummary: "Remove career entry", restoreSummary: "Restore career revision", importSummary: "Import career record", noDiff: "No field changed in this revision", error: { date: "Select a valid date.", dateRange: "End date cannot precede start date.", conflict: "The record changed. Your draft is preserved. Close the editor, refresh and edit again.", protected: "This operation is only available in the user interface.", busy: "Memory is being written. Try again shortly.", invalid: "Invalid content. Check the fields or import file.", content: "Required content is missing: any work field, a project title or the lesson text.", reference: "The parent entry is missing, or another entry still references this one.", missing: "Revision not found.", disabled: "Agent tools are disabled.", storage: "Cannot read or save memory. Check file permissions and host logs.", generic: "Operation failed. Refresh and try again." } },
    };
    const FIELDS = { profile: ["name", "position", "specialties", "abilities"], work: ["organization", "startDate", "endDate", "jobTitle", "highlights"], project: ["title", "startDate", "endDate", "role", "highlights", "workId"], lesson: ["parentId", "lesson"] };
    const TEXT_FIELDS = new Set(["name", "position", "title", "organization", "jobTitle", "role"]);
    const POLL_MS = 5000;

    async function call(path, opts) {
      const res = await fetch("/api/memory" + (path || ""), { headers: { "content-type": "application/json" }, ...(opts || {}) });
      if (!res.ok) {
        let code = "generic"; let detail = "";
        try { const d = (await res.json()).detail; if (d && typeof d === "object") { code = d.error || code; detail = d.detail || ""; } else if (typeof d === "string") detail = d; } catch { /* no body */ }
        if (res.status === 401 || res.status === 403) code = "forbidden";
        const err = new Error(code); err.code = code; err.detail = detail; err.status = res.status; throw err;
      }
      return res.json();
    }
    const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none"><symbol id="i-clock" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/></symbol><symbol id="i-arrow-left" viewBox="0 0 16 16"><path d="M13.25 8H2.75M7 3.75 2.75 8 7 12.25"/></symbol><symbol id="i-book" viewBox="0 0 16 16"><path d="M3.25 2.5h8.5a1 1 0 0 1 1 1v10.25H4.75a1.5 1.5 0 0 1-1.5-1.5V3.5a1 1 0 0 1 1-1z"/><path d="M3.25 11.5h9.5M5.75 5h4.5M5.75 7.5h3"/></symbol></svg>`;

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        if (!document.getElementById("i-book")) document.body.insertAdjacentHTML("beforeend", sprite);
        const style = document.createElement("style");
        style.textContent = `
          .memPage { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0 32px 24px; }
          .memPage .pageHead { flex: none; flex-wrap: wrap; }
          .memPage .pageHead .headTools { display: flex; flex-wrap: wrap; gap: 6px; }
          .memStatus { display: flex; align-items: center; gap: 12px; padding: 6px 0 10px; font-size: 12px; color: var(--label-tertiary); flex: none; }
          .memStatus .spacer { flex: 1; }
          .memStatus .switchRow { display: inline-flex; align-items: center; gap: 8px; color: var(--label-secondary); }
          .memBar { display: flex; align-items: center; gap: 10px; padding-bottom: 10px; flex: none; }
          .memBar .spacer { flex: 1; }
          .memSeg { display: inline-flex; padding: 3px; border-radius: 8px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .memSeg button { height: 26px; padding: 0 12px; border: none; border-radius: 6px; background: transparent; font-size: 12px; color: var(--label-secondary); }
          .memSeg button[aria-pressed="true"] { background: var(--layer-1); color: var(--label-primary); box-shadow: 0 1px 2px rgba(0,0,0,.08); }
          .memBody { flex: 1; min-height: 0; overflow: auto; border-radius: 12px; box-shadow: inset 0 0 0 0.5px var(--border-l2); background: var(--layer-1); }
          .memError { margin: 0 0 10px; padding: 8px 12px; border-radius: 8px; font-size: 12px; color: var(--error); background: color-mix(in srgb, var(--error) 8%, transparent); }
          .memSection { padding: 16px 20px; border-bottom: 0.5px solid var(--border-l2); }
          .memSection:last-child { border-bottom: none; }
          .memSection .secHead { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
          .memSection .secHead h2 { margin: 0; flex: 1; font-size: 15px; line-height: 22px; font-weight: 500; }
          .memDl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 24px; margin: 0; }
          .memDl > div { min-width: 0; }
          .memDl dt { font-size: 11px; color: var(--label-tertiary); margin-bottom: 2px; }
          .memDl dd { margin: 0; font-size: 13px; line-height: 20px; white-space: pre-wrap; overflow-wrap: anywhere; }
          .memCard { padding: 12px 14px; border-radius: 10px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); margin-bottom: 8px; }
          .memCard .time { font-size: 11px; color: var(--label-tertiary); }
          .memCard .row { display: flex; align-items: flex-start; gap: 8px; }
          .memCard .row h3 { margin: 2px 0 0; flex: 1; min-width: 0; font-size: 14px; line-height: 20px; font-weight: 500; }
          .memCard .muted { font-size: 12px; color: var(--label-secondary); margin-top: 2px; }
          .memCard .field { margin-top: 8px; font-size: 13px; line-height: 20px; white-space: pre-wrap; overflow-wrap: anywhere; }
          .memCard .link { margin-top: 8px; }
          .memLink { background: none; border: none; padding: 0; font-size: 12px; color: var(--info); cursor: pointer; }
          .memEmpty { padding: 24px 12px; text-align: center; font-size: 12px; color: var(--label-tertiary); }
          .memDir { display: flex; flex-direction: column; height: 100%; min-height: 0; }
          .memDir .top { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 0.5px solid var(--border-l2); font-size: 12px; color: var(--label-secondary); flex: none; }
          .memDir .top nav { display: flex; gap: 4px; flex-wrap: wrap; }
          .memCols { flex: 1; min-height: 0; display: flex; }
          .memCol { width: clamp(150px, 22%, 240px); flex: none; border-right: 0.5px solid var(--border-l2); display: flex; flex-direction: column; min-height: 0; }
          .memCol .colHead { display: flex; align-items: center; gap: 6px; padding: 8px 10px 4px; font-size: 11px; font-weight: 500; color: var(--label-tertiary); text-transform: uppercase; letter-spacing: .04em; }
          .memCol .colHead span { flex: 1; }
          .memCol .items { flex: 1; overflow: auto; padding: 0 6px 8px; }
          .memItem { display: flex; align-items: center; gap: 6px; width: 100%; text-align: left; padding: 6px 8px; border: none; border-radius: 6px; background: transparent; color: var(--label-primary); font-size: 12.5px; line-height: 18px; }
          .memItem:hover { background: var(--hover); }
          .memItem[data-selected] { background: var(--layer-3, var(--layer-2)); }
          .memItem[aria-current="true"] { background: color-mix(in srgb, var(--info) 12%, transparent); color: var(--info); }
          .memItem .main { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .memItem .sub { font-size: 11px; color: var(--label-tertiary); }
          .memDetail { flex: 1; min-width: 0; overflow: auto; padding: 16px 20px 24px; }
          .memDetail .kind { font-size: 11px; color: var(--label-tertiary); text-transform: uppercase; letter-spacing: .04em; }
          .memDetail h2 { margin: 4px 0 2px; font-size: 16px; line-height: 24px; font-weight: 500; }
          .memDetail .meta { font-size: 11px; color: var(--label-tertiary); margin-bottom: 10px; }
          .memDetail .actions { display: flex; gap: 6px; margin-bottom: 12px; }
          .memHist { display: grid; grid-template-columns: 240px minmax(0, 1fr); height: 100%; min-height: 0; }
          .memHist aside { border-right: 0.5px solid var(--border-l2); overflow: auto; padding: 8px; }
          .memHist aside h2 { margin: 4px 4px 8px; font-size: 12px; font-weight: 500; color: var(--label-tertiary); }
          .memHist .rev { display: block; width: 100%; text-align: left; padding: 8px 10px; border: none; border-radius: 8px; background: transparent; color: var(--label-primary); }
          .memHist .rev:hover { background: var(--hover); }
          .memHist .rev[aria-current="true"] { background: color-mix(in srgb, var(--info) 12%, transparent); }
          .memHist .rev .n { font-size: 11px; color: var(--label-tertiary); display: flex; gap: 6px; }
          .memHist .rev .s { font-size: 12.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .memHist .rev .tm { font-size: 11px; color: var(--label-tertiary); }
          .memHist .detail { overflow: auto; padding: 16px 20px 24px; }
          .memDiff { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
          .memDiff .item { padding: 10px 12px; border-radius: 8px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .memDiff .item .hd { font-size: 12px; font-weight: 500; margin-bottom: 6px; }
          .memDiff .cells { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
          .memDiff .cell { font-size: 12px; line-height: 18px; white-space: pre-wrap; overflow-wrap: anywhere; }
          .memDiff .cell b { display: block; font-weight: 500; color: var(--label-tertiary); font-size: 11px; margin-bottom: 2px; }
          .memDiff .cell[data-side="before"] { background: color-mix(in srgb, var(--error) 7%, transparent); padding: 6px 8px; border-radius: 6px; }
          .memDiff .cell[data-side="after"] { background: color-mix(in srgb, var(--success) 9%, transparent); padding: 6px 8px; border-radius: 6px; }
          .memForm { display: flex; flex-direction: column; gap: 12px; padding: 4px 4px 8px; }
          .memForm label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--label-secondary); }
          .memForm textarea { width: 100%; min-height: 84px; padding: 8px 12px; border: 0.5px solid var(--border-l4); border-radius: var(--r-md); background: var(--bg-layer-1); color: var(--label-primary); font: 13px/20px var(--font); resize: vertical; outline: none; }
          .memForm textarea:focus { border-color: var(--info); }
          .memForm .dates { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; align-items: end; }
          .memForm .check { flex-direction: row; align-items: center; gap: 6px; height: 34px; }
          .memForm .formError { font-size: 12px; color: var(--error); }
          @container (max-width: 760px) { .memCols { flex-wrap: wrap; } }
        `;
        document.head.appendChild(style);
        ctx.effect(() => style.remove());

        const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
        const period = (f) => { const a = f.startDate || ""; const b = f.endDate === "present" ? t.present : (f.endDate || ""); return a || b ? `${a || "—"} — ${b || "—"}` : ""; };
        const expDate = (e) => { if (e.kind === "lesson" || e.kind === "profile") return ""; const f = e.fields || {}; return f.startDate || (f.endDate === "present" ? "" : f.endDate || ""); };
        const sortEntries = (list, order) => { const dated = list.map((e, i) => [expDate(e), i, e]); const w = dated.filter((x) => x[0]); const wo = dated.filter((x) => !x[0]).map((x) => x[2]); w.sort((a, b) => (order === "newest" ? -1 : 1) * a[0].localeCompare(b[0]) || a[1] - b[1]); return [...w.map((x) => x[2]), ...wo]; };
        const entryName = (e) => { if (!e) return t.none; const f = e.fields || {}; if (e.kind === "profile") return t.personal; if (e.kind === "work") return [f.organization, f.jobTitle].filter(Boolean).join(" · ") || t.work; if (e.kind === "lesson") return (f.lesson || "").trim().slice(0, 80) || t.lesson; return f.title || t[e.kind]; };
        const errText = (err) => (err && err.code && t.error[err.code]) || (err && err.message && !t.error[err.message] ? t.error.generic : t.error.generic);

        function modal(inner, { wide } = {}) {
          const el = h("div", { class: "modal" }); el.innerHTML = `<div class="modalCard${wide ? "" : " narrow"}" role="dialog" aria-modal="true">${inner}</div>`;
          document.body.appendChild(el); return el;
        }

        // ------------------------------------------------------------ page
        function page(el) {
          let alive = true; let state = null; let error = null; let busy = false;
          let selected = "profile"; let view = "resume"; try { view = localStorage.getItem("pyh-memory-view") || "resume"; } catch { /* no storage */ }
          let history = false; let order = "newest"; let revision = null; const diffs = {};
          const root = h("div", { class: "memPage" }); el.replaceChildren(root);

          async function load(silent) {
            try { const s = await call(""); if (!alive) return; state = s; if (!silent) error = null; render(); }
            catch (err) { if (!silent) { error = errText(err); render(); } }
          }
          const timer = setInterval(() => load(true), POLL_MS);
          function setError(err) { error = errText(err); render(); }
          async function commit(body) {
            busy = true; render();
            try { state = await call("", { method: "POST", body: JSON.stringify({ baseRevision: state.revision, ...body }) }); error = null; return true; }
            catch (err) { error = errText(err); return false; }
            finally { busy = false; render(); }
          }

          // -------------------------------------------------------- header + bars
          function header() {
            const tools = h("div", { class: "headTools" },
              h("button", { type: "button", class: "btn outline sm", "aria-pressed": String(history), onClick: () => { history = !history; revision = null; render(); } }, ico(history ? "arrow-left" : "clock", "ico"), h("span", null, history ? t.back : t.history)),
              h("button", { type: "button", class: "btn outline sm", disabled: !state, onClick: exportJson }, t.export),
              h("button", { type: "button", class: "btn outline sm", onClick: () => fileInput.click() }, t.import),
              h("button", { type: "button", class: "iconButton", title: t.refresh, onClick: () => load(false) }, ico("refresh")),
              h("button", { type: "button", class: "btn outline sm", style: { color: "var(--error)" }, disabled: !state || busy, onClick: clearAll }, t.clear),
            );
            return h("div", { class: "pageHead" }, h("div", null, h("h1", { class: "pageTitle" }, t.entry), h("p", { class: "pageIntro" }, t.intro)), tools);
          }
          const fileInput = h("input", { type: "file", accept: "application/json,.json", hidden: true, onChange: importFile });
          function statusRow() {
            const last = state.history.length ? state.history[state.history.length - 1].time : null;
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(state.agentTools), disabled: busy, onClick: async () => { busy = true; render(); try { state = await call("", { method: "PATCH", body: JSON.stringify({ agentTools: !state.agentTools }) }); error = null; } catch (err) { error = errText(err); } busy = false; render(); } }, h("span", { class: "knob" }));
            return h("div", { class: "memStatus" }, h("span", null, `${t.revision} ${state.history.length} · ${fmtTime(last)}`), h("span", { class: "spacer" }), h("label", { class: "switchRow" }, h("span", null, t.agentTools), sw));
          }
          function viewBar() {
            const seg = h("div", { class: "memSeg", role: "group", "aria-label": t.view },
              h("button", { type: "button", "aria-pressed": String(view === "resume"), onClick: () => setView("resume") }, t.resumeView),
              h("button", { type: "button", "aria-pressed": String(view === "directory"), onClick: () => setView("directory") }, t.directory));
            const sel = h("select", { class: "select", "aria-label": t.sort, style: { width: "auto", height: "28px", padding: "0 28px 0 10px", fontSize: "12px" }, onChange: (e) => { order = e.target.value; render(); } }, h("option", { value: "newest", selected: order === "newest" }, t.newest), h("option", { value: "oldest", selected: order === "oldest" }, t.oldest));
            return h("div", { class: "memBar" }, seg, h("span", { class: "spacer" }), h("span", { style: { fontSize: "12px", color: "var(--label-tertiary)" } }, t.experienceTime), h("span", { class: "selectWrap" }, sel, ico("chev-down", "ico chev")));
          }
          function setView(v) { view = v; try { localStorage.setItem("pyh-memory-view", v); } catch { /* ignore */ } render(); }

          // -------------------------------------------------------- resume view
          function resumeView() {
            const entries = state.entries; const by = Object.fromEntries(entries.map((e) => [e.id, e]));
            const profile = by.profile || { id: "profile", kind: "profile", fields: {} };
            const countKids = (e) => entries.filter((x) => (e.kind === "work" ? x.kind === "project" && x.fields.workId === e.id : x.kind === "lesson" && x.fields.parentId === e.id)).length;
            const card = (e) => {
              const f = e.fields || {};
              return h("div", { class: "memCard" },
                h("div", { class: "time" }, period(f)),
                h("div", { class: "row" }, h("h3", null, e.kind === "work" ? (f.organization || t.none) : f.title), h("button", { type: "button", class: "btn outline sm", onClick: () => openEditor(e) }, t.edit), h("button", { type: "button", class: "btn outline sm", onClick: () => removeEntry(e) }, t.remove)),
                h("div", { class: "muted" }, e.kind === "work" ? f.jobTitle || "" : f.role || ""),
                f.highlights ? h("div", { class: "field" }, f.highlights) : null,
                h("div", { class: "link" }, h("button", { type: "button", class: "memLink", onClick: () => { view = "directory"; selected = e.id; history = false; render(); } }, `${e.kind === "work" ? t.viewProjects : t.lessons} ${countKids(e)} →`)));
            };
            const section = (kind, label, empty) => {
              const list = sortEntries(entries.filter((e) => e.kind === kind), order);
              return h("section", { class: "memSection" }, h("div", { class: "secHead" }, h("h2", null, label), h("button", { type: "button", class: "btn outline sm", onClick: () => addEntry(kind) }, ico("plus", "ico"), h("span", null, t.add))), list.length ? list.map(card) : h("div", { class: "memEmpty" }, empty));
            };
            return h("div", { class: "memBody" },
              h("section", { class: "memSection" }, h("div", { class: "secHead" }, h("h2", null, t.personal), h("button", { type: "button", class: "btn outline sm", onClick: () => openEditor(profile) }, t.edit)),
                h("dl", { class: "memDl" }, FIELDS.profile.map((k) => h("div", null, h("dt", null, t[k]), h("dd", null, profile.fields[k] || "—"))))),
              section("work", t.work, t.emptyWork), section("project", t.project, t.emptyProject));
          }

          // -------------------------------------------------------- directory view
          function directoryView() {
            const entries = state.entries; const by = Object.fromEntries(entries.map((e) => [e.id, e]));
            const cur = selected === "@independent" ? null : by[selected] || by.profile;
            if (selected !== "@independent" && !by[selected]) selected = "profile";
            let work = null, project = null, lesson = null, independent = selected === "@independent";
            if (cur) {
              if (cur.kind === "lesson") { lesson = cur; project = by[cur.fields.parentId]; }
              else if (cur.kind === "project") project = cur;
              else if (cur.kind === "work") work = cur;
              if (project) { work = by[project.fields.workId] || null; if (!work) independent = true; }
            }
            const works = entries.filter((e) => e.kind === "work");
            const indep = entries.filter((e) => e.kind === "project" && !e.fields.workId);
            const projects = independent ? indep : work ? entries.filter((e) => e.kind === "project" && e.fields.workId === work.id) : [];
            const lessons = project ? entries.filter((e) => e.kind === "lesson" && e.fields.parentId === project.id) : [];
            const crumbs = [h("button", { type: "button", class: "memLink", onClick: () => { selected = "profile"; render(); } }, t.directory)];
            if (independent) crumbs.push(h("span", null, " / " + t.noWork));
            for (const e of [work, project, lesson].filter(Boolean)) crumbs.push(h("span", null, " / "), h("button", { type: "button", class: "memLink", onClick: () => { selected = e.id; render(); } }, entryName(e)));
            const item = (e, current, onPath) => h("button", { type: "button", class: "memItem", "aria-current": current ? "true" : null, "data-selected": onPath && !current ? "" : null, onClick: () => { selected = e.id; render(); } }, h("span", { class: "main" }, entryName(e), e.kind !== "lesson" && period(e.fields) ? h("span", { class: "sub" }, " " + period(e.fields)) : null), h("span", null, e.kind === "lesson" ? "·" : "›"));
            const col = (label, addLabel, canAdd, onAdd, items, empty) => h("div", { class: "memCol" }, h("div", { class: "colHead" }, h("span", null, label), h("button", { type: "button", class: "iconButton sm", title: addLabel, disabled: !canAdd, onClick: onAdd }, ico("plus"))), h("div", { class: "items" }, items.length ? items : h("div", { class: "memEmpty" }, empty)));
            const workItems = [...sortEntries(works, order).map((e) => item(e, cur && cur.id === e.id, work && work.id === e.id)), h("button", { type: "button", class: "memItem", "aria-current": independent && !project ? "true" : null, "data-selected": independent && project ? "" : null, onClick: () => { selected = "@independent"; render(); } }, h("span", { class: "main" }, t.noWork, h("span", { class: "sub" }, ` ${indep.length}`)), h("span", null, "›"))];
            const projItems = sortEntries(projects, order).map((e) => item(e, cur && cur.id === e.id, project && project.id === e.id));
            const lessonItems = sortEntries(lessons, order).map((e) => item(e, cur && cur.id === e.id, false));
            let detail;
            if (independent && !project) detail = h("div", { class: "memDetail" }, h("h2", null, t.noWork), h("div", { class: "actions" }, h("button", { type: "button", class: "btn outline sm", onClick: () => addEntry("project") }, ico("plus", "ico"), h("span", null, t.add))), h("p", { class: "memEmpty" }, t.selectProject));
            else {
              const e = cur; const f = e.fields || {};
              detail = h("div", { class: "memDetail", "aria-label": t.content }, h("div", { class: "kind" }, e.kind === "profile" ? t.personal : t[e.kind]), h("h2", null, entryName(e)), h("div", { class: "meta" }, e.createdAt ? `${t.createdAt} · ${fmtTime(e.createdAt)}` : ""),
                h("div", { class: "actions" }, h("button", { type: "button", class: "btn outline sm", onClick: () => openEditor(e) }, t.edit), e.kind !== "profile" ? h("button", { type: "button", class: "btn outline sm", onClick: () => removeEntry(e) }, t.remove) : null),
                h("dl", { class: "memDl" }, FIELDS[e.kind].filter((k) => k !== "parentId" && k !== "workId").map((k) => h("div", null, h("dt", null, t[k]), h("dd", null, k === "endDate" && f[k] === "present" ? t.present : f[k] || "—")))));
            }
            return h("div", { class: "memBody memDir" },
              h("div", { class: "top" }, h("button", { type: "button", class: "btn outline sm", "aria-pressed": String(selected === "profile"), onClick: () => { selected = "profile"; render(); } }, t.personal), h("nav", { "aria-label": t.path }, crumbs)),
              h("div", { class: "memCols" },
                col(t.work, t.addWork, true, () => addEntry("work"), workItems, t.emptyWork),
                col(t.project, t.addProject, !!(work || independent), () => addEntry("project", work ? work.id : null), projItems, work || independent ? t.emptyProject : t.selectWork),
                col(t.lesson, t.addLesson, !!project, () => addEntry("lesson", project ? project.id : null), lessonItems, project ? t.emptyLessons : t.selectProject),
                detail));
          }

          // -------------------------------------------------------- history view
          function historyView() {
            const revs = [...state.history].reverse();
            if (revision === null && revs.length) revision = revs[0].revision;
            const aside = h("aside", null, h("h2", null, t.history), revs.length ? revs.map((r, i) => h("button", { type: "button", class: "rev", "aria-current": r.revision === revision ? "true" : null, onClick: () => { revision = r.revision; render(); } }, h("div", { class: "n" }, `v${revs.length - i}`, h("span", null, t[r.actor] || r.actor)), h("div", { class: "s" }, r.summary), h("div", { class: "tm" }, fmtTime(r.time)))) : h("div", { class: "memEmpty" }, t.emptyHistory));
            const detail = h("div", { class: "detail" });
            const r = state.history.find((x) => x.revision === revision);
            if (r) {
              const isCurrent = state.history.length && state.history[state.history.length - 1].revision === r.revision;
              detail.append(h("h2", { style: { margin: "0 0 2px", fontSize: "16px", fontWeight: 500 } }, r.summary), h("div", { class: "meta", style: { fontSize: "11px", color: "var(--label-tertiary)" } }, `${t[r.actor] || r.actor} · ${r.source}`),
                h("div", { class: "actions", style: { margin: "10px 0" } }, h("button", { type: "button", class: "btn outline sm", disabled: busy || isCurrent, onClick: () => restoreRevision(r) }, t.restore)));
              const box = h("div", { class: "memDiff" }, h("div", { class: "memEmpty" }, t.loading)); detail.append(box);
              const draw = (d) => { box.replaceChildren(...diffItems(d)); };
              if (diffs[r.revision]) draw(diffs[r.revision]);
              else call(`?diff=${r.revision}`).then((d) => { diffs[r.revision] = d; if (alive && revision === r.revision) draw(d); }).catch((err) => { box.replaceChildren(h("div", { class: "memError" }, errText(err))); });
            }
            return h("div", { class: "memBody memHist" }, aside, detail);
          }
          function diffItems(d) {
            const bBy = Object.fromEntries(d.before.entries.map((e) => [e.id, e])); const aBy = Object.fromEntries(d.after.entries.map((e) => [e.id, e]));
            const ids = [...new Set([...Object.keys(bBy), ...Object.keys(aBy)])]; const items = [];
            const show = (snap, key, v) => { if (!v) return "—"; if (key === "endDate" && v === "present") return t.present; if (key === "parentId" || key === "workId") return entryName(snap.find((e) => e.id === v)); return v; };
            for (const id of ids) {
              const b = bBy[id], a = aBy[id]; const keys = [...new Set([...Object.keys((b && b.fields) || {}), ...Object.keys((a && a.fields) || {})])];
              for (const k of keys) { const bv = b ? b.fields[k] || "" : ""; const av = a ? a.fields[k] || "" : ""; if (bv === av) continue; items.push(h("div", { class: "item" }, h("div", { class: "hd" }, `${entryName(a || b)} · ${t[k] || k}`), h("div", { class: "cells" }, h("div", { class: "cell", "data-side": "before" }, h("b", null, t.before), show(d.before.entries, k, bv)), h("div", { class: "cell", "data-side": "after" }, h("b", null, t.after), show(d.after.entries, k, av))))); }
            }
            return items.length ? items : [h("div", { class: "memEmpty" }, t.noDiff)];
          }

          // -------------------------------------------------------- editor + confirms
          function addEntry(kind, parentId) {
            const entry = { id: crypto.randomUUID(), kind, fields: parentId ? (kind === "project" ? { workId: parentId } : { parentId }) : {} };
            openEditor(entry);
          }
          function openEditor(entry) {
            const base = state.revision; const draft = { ...entry, fields: { ...entry.fields } };
            const kindLabel = entry.kind === "profile" ? t.personal : t[entry.kind];
            const el = modal(`<div class="modalHead">${esc(t.edit)} · ${esc(kindLabel)}</div><div class="modalBody"><div class="memForm" data-form></div></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes>${esc(t.save)}</button></div>`, { wide: true });
            const form = el.querySelector("[data-form]"); const err = h("div", { class: "formError" }); let first = null;
            const works = state.entries.filter((e) => e.kind === "work"); const projects = state.entries.filter((e) => e.kind === "project");
            for (const key of FIELDS[entry.kind]) {
              if (key === "endDate") continue;
              let ctl;
              if (key === "startDate") {
                const start = h("input", { class: "input", type: "date", value: draft.fields.startDate || "" }); const end = h("input", { class: "input", type: "date", value: draft.fields.endDate === "present" ? "" : draft.fields.endDate || "", disabled: draft.fields.endDate === "present" });
                const present = h("input", { type: "checkbox", checked: draft.fields.endDate === "present" });
                const syncDates = () => { draft.fields.startDate = start.value; draft.fields.endDate = present.checked ? "present" : end.value; end.disabled = present.checked; start.max = present.checked ? "" : end.value; end.min = start.value; };
                start.oninput = syncDates; end.oninput = syncDates; present.onchange = () => { if (present.checked) end.value = ""; syncDates(); };
                syncDates();
                ctl = h("div", { class: "dates" }, h("label", null, t.startDate, start), h("label", null, t.endDate, end), h("label", { class: "check" }, present, t.present));
                form.append(ctl); if (!first) first = start; continue;
              }
              if (key === "workId" || key === "parentId") {
                const opts = key === "workId" ? [["", t.noWork], ...works.map((w) => [w.id, entryName(w)])] : [["", t.none], ...projects.map((p) => [p.id, entryName(p)])];
                ctl = h("select", { class: "select", onChange: (e) => { draft.fields[key] = e.target.value; } }, opts.map(([v, l]) => h("option", { value: v, selected: (draft.fields[key] || "") === v }, l)));
              } else if (TEXT_FIELDS.has(key)) ctl = h("input", { class: "input", maxlength: 12000, value: draft.fields[key] || "", onInput: (e) => { draft.fields[key] = e.target.value; } });
              else ctl = h("textarea", { maxlength: key === "highlights" ? 50000 : 12000, rows: 4, onInput: (e) => { draft.fields[key] = e.target.value; } }, draft.fields[key] || "");
              form.append(h("label", null, t[key], ctl)); if (!first) first = ctl;
            }
            form.append(err);
            const close = () => { el.remove(); document.removeEventListener("keydown", onKey, true); };
            const onKey = (e) => { if (e.key === "Escape" && !busy) close(); };
            document.addEventListener("keydown", onKey, true);
            el.querySelector("[data-no]").onclick = close;
            el.querySelector("[data-yes]").onclick = async () => {
              if (state.revision !== base) { err.textContent = t.error.conflict; return; }
              const yes = el.querySelector("[data-yes]"); yes.disabled = true;
              try { state = await call("", { method: "POST", body: JSON.stringify({ baseRevision: base, summary: `${t.edit} · ${entryName(draft)}`, changes: [{ id: draft.id, kind: draft.kind, fields: draft.fields }] }) }); error = null; close(); if (view === "directory" && draft.kind !== "profile") selected = draft.id; render(); }
              catch (e2) { err.textContent = errText(e2); yes.disabled = false; }
            };
            if (first) first.focus();
          }
          function confirmBox(title, hint, label, danger, onYes) {
            const el = modal(`<div class="modalHead">${esc(title)}</div><div class="modalBody"><p>${esc(hint)}</p><div class="memError" data-err hidden></div></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes ${danger ? 'style="background:var(--error)"' : ""}>${esc(label)}</button></div>`);
            const close = () => { el.remove(); document.removeEventListener("keydown", onKey, true); };
            const onKey = (e) => { if (e.key === "Escape") close(); };
            document.addEventListener("keydown", onKey, true);
            el.querySelector("[data-no]").onclick = close; el.querySelector("[data-no]").focus();
            el.querySelector("[data-yes]").onclick = async () => { const yes = el.querySelector("[data-yes]"); yes.disabled = true; try { await onYes(); close(); } catch (e2) { const box = el.querySelector("[data-err]"); box.hidden = false; box.textContent = errText(e2); yes.disabled = false; } };
          }
          const post = async (body) => { state = await call("", { method: "POST", body: JSON.stringify({ baseRevision: state.revision, ...body }) }); error = null; render(); };
          function removeEntry(e) { confirmBox(t.removeTitle, t.removeHint, t.confirm, false, async () => { await post({ summary: t.deleteSummary, changes: [{ id: e.id, kind: e.kind, remove: true }] }); if (selected === e.id) selected = e.fields.parentId || e.fields.workId || "profile"; render(); }); }
          function restoreRevision(r) { confirmBox(t.restoreTitle, t.restoreHint, t.confirm, false, async () => { await post({ summary: t.restoreSummary, restore: r.revision }); revision = null; render(); }); }
          function clearAll() { confirmBox(t.clearTitle, t.clearHint, t.confirmClear, true, async () => { state = await call("", { method: "DELETE", body: JSON.stringify({ clear: true, baseRevision: state.revision }) }); error = null; selected = "profile"; history = false; revision = null; for (const k of Object.keys(diffs)) delete diffs[k]; render(); }); }
          function exportJson() { const blob = new Blob([JSON.stringify({ schemaVersion: 1, exportedAt: new Date().toISOString(), entries: state.entries }, null, 2)], { type: "application/json" }); const a = h("a", { href: URL.createObjectURL(blob), download: "career-memory.json" }); document.body.appendChild(a); a.click(); a.remove(); }
          async function importFile(e) {
            const file = e.target.files && e.target.files[0]; e.target.value = ""; if (!file) return;
            let data = null;
            try { if (file.size > 2 * 1024 * 1024) throw new Error("size"); data = JSON.parse(await file.text()); if (!data || data.schemaVersion !== 1 || !Array.isArray(data.entries)) throw new Error("shape"); }
            catch { error = t.error.invalid; render(); return; }
            confirmBox(t.importTitle, t.importHint, t.confirm, false, async () => { await post({ summary: t.importSummary, imported: { schemaVersion: 1, entries: data.entries } }); });
          }

          // -------------------------------------------------------- render
          function render() {
            if (!alive) return;
            const parts = [header(), fileInput];
            if (error) parts.push(h("div", { class: "memError", role: "alert" }, error));
            if (!state) parts.push(h("div", { class: "memEmpty" }, t.loading));
            else { parts.push(statusRow()); if (!history) parts.push(viewBar()); parts.push(history ? historyView() : view === "directory" ? directoryView() : resumeView()); }
            root.replaceChildren(...parts);
          }
          render(); load(false);
          return () => { alive = false; clearInterval(timer); };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "memory", label: t.entry, icon: "book", description: t.intro, order: 55 });
        ctx.slots.register({ slot: "main", key: "memory", label: t.entry }, page);
      },
    };
  },
});
