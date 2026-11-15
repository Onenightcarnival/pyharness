window.__PyhModules__.load({
  id: "s3",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: { entry: "S3", intro: "S3 兼容对象存储浏览器：MinIO / OSS / COS / R2 / AWS。配置桶、浏览与上传下载对象、分享链接。", agentTools: "允许 Agent 使用", buckets: "桶", add: "新增", empty: "暂无桶配置", edit: "编辑", del: "删除", test: "测试连接", deleteConfirm: (n) => `确定删除桶配置「${n}」？只移除本机保存的连接信息，不会动桶里的数据。`, testing: "连接测试中…", testOk: (ms) => `连接成功（${ms} ms）`, testFail: (e) => `连接失败：${e}`, formCreate: "新增桶", formEdit: (n) => `编辑桶「${n}」`, name: "显示名称", namePlaceholder: "默认用 bucket 名", optional: "可选", bucket: "Bucket 名称", endpoint: "Endpoint", region: "Region", accessKeyId: "Access Key ID", secretAccessKey: "Secret Access Key", pathStyle: "路径风格寻址（Path-style）", prefix: "限定前缀", cancel: "取消", save: "保存", saving: "保存中…", selectProfile: "在左侧选择一个桶开始浏览。", root: "根目录", refresh: "刷新", upload: "上传文件", newFolder: "新建文件夹", newFolderPrompt: "文件夹名称", filter: "过滤当前页…", loadMore: "加载更多", loading: "加载中…", noObjects: "这个前缀下没有对象。", colName: "名称", colSize: "大小", colModified: "修改时间", colActions: "操作", download: "下载", link: "分享链接", rename: "重命名", selected: (n) => `已选 ${n} 项`, deleteSelected: "删除所选", clearSelection: "取消选择", deleteTitle: "确认删除", deleteBody: (n) => `将永久删除以下 ${n} 项，文件夹会连同其中全部对象一起删除，无法撤销：`, deleteOk: "删除", deleted: (n) => `已删除 ${n} 个对象`, deleteErrors: (n) => `${n} 个对象删除失败`, renamePrompt: "新的对象名（同一目录内）", linkTitle: "分享链接", linkExpires: "有效期", linkCopy: "复制链接", linkCopied: "已复制", exp1h: "1 小时", exp1d: "1 天", exp7d: "7 天", uploading: (n, p) => `上传 ${n}（${p}%）`, uploadDone: (n) => `上传完成：${n}`, uploadFail: (n, e) => `上传失败：${n} — ${e}`, folderCreated: (n) => `已创建文件夹 ${n}`, previewTruncated: "（只显示前 512 KB，完整内容请下载）", previewBinary: "这个对象不是文本，无法预览；请下载查看。", close: "关闭", toolsOn: "agent 工具已开启", toolsOff: "agent 工具已关闭" },
      en: { entry: "S3", intro: "S3-compatible object storage browser: MinIO / OSS / COS / R2 / AWS. Configure buckets, browse, upload and download objects, share links.", agentTools: "Allow agent access", buckets: "Buckets", add: "Add", empty: "No buckets configured", edit: "Edit", del: "Delete", test: "Test connection", deleteConfirm: (n) => `Remove the bucket profile "${n}"? Only the locally saved connection is removed; the bucket data is untouched.`, testing: "Testing…", testOk: (ms) => `Connected (${ms} ms)`, testFail: (e) => `Connection failed: ${e}`, formCreate: "Add bucket", formEdit: (n) => `Edit bucket "${n}"`, name: "Display name", namePlaceholder: "defaults to the bucket name", optional: "Optional", bucket: "Bucket name", endpoint: "Endpoint", region: "Region", accessKeyId: "Access Key ID", secretAccessKey: "Secret Access Key", pathStyle: "Path-style addressing", prefix: "Scope prefix", cancel: "Cancel", save: "Save", saving: "Saving…", selectProfile: "Pick a bucket on the left to start browsing.", root: "Root", refresh: "Refresh", upload: "Upload files", newFolder: "New folder", newFolderPrompt: "Folder name", filter: "Filter this page…", loadMore: "Load more", loading: "Loading…", noObjects: "Nothing under this prefix.", colName: "Name", colSize: "Size", colModified: "Modified", colActions: "Actions", download: "Download", link: "Share link", rename: "Rename", selected: (n) => `${n} selected`, deleteSelected: "Delete selected", clearSelection: "Clear selection", deleteTitle: "Confirm deletion", deleteBody: (n) => `Permanently delete these ${n} item(s)? Folders are deleted with everything inside. This cannot be undone:`, deleteOk: "Delete", deleted: (n) => `Deleted ${n} object(s)`, deleteErrors: (n) => `${n} object(s) failed to delete`, renamePrompt: "New object name (same folder)", linkTitle: "Share link", linkExpires: "Valid for", linkCopy: "Copy link", linkCopied: "Copied", exp1h: "1 hour", exp1d: "1 day", exp7d: "7 days", uploading: (n, p) => `Uploading ${n} (${p}%)`, uploadDone: (n) => `Uploaded ${n}`, uploadFail: (n, e) => `Upload failed: ${n} — ${e}`, folderCreated: (n) => `Created folder ${n}`, previewTruncated: "(showing the first 512 KB; download for the full content)", previewBinary: "This object is not text and cannot be previewed; download it instead.", close: "Close", toolsOn: "Agent tools are on", toolsOff: "Agent tools are off" },
    };
    const IMAGE_RE = /\.(png|jpe?g|gif|webp|bmp|avif)$/i;
    async function call(path, opts) {
      const res = await fetch("/api/s3" + path, { headers: { "content-type": "application/json" }, ...(opts || {}) });
      if (!res.ok) { let detail = `HTTP ${res.status}`; try { const d = (await res.json()).detail; if (typeof d === "string") detail = d; } catch { /* no body */ } throw new Error(detail); }
      return res.json();
    }
    const humanSize = (n) => { let v = n; const units = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; } return i === 0 ? `${v} B` : `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`; };
    const fmtDate = (iso) => { if (!iso) return "-"; const d = new Date(iso); const p = (x) => String(x).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
    const baseName = (key) => { const k = key.replace(/\/+$/, ""); return k.slice(k.lastIndexOf("/") + 1); };
    const objectUrl = (id, key, inline) => `/api/s3/object?id=${encodeURIComponent(id)}&key=${encodeURIComponent(key)}${inline ? "&inline=1" : ""}`;
    const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none"><symbol id="i-archive" viewBox="0 0 16 16"><rect x="2.25" y="2.75" width="11.5" height="3" rx="1"/><path d="M3.25 5.75v6.5a1 1 0 0 0 1 1h7.5a1 1 0 0 0 1-1v-6.5M6.5 8.75h3"/></symbol><symbol id="i-upload" viewBox="0 0 16 16"><path d="M8 11V2.75M4.75 6 8 2.75 11.25 6M2.75 10.5v2a1 1 0 0 0 1 1h8.5a1 1 0 0 0 1-1v-2"/></symbol></svg>`;

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        if (!document.getElementById("i-archive")) document.body.insertAdjacentHTML("beforeend", sprite);
        const style = document.createElement("style");
        style.textContent = `
          .s3Page { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0 24px 16px; }
          .s3Page .pageHead { flex: none; flex-wrap: wrap; padding-bottom: 10px; }
          .s3Page .headTools { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--label-secondary); }
          .s3Banner { margin: 0 0 10px; padding: 7px 12px; border-radius: 8px; font-size: 12px; display: flex; align-items: center; gap: 8px; flex: none; }
          .s3Banner span.text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
          .s3Banner progress { width: 120px; height: 6px; }
          .s3Banner[data-kind="ok"] { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }
          .s3Banner[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .s3Banner[data-kind="info"] { background: color-mix(in srgb, var(--info) 10%, transparent); color: var(--info); }
          .s3Body { flex: 1; min-height: 0; display: flex; gap: 12px; }
          .s3Side { width: 220px; flex: none; display: flex; flex-direction: column; gap: 6px; min-height: 0; border-right: 0.5px solid var(--border-l2); padding-right: 12px; }
          .s3Side .blockHead { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: var(--label-secondary); padding: 2px 0; }
          .s3Side .blockHead span { flex: 1; }
          .s3Side .list { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
          .s3Prof { display: block; width: 100%; text-align: left; padding: 7px 8px; border: none; border-radius: 8px; background: transparent; color: var(--label-primary); }
          .s3Prof:hover { background: var(--hover); }
          .s3Prof[data-active] { background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .s3Prof .l1 { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .s3Prof .l2, .s3Prof .l3 { font-size: 11px; color: var(--label-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .s3Link { background: none; border: none; padding: 0; font-size: 12px; color: var(--info); cursor: pointer; }
          .s3Link[data-danger] { color: var(--error); }
          .s3Link:disabled { opacity: .5; cursor: default; }
          .s3Actions { display: flex; gap: 10px; padding: 0 8px; }
          .s3Browser { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
          .s3Browser[data-dragover] { outline: 2px dashed var(--info); outline-offset: -2px; border-radius: 12px; }
          .s3Toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex: none; }
          .s3Toolbar nav { display: flex; align-items: center; gap: 4px; font-size: 12px; flex-wrap: wrap; min-width: 0; }
          .s3Toolbar nav .crumb { background: none; border: none; padding: 0; color: var(--info); cursor: pointer; font-size: 12px; }
          .s3Toolbar nav .crumb[data-current] { color: var(--label-primary); cursor: default; font-weight: 500; }
          .s3Toolbar nav .sep { color: var(--label-tertiary); }
          .s3Toolbar .spacer { flex: 1; }
          .s3Toolbar .input { width: 180px; height: 28px; font-size: 12px; }
          .s3TableWrap { flex: 1; min-height: 0; overflow: auto; border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); background: var(--layer-1); }
          .s3Table { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12.5px; }
          .s3Table th { position: sticky; top: 0; z-index: 1; text-align: left; padding: 8px 10px; background: var(--layer-2); font-weight: 500; color: var(--label-secondary); border-bottom: 0.5px solid var(--border-l2); white-space: nowrap; }
          .s3Table th.right, .s3Table td.right { text-align: right; }
          .s3Table td { padding: 6px 10px; border-bottom: 0.5px solid var(--border-l2); white-space: nowrap; vertical-align: middle; }
          .s3Table tr:hover td { background: var(--hover); }
          .s3Table tr[data-selected] td { background: color-mix(in srgb, var(--info) 8%, transparent); }
          .s3Table td.name { max-width: 0; width: 60%; overflow: hidden; text-overflow: ellipsis; }
          .s3Table td.name button { background: none; border: none; padding: 0; color: var(--label-primary); font: inherit; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
          .s3Table td.name button span { overflow: hidden; text-overflow: ellipsis; }
          .s3Table td.name .ico { width: 14px; height: 14px; flex: none; color: var(--label-tertiary); }
          .s3Table td.sel { width: 24px; }
          .s3Table td.acts { text-align: right; }
          .s3Table td.acts .s3Link { margin-left: 10px; }
          .s3Foot { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--label-tertiary); flex: none; }
          .s3Foot .spacer { flex: 1; }
          .s3Empty { padding: 32px 12px; text-align: center; font-size: 12.5px; color: var(--label-tertiary); }
          .s3Form { display: flex; flex-direction: column; gap: 12px; padding: 4px 4px 8px; }
          .s3Form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--label-secondary); }
          .s3Form .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
          .s3Form .check { flex-direction: row; align-items: center; gap: 6px; }
          .s3Form .divider { font-size: 11px; color: var(--label-tertiary); text-transform: uppercase; letter-spacing: .04em; padding-top: 4px; }
          .s3Form .err { font-size: 12px; color: var(--error); }
          .s3Pre { margin: 4px; padding: 10px 12px; border-radius: 8px; background: var(--layer-1); font: 12px/18px var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 50vh; overflow: auto; }
          .s3Meta { font-size: 12px; color: var(--label-tertiary); margin: -6px 24px 8px; }
          .s3Preview img { max-width: 100%; max-height: 60vh; display: block; margin: 4px auto; border-radius: 8px; }
          .s3LinkRow { display: flex; gap: 8px; margin: 4px; }
          .s3LinkRow .input { flex: 1; margin: 0; }
          ul.s3Keys { margin: 4px; padding: 10px 12px 10px 28px; border-radius: 8px; background: var(--layer-1); font: 12px/18px var(--mono); max-height: 200px; overflow: auto; }
          @container (max-width: 760px) { .s3Body { flex-direction: column; } .s3Side { width: auto; border-right: none; padding-right: 0; max-height: 35%; } }
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
        const foot = (okLabel, danger) => `<div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button>${okLabel ? `<button type="button" class="btn primary" data-yes ${danger ? 'style="background:var(--error)"' : ""}>${esc(okLabel)}</button>` : ""}</div>`;

        // ------------------------------------------------------------ page
        function page(el) {
          let alive = true;
          const st = { profiles: null, settings: { agentTools: false }, active: null, banner: null, testing: false };
          const br = { prefix: "", folders: [], objects: [], nextToken: null, loading: false, error: null, filter: "", selected: new Set(), gen: 0 };
          const root = h("div", { class: "s3Page" }); el.replaceChildren(root);
          const setBanner = (kind, text, progress) => { st.banner = kind ? { kind, text, progress } : null; renderBanner(); };
          const fail = (err) => setBanner("error", err.message || String(err));
          const profile = () => (st.profiles || []).find((p) => p.id === st.active) || null;

          async function load() {
            try { const [p, s] = await Promise.all([call("/profiles"), call("/settings")]); if (!alive) return; st.profiles = p.profiles; st.settings = s.settings; const keep = st.profiles.find((x) => x.id === st.active); if (!keep) selectProfile(st.profiles[0] ? st.profiles[0].id : null); else render(); }
            catch (err) { fail(err); render(); }
          }
          function selectProfile(id) { st.active = id; Object.assign(br, { prefix: "", folders: [], objects: [], nextToken: null, filter: "", error: null }); br.selected.clear(); render(); if (id) list(false); }
          function setPrefix(prefix) { br.prefix = prefix; br.selected.clear(); br.filter = ""; list(false); }
          async function list(append) {
            const gen = ++br.gen; br.loading = true; br.error = null; if (!append) { br.folders = []; br.objects = []; br.nextToken = null; } render();
            try {
              const d = await call(`/list?id=${encodeURIComponent(st.active)}&prefix=${encodeURIComponent(br.prefix)}${append && br.nextToken ? `&token=${encodeURIComponent(br.nextToken)}` : ""}`);
              if (!alive || gen !== br.gen) return;
              br.folders = append ? br.folders.concat(d.page.folders) : d.page.folders; br.objects = append ? br.objects.concat(d.page.objects) : d.page.objects; br.nextToken = d.page.nextToken || null;
            } catch (err) { if (gen === br.gen) br.error = err.message; }
            if (gen === br.gen) { br.loading = false; render(); }
          }

          // -------------------------------------------------------- header, banner
          function header() {
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(!!st.settings.agentTools), disabled: !st.profiles, onClick: async () => {
              const next = !st.settings.agentTools; st.settings.agentTools = next; render();
              try { const d = await call("/settings", { method: "POST", body: JSON.stringify({ agentTools: next }) }); st.settings = d.settings; setBanner("ok", next ? t.toolsOn : t.toolsOff); }
              catch (err) { st.settings.agentTools = !next; fail(err); } render();
            } }, h("span", { class: "knob" }));
            return h("div", { class: "pageHead" }, h("div", null, h("h1", { class: "pageTitle" }, t.entry), h("p", { class: "pageIntro" }, t.intro)), h("div", { class: "headTools" }, h("span", null, t.agentTools), sw));
          }
          const bannerBox = h("div");
          function renderBanner() { bannerBox.replaceChildren(); if (st.banner) bannerBox.append(h("div", { class: "s3Banner", "data-kind": st.banner.kind }, h("span", { class: "text" }, st.banner.text), st.banner.progress != null ? h("progress", { max: 100, value: st.banner.progress }) : null, h("button", { type: "button", class: "iconButton sm", title: t.close, onClick: () => setBanner(null) }, ico("x")))); }

          // -------------------------------------------------------- side
          function side() {
            const p = profile();
            const list = h("div", { class: "list" });
            if (st.profiles && !st.profiles.length) list.append(h("div", { class: "s3Empty", style: { padding: "12px" } }, t.empty));
            for (const c of st.profiles || []) list.append(h("button", { type: "button", class: "s3Prof", "data-active": c.id === st.active ? "" : null, title: `${c.bucket} · ${c.endpoint || "AWS"} · ${c.region}`, onClick: () => { if (c.id !== st.active) selectProfile(c.id); } },
              h("div", { class: "l1" }, c.name), h("div", { class: "l2" }, c.bucket + (c.prefix ? "/" + c.prefix : "")), h("div", { class: "l3" }, c.endpoint ? c.endpoint.replace(/^https?:\/\//, "") : `AWS · ${c.region}`)));
            const actions = p ? h("div", { class: "s3Actions" }, h("button", { type: "button", class: "s3Link", disabled: st.testing, onClick: testActive }, t.test), h("button", { type: "button", class: "s3Link", onClick: () => openForm(p) }, t.edit), h("button", { type: "button", class: "s3Link", "data-danger": "", onClick: () => deleteProfile(p) }, t.del)) : null;
            return h("aside", { class: "s3Side" }, h("div", { class: "blockHead" }, h("span", null, t.buckets), h("button", { type: "button", class: "s3Link", onClick: () => openForm(null) }, "+ " + t.add)), list, actions);
          }
          async function testActive() {
            const p = profile(); if (!p) return;
            st.testing = true; setBanner("info", t.testing); render();
            try { const r = (await call("/test", { method: "POST", body: JSON.stringify({ id: p.id }) })).result; setBanner(r.ok ? "ok" : "error", r.ok ? t.testOk(r.latencyMs) : t.testFail(r.error || "?")); }
            catch (err) { fail(err); }
            st.testing = false; render();
          }
          function deleteProfile(p) {
            const { el, close } = modal(`<div class="modalHead">${esc(t.del)}</div><div class="modalBody"><p>${esc(t.deleteConfirm(p.name))}</p></div>${foot(t.del, true)}`);
            el.querySelector("[data-no]").onclick = close;
            el.querySelector("[data-yes]").onclick = async () => { try { await call(`/profiles?id=${encodeURIComponent(p.id)}`, { method: "DELETE" }); close(); if (st.active === p.id) st.active = null; await load(); } catch (err) { close(); fail(err); } };
          }
          function openForm(existing) {
            const d = existing ? { ...existing } : { bucket: "", endpoint: "", region: "us-east-1", name: "", prefix: "", pathStyle: true };
            let accessKey = "", secret = "";
            const { el, close } = modal(`<div class="modalHead">${esc(existing ? t.formEdit(existing.name) : t.formCreate)}</div><div class="modalBody"><div class="s3Form" data-form></div></div>${foot(t.save)}`);
            const form = el.querySelector("[data-form]"); const err = h("div", { class: "err" });
            const input = (key, attrs = {}) => h("input", { class: "input" + (attrs.mono ? " mono" : ""), value: d[key] == null ? "" : d[key], ...attrs, onInput: (e) => { d[key] = e.target.value; } });
            const bucketInput = input("bucket", { mono: true, placeholder: "my-bucket", autofocus: true });
            const nameInput = input("name", { placeholder: t.namePlaceholder });
            bucketInput.addEventListener("input", () => { nameInput.placeholder = bucketInput.value.trim() || t.namePlaceholder; });
            form.append(
              h("label", null, t.bucket, bucketInput),
              h("label", null, t.endpoint, input("endpoint", { mono: true, placeholder: "https://s3.example.com" })),
              h("div", { class: "row" }, h("label", null, t.accessKeyId, h("input", { class: "input mono", autocomplete: "off", placeholder: existing ? existing.accessKeyHint : "", onInput: (e) => { accessKey = e.target.value; } })), h("label", null, t.secretAccessKey, h("input", { class: "input", type: "password", autocomplete: "new-password", placeholder: existing ? "••••••••" : "", onInput: (e) => { secret = e.target.value; } }))),
              h("div", { class: "divider" }, t.optional),
              h("div", { class: "row" }, h("label", null, t.name, nameInput), h("label", null, t.region, input("region", { mono: true, placeholder: "us-east-1" }))),
              h("label", null, t.prefix, input("prefix", { mono: true, placeholder: "team-a/" })),
              h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!d.pathStyle, onChange: (e) => { d.pathStyle = e.target.checked; } }), t.pathStyle),
              err);
            form.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); submit(); } });
            async function submit() {
              const yes = el.querySelector("[data-yes]"); yes.disabled = true; yes.textContent = t.saving;
              const payload = { name: d.name || "", bucket: d.bucket || "", endpoint: d.endpoint || "", region: d.region || "", pathStyle: !!d.pathStyle, prefix: d.prefix || "" };
              if (accessKey.trim() || !existing) payload.accessKeyId = accessKey;
              if (secret || !existing) payload.secretAccessKey = secret;
              try {
                const r = existing ? await call(`/profiles?id=${encodeURIComponent(existing.id)}`, { method: "PATCH", body: JSON.stringify(payload) }) : await call("/profiles", { method: "POST", body: JSON.stringify(payload) });
                close(); const p = await call("/profiles"); st.profiles = p.profiles; selectProfile(r.profile.id);
              } catch (e2) { err.textContent = e2.message; yes.disabled = false; yes.textContent = t.save; }
            }
            el.querySelector("[data-no]").onclick = close; el.querySelector("[data-yes]").onclick = submit;
            bucketInput.focus();
          }

          // -------------------------------------------------------- browser
          const fileInput = h("input", { type: "file", multiple: true, hidden: true, onChange: (e) => { uploadFiles([...e.target.files]); e.target.value = ""; } });
          function browser(p) {
            const box = h("div", { class: "s3Browser" });
            box.addEventListener("dragover", (e) => { e.preventDefault(); box.setAttribute("data-dragover", ""); });
            box.addEventListener("dragleave", () => box.removeAttribute("data-dragover"));
            box.addEventListener("drop", (e) => { e.preventDefault(); box.removeAttribute("data-dragover"); if (e.dataTransfer && e.dataTransfer.files.length) uploadFiles([...e.dataTransfer.files]); });
            // breadcrumbs
            const nav = h("nav", { "aria-label": "path" });
            const rootLabel = p.bucket + (p.prefix ? "/" + p.prefix.replace(/\/$/, "") : "");
            const parts = br.prefix.split("/").filter(Boolean);
            nav.append(h("button", { type: "button", class: "crumb", "data-current": parts.length ? null : "", title: t.root, onClick: () => setPrefix("") }, rootLabel));
            let acc = "";
            parts.forEach((seg, i) => { acc += seg + "/"; const target = acc; nav.append(h("span", { class: "sep" }, "/"), h("button", { type: "button", class: "crumb", "data-current": i === parts.length - 1 ? "" : null, title: target, onClick: () => setPrefix(target) }, seg)); });
            const filter = h("input", { class: "input", placeholder: t.filter, value: br.filter, onInput: (e) => { br.filter = e.target.value; drawTable(); } });
            box.append(h("div", { class: "s3Toolbar" }, nav, h("span", { class: "spacer" }), filter,
              h("button", { type: "button", class: "btn outline sm", disabled: br.loading, onClick: () => list(false) }, t.refresh),
              h("button", { type: "button", class: "btn outline sm", onClick: newFolder }, ico("folder-plus", "ico"), h("span", null, t.newFolder)),
              h("button", { type: "button", class: "btn primary sm", onClick: () => fileInput.click() }, ico("upload", "ico"), h("span", null, t.upload))));
            const wrap = h("div", { class: "s3TableWrap" }); box.append(wrap);
            const footBox = h("div", { class: "s3Foot" }); box.append(footBox);
            function rows() { const f = br.filter.toLowerCase(); const match = (k) => !f || baseName(k).toLowerCase().includes(f); return { folders: br.folders.filter(match), objects: br.objects.filter((o) => match(o.key)) }; }
            function drawTable() {
              wrap.replaceChildren();
              const { folders, objects } = rows();
              if (br.error) wrap.append(h("div", { class: "s3Empty", style: { color: "var(--error)" } }, br.error));
              else if (br.loading && !br.folders.length && !br.objects.length) wrap.append(h("div", { class: "s3Empty" }, t.loading));
              else if (!folders.length && !objects.length) wrap.append(h("div", { class: "s3Empty" }, t.noObjects));
              else {
                const all = [...folders, ...objects.map((o) => o.key)];
                const allSelected = all.length > 0 && all.every((k) => br.selected.has(k));
                const head = h("tr", null, h("th", null, h("input", { type: "checkbox", "aria-label": "select all", checked: allSelected, onChange: (e) => { if (e.target.checked) all.forEach((k) => br.selected.add(k)); else all.forEach((k) => br.selected.delete(k)); render(); } })), h("th", null, t.colName), h("th", { class: "right" }, t.colSize), h("th", null, t.colModified), h("th", { class: "right" }, t.colActions));
                const body = h("tbody");
                const row = (key, isFolder, obj) => h("tr", { "data-selected": br.selected.has(key) ? "" : null },
                  h("td", { class: "sel" }, h("input", { type: "checkbox", checked: br.selected.has(key), onChange: (e) => { if (e.target.checked) br.selected.add(key); else br.selected.delete(key); render(); } })),
                  h("td", { class: "name", title: key }, h("button", { type: "button", onClick: () => (isFolder ? setPrefix(key) : preview(p, obj)) }, ico(isFolder ? "folder" : "file", "ico"), h("span", null, baseName(key)))),
                  h("td", { class: "right" }, isFolder ? "-" : humanSize(obj.size)),
                  h("td", null, isFolder ? "-" : fmtDate(obj.lastModified)),
                  h("td", { class: "acts" }, isFolder ? null : h("a", { class: "s3Link", href: objectUrl(p.id, key, false), download: baseName(key) }, t.download), isFolder ? null : h("button", { type: "button", class: "s3Link", onClick: () => shareLink(p, key) }, t.link), isFolder ? null : h("button", { type: "button", class: "s3Link", onClick: () => rename(p, key) }, t.rename), h("button", { type: "button", class: "s3Link", "data-danger": "", onClick: () => confirmDelete(p, [key]) }, t.del)));
                folders.forEach((f) => body.append(row(f, true, null))); objects.forEach((o) => body.append(row(o.key, false, o)));
                wrap.append(h("table", { class: "s3Table" }, h("thead", null, head), body));
              }
              footBox.replaceChildren();
              if (br.selected.size) footBox.append(h("span", null, t.selected(br.selected.size)), h("button", { type: "button", class: "s3Link", "data-danger": "", onClick: () => confirmDelete(p, [...br.selected]) }, t.deleteSelected), h("button", { type: "button", class: "s3Link", onClick: () => { br.selected.clear(); render(); } }, t.clearSelection));
              else footBox.append(h("span", null, br.folders.length || br.objects.length ? `${br.folders.length} / ${br.objects.length}` : ""));
              footBox.append(h("span", { class: "spacer" }));
              if (br.nextToken) footBox.append(h("button", { type: "button", class: "btn outline sm", disabled: br.loading, onClick: () => list(true) }, br.loading ? t.loading : t.loadMore));
            }
            drawTable();
            return box;
          }
          async function uploadFiles(files) {
            const p = profile(); if (!p) return;
            for (const file of files) {
              const key = br.prefix + file.name;
              setBanner("info", t.uploading(file.name, 0), 0);
              try {
                await new Promise((resolve, reject) => {
                  const xhr = new XMLHttpRequest(); xhr.open("PUT", `/api/s3/upload?id=${encodeURIComponent(p.id)}&key=${encodeURIComponent(key)}`);
                  if (file.type) xhr.setRequestHeader("content-type", file.type);
                  xhr.upload.onprogress = (e) => { if (e.lengthComputable) setBanner("info", t.uploading(file.name, Math.round((e.loaded * 100) / e.total)), Math.round((e.loaded * 100) / e.total)); };
                  xhr.onload = () => { if (xhr.status >= 200 && xhr.status < 300) resolve(); else { let msg = `HTTP ${xhr.status}`; try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* not JSON */ } reject(new Error(msg)); } };
                  xhr.onerror = () => reject(new Error("network error")); xhr.onabort = () => reject(new Error("aborted"));
                  xhr.send(file);
                });
                setBanner("ok", t.uploadDone(file.name));
              } catch (err) { setBanner("error", t.uploadFail(file.name, err.message)); break; }
            }
            list(false);
          }
          function newFolder() {
            const p = profile(); if (!p) return;
            const { el, close } = modal(`<div class="modalHead">${esc(t.newFolder)}</div><div class="s3Meta">${esc(br.prefix || t.root)}</div><div class="modalBody"><label style="font-size:12px;color:var(--label-secondary);margin:0 4px">${esc(t.newFolderPrompt)}</label><input class="input" data-name autocomplete="off"></div>${foot(t.save)}`);
            const input = el.querySelector("[data-name]"); const yes = el.querySelector("[data-yes]"); yes.disabled = true;
            input.oninput = () => { yes.disabled = !input.value.trim(); };
            const submit = async () => { const name = input.value.trim().replace(/^\/+|\/+$/g, ""); if (!name) return; yes.disabled = true; try { await call("/folder", { method: "POST", body: JSON.stringify({ id: p.id, key: br.prefix + name + "/" }) }); close(); setBanner("ok", t.folderCreated(name)); list(false); } catch (err) { close(); fail(err); } };
            input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } };
            el.querySelector("[data-no]").onclick = close; yes.onclick = submit; input.focus();
          }
          function confirmDelete(p, keys) {
            const { el, close } = modal(`<div class="modalHead">${esc(t.deleteTitle)}</div><div class="modalBody"><p>${esc(t.deleteBody(keys.length))}</p><ul class="s3Keys">${keys.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div>${foot(t.deleteOk, true)}`);
            el.querySelector("[data-no]").onclick = close;
            el.querySelector("[data-yes]").onclick = async () => {
              el.querySelector("[data-yes]").disabled = true;
              try {
                const r = (await call("/delete", { method: "POST", body: JSON.stringify({ id: p.id, keys }) })).result;
                close();
                if (r.errors.length) setBanner("error", `${t.deleteErrors(r.errors.length)}: ${r.errors.slice(0, 3).map((e) => `${e.key} (${e.error})`).join("; ")}`); else setBanner("ok", t.deleted(r.deleted));
              } catch (err) { close(); fail(err); }
              br.selected.clear(); list(false);
            };
          }
          function shareLink(p, key) {
            const { el, close } = modal(`<div class="modalHead">${esc(t.linkTitle)}</div><div class="s3Meta">${esc(key)}</div><div class="modalBody"><label style="font-size:12px;color:var(--label-secondary);margin:0 4px">${esc(t.linkExpires)}</label><span class="selectWrap" style="margin:4px"><select class="select" data-exp><option value="3600">${esc(t.exp1h)}</option><option value="86400">${esc(t.exp1d)}</option><option value="604800">${esc(t.exp7d)}</option></select>${icon("chev-down", "ico chev")}</span><div class="err" data-err style="font-size:12px;color:var(--error);margin:4px"></div><div class="s3LinkRow"><input class="input mono" data-url readonly value="${esc(t.loading)}"><button type="button" class="btn primary" data-copy disabled>${esc(t.linkCopy)}</button></div></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.close)}</button></div>`);
            const url = el.querySelector("[data-url]"); const copy = el.querySelector("[data-copy]"); const sel = el.querySelector("[data-exp]"); const err = el.querySelector("[data-err]");
            async function sign() { copy.disabled = true; url.value = t.loading; err.textContent = ""; try { const r = await call("/presign", { method: "POST", body: JSON.stringify({ id: p.id, key, expiresIn: Number(sel.value), method: "GET" }) }); url.value = r.url; copy.disabled = false; copy.textContent = t.linkCopy; } catch (e2) { url.value = ""; err.textContent = e2.message; } }
            sel.onchange = sign; url.onfocus = () => url.select();
            copy.onclick = async () => { try { await navigator.clipboard.writeText(url.value); copy.textContent = t.linkCopied; } catch { url.focus(); url.select(); } };
            el.querySelector("[data-no]").onclick = close; sign();
          }
          function rename(p, key) {
            const dir = key.slice(0, key.lastIndexOf("/") + 1);
            const { el, close } = modal(`<div class="modalHead">${esc(t.rename)}</div><div class="s3Meta">${esc(key)}</div><div class="modalBody"><label style="font-size:12px;color:var(--label-secondary);margin:0 4px">${esc(t.renamePrompt)}</label><input class="input" data-name autocomplete="off"><div data-err style="font-size:12px;color:var(--error);margin:4px"></div></div>${foot(t.save)}`);
            const input = el.querySelector("[data-name]"); input.value = baseName(key); const err = el.querySelector("[data-err]"); const yes = el.querySelector("[data-yes]");
            const submit = async () => { const name = input.value.trim(); if (!name || name.includes("/")) { err.textContent = t.renamePrompt; return; } if (name === baseName(key)) { close(); return; } yes.disabled = true; yes.textContent = t.saving; try { await call("/copy", { method: "POST", body: JSON.stringify({ id: p.id, from: key, to: dir + name, move: true }) }); close(); list(false); } catch (e2) { err.textContent = e2.message; yes.disabled = false; yes.textContent = t.save; } };
            input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } };
            el.querySelector("[data-no]").onclick = close; yes.onclick = submit; input.focus(); input.select();
          }
          async function preview(p, obj) {
            const key = obj.key;
            const { el, close } = modal(`<div class="modalHead">${esc(baseName(key))}</div><div class="s3Meta">${esc(key)} · ${esc(humanSize(obj.size))}</div><div class="modalBody s3Preview" data-body><div class="s3Empty">${esc(t.loading)}</div></div><div class="modalFoot"><span class="spacer"></span><a class="btn outline" href="${esc(objectUrl(p.id, key, false))}" download="${esc(baseName(key))}">${esc(t.download)}</a><button type="button" class="btn primary" data-no>${esc(t.close)}</button></div>`, true);
            const body = el.querySelector("[data-body]"); el.querySelector("[data-no]").onclick = close;
            if (IMAGE_RE.test(key)) { body.replaceChildren(h("img", { src: objectUrl(p.id, key, true), alt: baseName(key) })); return; }
            try { const r = await call(`/text?id=${encodeURIComponent(p.id)}&key=${encodeURIComponent(key)}`); body.replaceChildren(h("pre", { class: "s3Pre" }, r.text), r.truncated ? h("div", { class: "s3Meta", style: { margin: "4px" } }, t.previewTruncated) : null); }
            catch (err) { body.replaceChildren(h("div", { class: "s3Empty" }, /binary/i.test(err.message) ? t.previewBinary : err.message)); }
          }

          // -------------------------------------------------------- render
          function render() {
            if (!alive) return;
            const p = profile();
            root.replaceChildren(header(), bannerBox, fileInput, h("div", { class: "s3Body" }, side(), p ? browser(p) : h("div", { class: "s3Browser" }, h("div", { class: "s3Empty" }, t.selectProfile))));
            renderBanner();
          }
          render(); load();
          return () => { alive = false; };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "s3", label: t.entry, icon: "archive", description: t.intro, order: 50 });
        ctx.slots.register({ slot: "main", key: "s3", label: t.entry }, page);
      },
    };
  },
});
