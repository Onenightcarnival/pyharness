window.__PyhModules__.load({
  id: "config-center",
  factory(require) {
    const { h, icon, esc, toast, json, waitForRestart } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: {
        mcp: "MCP", mcpIntro: "管理模型可调用的 MCP 服务器。保存后重启生效；工具名以服务器名作前缀，权限模式与审批照常适用。", servers: "服务器", add: "添加", empty: "还没有服务器。点「添加」新建一个。", none: "在左侧选择一个服务器，或点「添加」。", newServer: "新服务器", off: "已停用", enabled: "启用", name: "名称", nameHint: "工具前缀为 名称_，限 1–64 位字母、数字、_、-", transport: "连接方式", transportHttp: "远程服务（streamable HTTP）", transportSse: "远程服务（SSE）", transportStdio: "本机命令（stdio）", url: "服务器地址", headers: "请求头", headersAdd: "添加请求头", command: "命令", commandHint: "只填可执行文件，参数写在下方；裸 bun / bunx 会使用「设置 → 环境依赖」安装的 bun", args: "参数", argsHint: "每行一个", env: "环境变量", envAdd: "添加环境变量", cwd: "工作目录", optional: "可选", value: "值", remove: "移除", stdioNote: "命令以当前用户身份在本机执行，只添加信任的服务器。首次运行 npx / bunx 会下载依赖。", approval: "调用前需要批准", del: "删除", deleteConfirm: (n) => `删除服务器「${n}」？`, deleted: "已删除", test: "测试连接", testing: "测试中…", testingStdio: (s) => `测试中…首次运行需下载依赖，最长 ${s} 秒`, startupWait: "启动等待（秒）", startupWaitHint: "默认 20 秒，适用于所有服务器的连接与工具列表。", connectionSettings: "连接设置", details: "详情", saveTimeout: "保存等待时间", timeoutIssue: "等待时间须为 1–86400 的数字（秒）。", saving: "保存中…", save: "保存", saved: "已保存，已生效", savedRestart: "已保存，重启后生效", savedManual: "已保存，需重启 harness 后生效", refresh: "刷新", cancel: "取消", close: "关闭", loading: "加载中…", stateConnected: (n) => `已连接，${n} 个工具`, stateError: (e) => `连接失败：${e}`, stateDisabled: "已停用", stateWaiting: (r) => `等待凭据：${r}`, stateUnknown: "尚未连接，重启后生效", testOk: (n, names) => `握手成功，提供 ${n} 个工具${names ? "：" + names : ""}`, testFail: (e) => `连接失败：${e}`, importJson: "导入 JSON", importHint: "粘贴 Claude Desktop / Cursor 风格的 {\"mcpServers\": {...}} 配置，或单个服务器对象。", importOk: (n) => `已导入 ${n} 个服务器，记得保存`, importBad: "无法解析：需要 JSON 对象", issueName: "名称需为 1–64 位字母、数字、_、-", issueCommand: "请填写命令，例如 npx、bunx 或 uvx", issueUrl: "地址需以 http:// 或 https:// 开头", issueDuplicate: "名称与已有服务器重复",
        credentialHint: "值可写成 ${credential:NAME}，连接时从同名环境变量或凭据库取值；这类值按原样显示。", credentials: "凭据", credentialsHint: "凭据值保存在 profile 的凭据库中，不写入配置，保存后不再显示。", credEnv: "已配置（环境变量）", credStore: "已配置（凭据库）", credMissing: "缺失", credUnknown: "保存后显示状态", credValue: "凭据值", credEmpty: "请输入凭据值", credDeleteConfirm: (n) => `删除凭据库中的「${n}」？`,
        skills: "技能", skillsIntro: "放在 profile 数据目录下的技能（SKILL.md 包），启用的技能挂载给 agent 读取；可安装 ZIP、启停与删除。", open: "打开目录", install: "安装 ZIP", zipLimit: "ZIP 最大 32 MB", installed: (c, s) => `已安装 ${c} 个，跳过 ${s} 个`, conflicts: "技能已存在", replaceHint: "覆盖将替换原内容，并启用新版本。", replace: "覆盖", skip: "跳过同名", skillsEmpty: "尚未安装技能", skillEnabled: "已启用", metadata: "技能信息", files: "文件", truncated: "内容已截断", skillDeleteConfirm: (n) => `删除技能「${n}」及其文件？`, selectSkill: "在左侧选择一个技能。",
        envTitle: "环境依赖", envIntro: "管理 JavaScript MCP 服务器使用的独立 bun 运行环境。", envDesc: "bun 专属运行环境：MCP 服务器命令写 bun / bunx 时自动使用它。", check: "检测", version: "已安装版本", available: "提供版本", platform: "平台", path: "可执行文件", data: "数据目录", installBtn: "安装", repair: "修复", working: "正在准备…", firstRun: "首次运行时联网下载依赖。", unsupported: "支持 Windows、macOS 和 glibc Linux 的 x64 / ARM64。", docs: "使用文档", states: { missing: "未安装", ready: "已就绪", downloading: "下载中", verifying: "校验中", installing: "安装中", error: "异常", unsupported: "暂不支持" },
      },
      en: {
        mcp: "MCP", mcpIntro: "Manage the MCP servers the model can call. Changes apply after a restart; tool names are prefixed with the server name, and permission modes and approvals apply as usual.", servers: "Servers", add: "Add", empty: "No servers yet. Choose Add to create one.", none: "Select a server on the left, or choose Add.", newServer: "New server", off: "Disabled", enabled: "Enabled", name: "Name", nameHint: "Tool prefix name_; 1–64 letters, digits, _ or -", transport: "Transport", transportHttp: "Remote service (streamable HTTP)", transportSse: "Remote service (SSE)", transportStdio: "Local command (stdio)", url: "Server URL", headers: "Request headers", headersAdd: "Add header", command: "Command", commandHint: "The executable only; arguments go below. A bare bun / bunx uses the bun installed in Settings → Environment", args: "Arguments", argsHint: "One per line", env: "Environment variables", envAdd: "Add variable", cwd: "Working directory", optional: "optional", value: "Value", remove: "Remove", stdioNote: "The command runs on this machine as the current user; add trusted servers only. The first npx / bunx run downloads dependencies.", approval: "Ask before each call", del: "Delete", deleteConfirm: (n) => `Delete server "${n}"?`, deleted: "Deleted", test: "Test connection", testing: "Testing…", testingStdio: (s) => `Testing… the first run downloads dependencies, up to ${s} seconds`, startupWait: "Startup wait (seconds)", startupWaitHint: "Default: 20 seconds. Applies to connecting and listing tools of every server.", connectionSettings: "Connection settings", details: "Details", saveTimeout: "Save wait time", timeoutIssue: "Wait time must be a number from 1 to 86400 seconds.", saving: "Saving…", save: "Save", saved: "Saved and applied", savedRestart: "Saved; applies after the restart", savedManual: "Saved; restart the harness to apply", refresh: "Refresh", cancel: "Cancel", close: "Close", loading: "Loading…", stateConnected: (n) => `Connected, ${n} tools`, stateError: (e) => `Failed to load: ${e}`, stateDisabled: "Disabled", stateWaiting: (r) => `Waiting for credentials: ${r}`, stateUnknown: "Not connected yet; applies after the restart", testOk: (n, names) => `Handshake succeeded, ${n} tools${names ? ": " + names : ""}`, testFail: (e) => `Connection failed: ${e}`, importJson: "Import JSON", importHint: 'Paste a Claude Desktop / Cursor style {"mcpServers": {...}} configuration, or a single server object.', importOk: (n) => `Imported ${n} server(s); remember to save`, importBad: "Cannot parse: a JSON object is required", issueName: "The name takes 1–64 letters, digits, _ or -", issueCommand: "Enter a command, e.g. npx, bunx or uvx", issueUrl: "The URL starts with http:// or https://", issueDuplicate: "Another server already uses this name",
        credentialHint: "A value may be ${credential:NAME}: it resolves from the environment variable of that name or the credential store when the server connects, and is shown as written.", credentials: "Credentials", credentialsHint: "Values are kept in the profile credential store, outside the configuration, and are not shown after saving.", credEnv: "Configured (environment variable)", credStore: "Configured (credential store)", credMissing: "Missing", credUnknown: "State appears after saving", credValue: "Credential value", credEmpty: "Enter a credential value", credDeleteConfirm: (n) => `Delete "${n}" from the credential store?`,
        skills: "Skills", skillsIntro: "Skills (SKILL.md bundles) under the profile data directory; enabled ones are mounted for the agent to read. Install ZIPs, enable, disable and delete.", open: "Open folder", install: "Install ZIP", zipLimit: "ZIP limit: 32 MB", installed: (c, s) => `Installed ${c}, skipped ${s}`, conflicts: "Skills already exist", replaceHint: "Replace existing files and enable the new version.", replace: "Replace", skip: "Skip existing", skillsEmpty: "No skills installed", skillEnabled: "Enabled", metadata: "Skill info", files: "Files", truncated: "Content truncated", skillDeleteConfirm: (n) => `Delete skill “${n}” and its files?`, selectSkill: "Select a skill on the left.",
        envTitle: "Environment dependencies", envIntro: "Manage the isolated bun runtime used by JavaScript MCP servers.", envDesc: "Isolated bun runtime: MCP server commands written as bun / bunx use it automatically.", check: "Check", version: "Installed version", available: "Provided version", platform: "Platform", path: "Executable", data: "Data directory", installBtn: "Install", repair: "Repair", working: "Preparing…", firstRun: "The first run downloads dependencies.", unsupported: "Supports Windows, macOS and glibc Linux on x64 / ARM64.", docs: "Documentation", states: { missing: "Not installed", ready: "Ready", downloading: "Downloading", verifying: "Verifying", installing: "Installing", error: "Error", unsupported: "Unsupported" },
      },
    };
    const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
    const MASK = "••••";
    const CREDENTIAL_RE = /\$\{credential:([A-Z][A-Z0-9_]{0,127})\}/g;
    const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none"><symbol id="i-sparkle" viewBox="0 0 16 16"><path d="m8 1.75 1.75 4.5 4.5 1.75-4.5 1.75L8 14.25l-1.75-4.5-4.5-1.75 4.5-1.75z"/></symbol></svg>`;
    async function call(path, opts) {
      const res = await fetch("/api/config-center" + path, { headers: { "content-type": "application/json" }, ...(opts || {}) });
      if (!res.ok) { let detail = `HTTP ${res.status}`; try { const d = (await res.json()).detail; if (typeof d === "string") detail = d; else if (d) detail = JSON.stringify(d); } catch { /* no body */ } throw new Error(detail); }
      return res.json();
    }

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        if (!document.getElementById("i-sparkle")) document.body.insertAdjacentHTML("beforeend", sprite);
        const style = document.createElement("style");
        style.textContent = `
          .ccPage { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0 24px 16px; }
          .ccPage .pageHead { flex: none; flex-wrap: wrap; padding-bottom: 10px; }
          .ccPage .headTools { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
          .ccNotice { margin: 0 0 10px; padding: 7px 12px; border-radius: 8px; font-size: 12px; display: flex; align-items: center; gap: 8px; flex: none; }
          .ccNotice span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
          .ccNotice[data-kind="ok"] { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }
          .ccNotice[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .ccNotice[data-kind="info"] { background: color-mix(in srgb, var(--info) 10%, transparent); color: var(--info); }
          .ccNotice details { font-size: 11px; } .ccNotice pre { margin: 4px 0 0; white-space: pre-wrap; font: 11px/16px var(--mono); }
          .ccBody { flex: 1; min-height: 0; display: flex; gap: 12px; }
          .ccSide { width: clamp(180px, 22%, 280px); flex: none; display: flex; flex-direction: column; gap: 6px; min-height: 0; border-right: 0.5px solid var(--border-l2); padding-right: 12px; }
          .ccSide .blockHead { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: var(--label-secondary); padding: 2px 0; }
          .ccSide .blockHead span { flex: 1; }
          .ccSide .list { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
          .ccRow { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 7px 8px; border: none; border-radius: 8px; background: transparent; color: var(--label-primary); }
          .ccRow:hover { background: var(--hover); }
          .ccRow[aria-current="true"] { background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .ccRow .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--label-dimmed); flex: none; }
          .ccRow .dot[data-state="connected"] { background: var(--success); } .ccRow .dot[data-state="error"] { background: var(--error); } .ccRow .dot[data-state="waiting-credentials"] { background: var(--warn); }
          .ccRow .main { flex: 1; min-width: 0; }
          .ccRow .main b { display: block; font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ccRow .main small { display: block; font-size: 11px; color: var(--label-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ccRow .tag { flex: none; }
          .ccLink { background: none; border: none; padding: 0; font-size: 12px; color: var(--info); cursor: pointer; }
          .ccLink[data-danger] { color: var(--error); } .ccLink:disabled { opacity: .5; cursor: default; }
          .ccMain { flex: 1; min-width: 0; min-height: 0; overflow: auto; }
          .ccCard { padding: 16px 18px; border-radius: 12px; background: var(--layer-1); box-shadow: inset 0 0 0 0.5px var(--border-l2); display: flex; flex-direction: column; gap: 12px; }
          .ccCard .cardHead { display: flex; align-items: center; gap: 10px; }
          .ccCard .cardHead h2 { margin: 0; flex: 1; font-size: 15px; font-weight: 500; }
          .ccCard .status { font-size: 12px; color: var(--label-secondary); }
          .ccForm { display: flex; flex-direction: column; gap: 12px; }
          .ccForm label.f { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--label-secondary); }
          .ccForm .hint { font-size: 11px; color: var(--label-tertiary); }
          .ccForm textarea { width: 100%; min-height: 72px; padding: 8px 12px; border: 0.5px solid var(--border-l4); border-radius: var(--r-md); background: var(--bg-layer-1); color: var(--label-primary); font: 12px/18px var(--mono); resize: vertical; outline: none; }
          .ccForm textarea:focus { border-color: var(--info); }
          .ccPairs { display: flex; flex-direction: column; gap: 6px; }
          .ccPairs .pair { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; align-items: center; }
          .ccForm .check { display: flex; align-items: center; gap: 6px; font-size: 12px; }
          .ccCreds { display: flex; flex-direction: column; gap: 6px; padding-top: 12px; border-top: 0.5px solid var(--border-l2); } .ccCreds[hidden] { display: none; }
          .ccCreds .credHead { font-size: 12px; font-weight: 500; color: var(--label-secondary); } .ccCreds .hint { font-size: 11px; color: var(--label-tertiary); }
          .ccCreds .cred { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; } .ccCreds .cred code { font: 12px var(--mono); overflow-wrap: anywhere; } .ccCreds .cred .input { flex: 1; min-width: 140px; }
          .ccActions { display: flex; align-items: center; gap: 8px; padding-top: 4px; border-top: 0.5px solid var(--border-l2); }
          .ccActions .spacer { flex: 1; }
          .ccDetails { font-size: 12px; } .ccDetails summary { cursor: pointer; color: var(--label-secondary); }
          .ccDetails .inner { display: flex; align-items: center; gap: 8px; padding: 8px 0 4px; flex-wrap: wrap; }
          .ccDetails .inner .input { width: 110px; }
          .ccEmpty { padding: 32px 12px; text-align: center; font-size: 12.5px; color: var(--label-tertiary); }
          .ccSkillBody { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
          .ccSkillBody .filesWrap { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 10px; min-height: 240px; }
          .ccSkillBody .tree { display: flex; flex-direction: column; gap: 2px; overflow: auto; max-height: 50vh; }
          .ccSkillBody .tree button { text-align: left; padding: 4px 8px; border: none; border-radius: 6px; background: transparent; color: var(--label-primary); font: 12px var(--mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ccSkillBody .tree button:hover { background: var(--hover); } .ccSkillBody .tree button[aria-current="true"] { background: color-mix(in srgb, var(--info) 12%, transparent); color: var(--info); }
          .ccSkillBody pre { margin: 0; padding: 10px 12px; border-radius: 8px; background: var(--layer-2); font: 12px/18px var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 50vh; overflow: auto; }
          .ccSkillBody .desc { font-size: 13px; line-height: 20px; max-height: 80px; overflow: auto; }
          .ccEnvCard { padding: 16px 18px; border-radius: 12px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); display: flex; flex-direction: column; gap: 10px; max-width: 760px; }
          .ccEnvCard .head { display: flex; align-items: center; gap: 10px; } .ccEnvCard .head b { font-size: 14px; font-weight: 500; flex: 1; }
          .ccEnvCard dl { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 4px 12px; margin: 0; font-size: 12px; }
          .ccEnvCard dt { color: var(--label-tertiary); } .ccEnvCard dd { margin: 0; font-family: var(--mono); overflow-wrap: anywhere; }
          .ccEnvCard progress { width: 100%; height: 6px; }
          .ccEnvCard .row { display: flex; align-items: center; gap: 8px; } .ccEnvCard .row .spacer { flex: 1; }
          .ccEnvCard .meta { font-size: 12px; color: var(--label-tertiary); }
          .ccEnvCard .err { font-size: 12px; color: var(--error); }
          @container (max-width: 640px) { .ccBody { flex-direction: column; } .ccSide { width: auto; border-right: none; padding-right: 0; max-height: 150px; } .ccSkillBody .filesWrap { grid-template-columns: 1fr; } }
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
        const confirmBox = (title, text, okLabel) => new Promise((resolve) => {
          const { el, close } = modal(`<div class="modalHead">${esc(title)}</div><div class="modalBody"><p>${esc(text)}</p></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes style="background:var(--error)">${esc(okLabel)}</button></div>`);
          el.querySelector("[data-no]").onclick = () => { close(); resolve(false); }; el.querySelector("[data-yes]").onclick = () => { close(); resolve(true); };
        });
        const notice = (box, kind, text, detail) => { box.replaceChildren(); if (!kind) return; const n = h("div", { class: "ccNotice", "data-kind": kind }, h("span", null, text)); if (detail) n.append(h("details", null, h("summary", null, t.details), h("pre", null, detail))); n.append(h("button", { type: "button", class: "iconButton sm", title: t.close, onClick: () => box.replaceChildren() }, ico("x"))); box.append(n); };

        // ============================================================ MCP page
        function mcpPage(el) {
          let alive = true;
          // creds: reference → { reference, configured, source } as the server last described it; secrets: reference → typed, unsaved value.
          const st = { servers: null, timeout: 20, selected: null, draft: null, busy: false, creds: {}, secrets: {} };
          const root = h("div", { class: "ccPage" }); el.replaceChildren(root);
          const noticeBox = h("div");
          async function load(keepDraft) { try { const d = await call("/mcp"); if (!alive) return; st.servers = d.servers; st.timeout = d.connectTimeout; for (const sv of Object.values(st.servers)) for (const c of sv.credentials || []) st.creds[c.reference] = c; if (st.selected && st.selected !== "" && !st.servers[st.selected]) { st.selected = null; st.draft = null; } else if (st.selected && st.servers[st.selected] && keepDraft !== true) st.draft = draftOf(st.selected); render(); } catch (err) { notice(noticeBox, "error", err.message); render(); } }
          const stateText = (sv) => sv.state === "connected" ? t.stateConnected((sv.tools || []).length) : sv.state === "error" ? t.stateError(sv.error || "?") : sv.state === "disabled" ? t.stateDisabled : sv.state === "waiting-credentials" ? t.stateWaiting((sv.missing || []).join(", ")) : t.stateUnknown;
          const savedText = (application) => application === "restart-scheduled" ? t.savedRestart : application === "saved-restart-required" ? t.savedManual : t.saved;
          const kindOf = (sv) => (sv.command ? "stdio" : sv.transport === "sse" ? "sse" : "streamable_http");
          function draftOf(name) {
            const sv = name ? st.servers[name] : null;
            return sv ? { name, transport: kindOf(sv), command: sv.command || "", args: [...(sv.args || [])], env: { ...(sv.env || {}) }, cwd: sv.cwd || "", url: sv.url || "", headers: { ...(sv.headers || {}) }, enabled: sv.enabled !== false, approval: !!sv.approval }
              : { name: "", transport: "streamable_http", command: "", args: [], env: {}, cwd: "", url: "", headers: {}, enabled: true, approval: false };
          }
          function select(name) { st.selected = name; st.draft = draftOf(name); st.secrets = {}; render(); }
          function payloadOf(d) {
            const base = { enabled: d.enabled, approval: d.approval };
            if (d.transport === "stdio") return { ...base, command: d.command.trim(), args: d.args.map((a) => a.trim()).filter(Boolean), env: clean(d.env), cwd: d.cwd.trim() || undefined };
            return { ...base, transport: d.transport, url: d.url.trim(), headers: clean(d.headers) };
          }
          const clean = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k.trim(), v]).filter(([k]) => k));
          const serverPayload = (sv) => ({ transport: sv.command ? undefined : sv.transport, command: sv.command || undefined, args: sv.args || [], env: sv.env || {}, cwd: sv.cwd || undefined, url: sv.url || undefined, headers: sv.headers || {}, enabled: sv.enabled !== false, approval: sv.approval || false, prefix: sv.prefix !== false });
          function validate(d) {
            if (!NAME_RE.test(d.name.trim())) return t.issueName;
            if (d.name.trim() !== st.selected && st.servers[d.name.trim()]) return t.issueDuplicate;
            if (d.transport === "stdio" && !d.command.trim()) return t.issueCommand;
            if (d.transport !== "stdio" && !/^https?:\/\/\S+$/.test(d.url.trim())) return t.issueUrl;
            return null;
          }
          async function saveAll(servers, okText) {
            st.busy = true; render();
            try {
              const r = await json("/settings/mcp", { method: "PUT", body: JSON.stringify({ servers }) });
              notice(noticeBox, "ok", savedText(r.application));
              if (r.application === "restart-scheduled") waitForRestart().then(() => { if (alive) load(); });
              await load();
              return true;
            } catch (err) { notice(noticeBox, "error", err.message); return false; }
            finally { st.busy = false; render(); }
          }
          async function save() {
            const d = st.draft; const issue = validate(d); if (issue) { notice(noticeBox, "error", issue); return; }
            const servers = {}; for (const [n, sv] of Object.entries(st.servers)) if (n !== st.selected) servers[n] = serverPayload(sv);
            servers[d.name.trim()] = payloadOf(d);
            if (await saveAll(servers)) select(d.name.trim());
          }
          async function remove() {
            if (!st.selected) { select(null); return; }
            if (!(await confirmBox(t.del, t.deleteConfirm(st.selected), t.del))) return;
            const servers = {}; for (const [n, sv] of Object.entries(st.servers)) if (n !== st.selected) servers[n] = serverPayload(sv);
            const ok = await saveAll(servers); if (ok) { notice(noticeBox, "ok", t.deleted); select(Object.keys(st.servers)[0] || null); }
          }
          async function test() {
            const d = st.draft; const issue = validate(d); if (issue) { notice(noticeBox, "error", issue); return; }
            st.busy = true; render(); notice(noticeBox, "info", d.transport === "stdio" ? t.testingStdio(st.timeout) : t.testing);
            try { const r = (await call("/mcp/test", { method: "POST", body: JSON.stringify({ name: st.selected || undefined, server: payloadOf(d) }) })).result; if (r.ok) notice(noticeBox, "ok", t.testOk(r.tools.length, r.tools.slice(0, 12).join(", ") + (r.tools.length > 12 ? "…" : ""))); else notice(noticeBox, "error", t.testFail(r.error || r.code), r.error); }
            catch (err) { notice(noticeBox, "error", t.testFail(err.message)); }
            st.busy = false; render();
          }
          function importJson() {
            const { el, close } = modal(`<div class="modalHead">${esc(t.importJson)}</div><div class="modalBody"><p>${esc(t.importHint)}</p><textarea class="input mono" data-json rows="10" style="margin:4px;width:calc(100% - 8px);height:200px;padding:8px 12px;font:12px/18px var(--mono);resize:vertical"></textarea><div data-err style="font-size:12px;color:var(--error);margin:4px"></div></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes>${esc(t.importJson)}</button></div>`, true);
            el.querySelector("[data-no]").onclick = close;
            el.querySelector("[data-yes]").onclick = async () => {
              let data; try { data = JSON.parse(el.querySelector("[data-json]").value); } catch { el.querySelector("[data-err]").textContent = t.importBad; return; }
              if (!data || typeof data !== "object") { el.querySelector("[data-err]").textContent = t.importBad; return; }
              let entries = data.mcpServers && typeof data.mcpServers === "object" ? data.mcpServers : (data.command || data.url) ? { [data.name || "imported"]: data } : data;
              const servers = {}; for (const [n, sv] of Object.entries(st.servers)) servers[n] = serverPayload(sv);
              let count = 0;
              for (const [n, sv] of Object.entries(entries)) {
                if (!sv || typeof sv !== "object" || !NAME_RE.test(n)) continue;
                if (sv.command) servers[n] = { command: String(sv.command), args: Array.isArray(sv.args) ? sv.args.map(String) : [], env: sv.env && typeof sv.env === "object" ? sv.env : {}, cwd: sv.cwd || undefined, enabled: sv.disabled !== true, approval: false, prefix: true };
                else if (sv.url) servers[n] = { transport: sv.type === "sse" || sv.transport === "sse" ? "sse" : "streamable_http", url: String(sv.url), headers: sv.headers && typeof sv.headers === "object" ? sv.headers : {}, enabled: sv.disabled !== true, approval: false, prefix: true };
                else continue;
                count += 1;
              }
              if (!count) { el.querySelector("[data-err]").textContent = t.importBad; return; }
              close(); if (await saveAll(servers)) notice(noticeBox, "ok", t.importOk(count));
            };
            el.querySelector("[data-json]").focus();
          }
          function draftReferences(d) {
            const texts = d.transport === "stdio" ? [d.command, ...d.args, ...Object.values(d.env), d.cwd] : [d.url, ...Object.values(d.headers)];
            const refs = []; for (const text of texts) for (const m of String(text || "").matchAll(CREDENTIAL_RE)) if (!refs.includes(m[1])) refs.push(m[1]);
            return refs;
          }
          async function applyCredential(ref, query, opts) {
            st.busy = true; render();
            try {
              const r = await call("/mcp/credentials" + query, opts);
              st.creds[ref] = r.credential; delete st.secrets[ref];
              notice(noticeBox, "ok", savedText(r.application));
              if (r.application === "restart-scheduled") waitForRestart().then(() => { if (alive) load(true); });
            } catch (err) { notice(noticeBox, "error", err.message); }
            st.busy = false; render();
          }
          async function saveCredential(ref) {
            const value = (st.secrets[ref] || "").trim(); if (!value) { notice(noticeBox, "error", t.credEmpty); return; }
            await applyCredential(ref, "", { method: "PUT", body: JSON.stringify({ reference: ref, value }) });
          }
          async function deleteCredential(ref) {
            if (!(await confirmBox(t.del, t.credDeleteConfirm(ref), t.del))) return;
            await applyCredential(ref, `?reference=${encodeURIComponent(ref)}`, { method: "DELETE" });
          }
          async function saveTimeout(value) {
            const n = Number(value); if (!Number.isFinite(n) || n < 1 || n > 86400) { notice(noticeBox, "error", t.timeoutIssue); return; }
            try { const r = await call("/mcp/timeout", { method: "PUT", body: JSON.stringify({ connectTimeout: n }) }); st.timeout = r.connectTimeout; notice(noticeBox, "ok", t.saved); } catch (err) { notice(noticeBox, "error", err.message); }
          }

          function pairs(obj, keyPh, addLabel) {
            const box = h("div", { class: "ccPairs" });
            const draw = () => {
              box.replaceChildren();
              for (const [k, v] of Object.entries(obj)) {
                const keyIn = h("input", { class: "input mono", value: k, placeholder: keyPh, onChange: (e) => { const nk = e.target.value; const val = obj[k]; delete obj[k]; obj[nk] = val; draw(); } });
                const valIn = h("input", { class: "input mono", value: v, placeholder: t.value, onInput: (e) => { obj[k] = e.target.value; } });
                box.append(h("div", { class: "pair" }, keyIn, valIn, h("button", { type: "button", class: "iconButton sm", title: t.remove, onClick: () => { delete obj[k]; draw(); } }, ico("x"))));
              }
              box.append(h("button", { type: "button", class: "ccLink", style: { alignSelf: "flex-start" }, onClick: () => { let i = 1; while (obj[`KEY${i}`] !== undefined) i += 1; obj[`KEY${i}`] = ""; draw(); } }, "＋ " + addLabel));
            };
            draw(); return box;
          }
          function editor() {
            const d = st.draft; const sv = st.selected ? st.servers[st.selected] : null;
            const form = h("div", { class: "ccForm" });
            const head = h("div", { class: "cardHead" }, h("h2", null, st.selected || t.newServer), h("span", { style: { fontSize: "12px", color: "var(--label-secondary)" } }, t.enabled), h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(d.enabled), onClick: (e) => { d.enabled = !d.enabled; e.currentTarget.setAttribute("aria-checked", String(d.enabled)); } }, h("span", { class: "knob" })));
            const draw = () => {
              form.replaceChildren();
              if (sv) form.append(h("div", { class: "status" }, stateText(sv)));
              form.append(h("label", { class: "f" }, t.name, h("input", { class: "input mono", value: d.name, placeholder: "my-server", readonly: !!st.selected, onInput: (e) => { d.name = e.target.value; } }), h("span", { class: "hint" }, t.nameHint)));
              form.append(h("label", { class: "f" }, t.transport, h("span", { class: "selectWrap" }, h("select", { class: "select", onChange: (e) => { d.transport = e.target.value; draw(); } }, [["streamable_http", t.transportHttp], ["sse", t.transportSse], ["stdio", t.transportStdio]].map(([v, l]) => h("option", { value: v, selected: d.transport === v }, l))), ico("chev-down", "ico chev"))));
              if (d.transport === "stdio") {
                form.append(h("label", { class: "f" }, t.command, h("input", { class: "input mono", value: d.command, placeholder: "npx / bunx / uvx", onInput: (e) => { d.command = e.target.value; } }), h("span", { class: "hint" }, t.commandHint)));
                form.append(h("label", { class: "f" }, t.args, h("textarea", { placeholder: "-y\n@modelcontextprotocol/server-filesystem\n/path/to/dir", onInput: (e) => { d.args = e.target.value.split("\n"); } }, d.args.join("\n")), h("span", { class: "hint" }, t.argsHint)));
                form.append(h("label", { class: "f" }, t.env, pairs(d.env, "API_KEY", t.envAdd), h("span", { class: "hint" }, t.credentialHint)));
                form.append(h("label", { class: "f" }, `${t.cwd} (${t.optional})`, h("input", { class: "input mono", value: d.cwd, placeholder: "/path/to/project", onInput: (e) => { d.cwd = e.target.value; } })));
                form.append(h("div", { class: "hint" }, t.stdioNote));
              } else {
                form.append(h("label", { class: "f" }, t.url, h("input", { class: "input mono", value: d.url, placeholder: "http://127.0.0.1:8080/mcp", onInput: (e) => { d.url = e.target.value; } })));
                form.append(h("label", { class: "f" }, t.headers, pairs(d.headers, "Authorization", t.headersAdd), h("span", { class: "hint" }, t.credentialHint)));
              }
              form.append(h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.approval, onChange: (e) => { d.approval = e.target.checked; } }), t.approval));
            };
            draw();
            const creds = h("div", { class: "ccCreds", hidden: true }); let shown = null;
            const drawCreds = () => {
              const refs = draftReferences(d); if (refs.join(" ") === shown) return;
              shown = refs.join(" "); creds.hidden = !refs.length; creds.replaceChildren();
              if (!refs.length) return;
              creds.append(h("div", { class: "credHead" }, t.credentials), h("div", { class: "hint" }, t.credentialsHint));
              for (const ref of refs) {
                const c = st.creds[ref];
                const row = h("div", { class: "cred" }, h("code", null, ref), h("span", { class: "tag", "data-tone": !c ? "outline" : c.configured ? "success" : "warning" }, !c ? t.credUnknown : c.source === "env" ? t.credEnv : c.source === "store" ? t.credStore : t.credMissing));
                if (!c || c.source !== "env") {
                  row.append(h("input", { class: "input mono", type: "password", autocomplete: "new-password", value: st.secrets[ref] || "", placeholder: t.credValue, "aria-label": `${ref} ${t.credValue}`, onInput: (e) => { st.secrets[ref] = e.target.value; } }), h("button", { type: "button", class: "btn outline sm", disabled: st.busy, onClick: () => saveCredential(ref) }, t.save));
                  if (c && c.source === "store") row.append(h("button", { type: "button", class: "btn outline sm", style: { color: "var(--error)" }, disabled: st.busy, onClick: () => deleteCredential(ref) }, t.del));
                }
                creds.append(row);
              }
            };
            for (const type of ["input", "change", "click"]) form.addEventListener(type, drawCreds);
            drawCreds();
            const actions = h("div", { class: "ccActions" }, h("button", { type: "button", class: "btn outline sm", style: { color: "var(--error)" }, disabled: st.busy, onClick: remove }, t.del), h("span", { class: "spacer" }), h("button", { type: "button", class: "btn outline sm", disabled: st.busy, onClick: test }, st.busy ? t.testing : t.test), h("button", { type: "button", class: "btn primary sm", disabled: st.busy, onClick: save }, st.busy ? t.saving : t.save));
            return h("div", { class: "ccCard" }, head, form, creds, actions);
          }
          function render() {
            if (!alive) return;
            const tools = h("div", { class: "headTools" }, h("button", { type: "button", class: "btn outline sm", onClick: importJson }, t.importJson), h("button", { type: "button", class: "iconButton", title: t.refresh, onClick: load }, ico("refresh")));
            const head = h("div", { class: "pageHead" }, h("div", null, h("h1", { class: "pageTitle" }, t.mcp), h("p", { class: "pageIntro" }, t.mcpIntro)), tools);
            const timeoutIn = h("input", { class: "input", type: "number", min: 1, max: 86400, step: 1, value: st.timeout });
            const settings = h("details", { class: "ccDetails" }, h("summary", null, t.connectionSettings), h("div", { class: "inner" }, h("span", null, t.startupWait), timeoutIn, h("button", { type: "button", class: "btn outline sm", onClick: () => saveTimeout(timeoutIn.value) }, t.saveTimeout), h("span", { class: "hint", style: { fontSize: "11px", color: "var(--label-tertiary)" } }, t.startupWaitHint)));
            const list = h("div", { class: "list" });
            if (!st.servers) list.append(h("div", { class: "ccEmpty" }, t.loading));
            else {
              const names = Object.keys(st.servers);
              if (!names.length && st.selected !== "") list.append(h("div", { class: "ccEmpty" }, t.empty));
              for (const n of names) { const sv = st.servers[n]; list.append(h("button", { type: "button", class: "ccRow", "aria-current": st.selected === n ? "true" : null, title: stateText(sv), onClick: () => select(n) }, h("span", { class: "dot", "data-state": sv.state }), h("span", { class: "main" }, h("b", null, n), h("small", null, sv.command ? [sv.command, ...(sv.args || [])].join(" ") : sv.url || "")), sv.enabled === false ? h("span", { class: "tag", "data-tone": "outline" }, t.off) : null)); }
              if (st.selected === "") list.append(h("button", { type: "button", class: "ccRow", "aria-current": "true" }, h("span", { class: "dot" }), h("span", { class: "main" }, h("b", null, st.draft.name || t.newServer))));
            }
            const side = h("aside", { class: "ccSide" }, h("div", { class: "blockHead" }, h("span", null, t.servers), h("button", { type: "button", class: "ccLink", onClick: () => select("") }, "＋ " + t.add)), list);
            const main = h("div", { class: "ccMain" }, st.draft ? editor() : h("div", { class: "ccEmpty" }, t.none));
            root.replaceChildren(head, noticeBox, settings, h("div", { class: "ccBody", style: { marginTop: "10px" } }, side, main));
          }
          render(); load();
          return () => { alive = false; };
        }

        // ============================================================ Skills page
        function skillsPage(el) {
          let alive = true;
          const st = { skills: null, selected: null, detail: null, file: null, fileText: null, conflicts: null, pending: null };
          const root = h("div", { class: "ccPage" }); el.replaceChildren(root);
          const noticeBox = h("div");
          const fileInput = h("input", { type: "file", accept: ".zip,.skill", hidden: true, onChange: async (e) => { const f = e.target.files && e.target.files[0]; e.target.value = ""; if (f) await install(f, "ask"); } });
          async function load() { try { const d = await call("/skills"); if (!alive) return; st.skills = d.skills; if (st.selected && !st.skills.find((s) => s.name === st.selected)) st.selected = null; if (!st.selected && st.skills.length) st.selected = st.skills[0].name; render(); await loadDetail(); } catch (err) { notice(noticeBox, "error", err.message); render(); } }
          async function loadDetail() {
            if (!st.selected) { st.detail = null; render(); return; }
            const name = st.selected;
            try { const d = await call(`/skills/detail?name=${encodeURIComponent(name)}`); if (!alive || st.selected !== name) return; st.detail = d; st.file = d.entryFile; render(); await loadFile(); }
            catch (err) { notice(noticeBox, "error", err.message); }
          }
          async function loadFile() {
            if (!st.detail || !st.file) return;
            const key = `${st.selected}/${st.file}`;
            try { const d = await call(`/skills/file?name=${encodeURIComponent(st.selected)}&file=${encodeURIComponent(st.file)}`); if (!alive || `${st.selected}/${st.file}` !== key) return; st.fileText = d; }
            catch (err) { st.fileText = { error: err.message }; }
            render();
          }
          async function install(file, policy) {
            if (file.size > 32 * 1024 * 1024) { notice(noticeBox, "error", t.zipLimit); return; }
            const data = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(",")[1] || ""); r.onerror = () => reject(r.error); r.readAsDataURL(file); });
            try {
              const r = await call("/skills/install", { method: "POST", body: JSON.stringify({ data, policy }) });
              if (r.conflicts && r.conflicts.length) { st.conflicts = r.conflicts; st.pending = file; render(); return; }
              st.conflicts = null; st.pending = null; notice(noticeBox, "ok", t.installed(r.installed.length, r.skipped.length)); if (r.installed.length) st.selected = r.installed[0]; await load();
            } catch (err) { notice(noticeBox, "error", err.message); }
          }
          async function toggle(name, enabled) { try { const d = await call("/skills", { method: "POST", body: JSON.stringify({ name, enabled }) }); st.skills = d.skills; render(); await loadDetail(); } catch (err) { notice(noticeBox, "error", err.message); } }
          async function remove(name) { if (!(await confirmBox(t.del, t.skillDeleteConfirm(name), t.del))) return; try { const d = await call(`/skills?name=${encodeURIComponent(name)}`, { method: "DELETE" }); st.skills = d.skills; st.selected = null; st.detail = null; await load(); } catch (err) { notice(noticeBox, "error", err.message); } }
          const openFolder = async (name) => { try { await call(`/skills/open${name ? `?name=${encodeURIComponent(name)}` : ""}`, { method: "POST", body: "{}" }); } catch (err) { notice(noticeBox, "error", err.message); } };
          function render() {
            if (!alive) return;
            const tools = h("div", { class: "headTools" }, h("button", { type: "button", class: "iconButton", title: t.refresh, onClick: load }, ico("refresh")), h("button", { type: "button", class: "btn outline sm", onClick: () => openFolder(null) }, t.open), h("button", { type: "button", class: "btn primary sm", onClick: () => fileInput.click() }, ico("plus", "ico"), h("span", null, t.install)));
            const head = h("div", { class: "pageHead" }, h("div", null, h("h1", { class: "pageTitle" }, t.skills), h("p", { class: "pageIntro" }, t.skillsIntro)), tools);
            const parts = [head, noticeBox, fileInput];
            if (st.conflicts) parts.push(h("div", { class: "ccNotice", "data-kind": "info", style: { display: "block" } }, h("div", null, h("b", null, t.conflicts + ": "), st.conflicts.join(", ")), h("div", { style: { margin: "6px 0" } }, t.replaceHint), h("div", { style: { display: "flex", gap: "6px" } }, h("button", { type: "button", class: "btn primary sm", onClick: () => install(st.pending, "replace") }, t.replace), h("button", { type: "button", class: "btn outline sm", onClick: () => install(st.pending, "skip") }, t.skip), h("button", { type: "button", class: "btn outline sm", onClick: () => { st.conflicts = null; st.pending = null; render(); } }, t.cancel))));
            const list = h("div", { class: "list" });
            if (!st.skills) list.append(h("div", { class: "ccEmpty" }, t.loading));
            else if (!st.skills.length) list.append(h("div", { class: "ccEmpty" }, t.skillsEmpty));
            for (const s of st.skills || []) list.append(h("button", { type: "button", class: "ccRow", "aria-current": st.selected === s.name ? "true" : null, onClick: () => { st.selected = s.name; st.detail = null; st.fileText = null; render(); loadDetail(); } }, h("span", { class: "main" }, h("b", null, s.name), h("small", null, `${s.version ? s.version + " · " : ""}${s.enabled ? t.skillEnabled : t.off}`), s.description ? h("small", { style: { whiteSpace: "normal", display: "-webkit-box", WebkitLineClamp: "2", WebkitBoxOrient: "vertical" } }, s.description) : null)));
            const side = h("aside", { class: "ccSide" }, h("div", { class: "blockHead" }, h("span", null, t.skills)), list);
            let main;
            if (!st.selected) main = h("div", { class: "ccEmpty" }, st.skills && st.skills.length ? t.selectSkill : t.skillsEmpty);
            else if (!st.detail) main = h("div", { class: "ccEmpty" }, t.loading);
            else {
              const d = st.detail;
              const tree = h("div", { class: "tree" }, d.files.map((f) => h("button", { type: "button", "aria-current": st.file === f.path ? "true" : null, title: `${f.path} · ${f.size} B`, onClick: () => { st.file = f.path; st.fileText = null; render(); loadFile(); } }, f.path)), d.truncated ? h("div", { class: "ccEmpty" }, t.truncated) : null);
              const preview = st.fileText ? (st.fileText.error ? h("div", { class: "ccEmpty" }, st.fileText.error) : h("div", null, h("div", { style: { font: "12px var(--mono)", color: "var(--label-tertiary)", marginBottom: "6px" } }, st.file), h("pre", null, st.fileText.text), st.fileText.truncated ? h("div", { class: "ccEmpty" }, t.truncated) : null)) : h("div", { class: "ccEmpty" }, t.loading);
              main = h("div", { class: "ccCard ccSkillBody" },
                h("div", { class: "cardHead" }, h("h2", null, d.name), h("span", { style: { fontSize: "12px", color: "var(--label-secondary)" } }, t.enabled), h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(d.enabled), onClick: () => toggle(d.name, !d.enabled) }, h("span", { class: "knob" })), h("button", { type: "button", class: "btn outline sm", onClick: () => openFolder(d.name) }, t.open), h("button", { type: "button", class: "btn outline sm", style: { color: "var(--error)" }, onClick: () => remove(d.name) }, t.del)),
                d.description ? h("div", { class: "desc" }, d.description) : null,
                h("details", { class: "ccDetails" }, h("summary", null, t.metadata), h("pre", { style: { marginTop: "6px" } }, `${d.path}\n${JSON.stringify(d.frontmatter, null, 2)}`)),
                h("div", null, h("div", { style: { fontSize: "12px", color: "var(--label-secondary)", marginBottom: "6px" } }, t.files), h("div", { class: "filesWrap" }, tree, preview)));
            }
            parts.push(h("div", { class: "ccBody" }, side, h("div", { class: "ccMain" }, main)));
            root.replaceChildren(...parts);
          }
          render(); load();
          return () => { alive = false; };
        }

        // ============================================================ Environment settings section
        function environmentSection(el) {
          let alive = true; let status = null; let timer = null; let busy = false;
          const root = h("div"); el.replaceChildren(root);
          async function poll() {
            try { status = await call("/environment"); } catch (err) { status = { state: "error", error: err.message, supported: true }; }
            if (!alive) return; render();
            clearTimeout(timer);
            timer = setTimeout(poll, ["downloading", "verifying", "installing"].includes(status.state) ? 1500 : 10000);
          }
          async function install() { busy = true; render(); try { status = await call("/environment", { method: "POST", body: "{}" }); } catch (err) { status = { ...(status || {}), error: err.message }; } busy = false; poll(); }
          function render() {
            if (!alive) return;
            const s = status; const working = s && ["downloading", "verifying", "installing"].includes(s.state);
            const pill = h("span", { class: "tag", "data-tone": !s ? "quiet" : s.state === "ready" ? "success" : s.state === "error" ? "danger" : working ? "info" : "outline" }, s ? t.states[s.state] || s.state : t.loading);
            const dl = s ? h("dl", null, h("dt", null, t.version), h("dd", null, s.version || "—"), h("dt", null, t.available), h("dd", null, s.recommendedVersion || "—"), h("dt", null, t.platform), h("dd", null, s.target || "—"), h("dt", null, t.path), h("dd", null, s.path || "—"), h("dt", null, t.data), h("dd", null, s.dataDirectory || "—")) : null;
            const progress = working ? h("progress", { max: 100, value: s.state === "downloading" && s.progress != null ? s.progress : null }) : null;
            const button = h("button", { type: "button", class: "btn primary sm", disabled: busy || working || (s && s.supported === false), onClick: install }, working ? t.working : s && s.ready ? t.repair : t.installBtn);
            root.replaceChildren(
              h("p", { class: "sectionIntro" }, t.envIntro),
              h("div", { class: "ccEnvCard" },
                h("div", { class: "head" }, h("b", null, "bun / bunx"), pill, h("button", { type: "button", class: "btn outline sm", disabled: busy || working, onClick: poll }, t.check)),
                h("div", { class: "meta" }, t.envDesc), dl, progress,
                s && s.supported === false ? h("div", { class: "meta" }, t.unsupported) : null,
                h("div", { class: "meta" }, t.firstRun),
                h("div", { class: "row" }, h("a", { class: "ccLink", href: "https://bun.sh/docs", target: "_blank", rel: "noopener" }, t.docs), h("span", { class: "spacer" }), button),
                s && s.error ? h("div", { class: "err" }, s.error) : null));
          }
          render(); poll();
          return () => { alive = false; clearTimeout(timer); };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "mcp", label: t.mcp, icon: "plug", description: t.mcpIntro, order: 55 });
        ctx.slots.register({ slot: "main", key: "mcp", label: t.mcp }, mcpPage);
        ctx.slots.register({ slot: "sidebar.panellist", id: "skills", label: t.skills, icon: "sparkle", description: t.skillsIntro, order: 56 });
        ctx.slots.register({ slot: "main", key: "skills", label: t.skills }, skillsPage);
        ctx.slots.register({ slot: "settings.sections", key: "environment", label: t.envTitle, icon: "terminal", order: 120 }, environmentSection);
      },
    };
  },
});
