// Browser module of the `subscriptions` entry: the sidebar "AI subscriptions" entry and its page (providers, account
// login with manual callback fallback, models / tools / usage tabs, generated media previews in tool rows).
window.__PyhModules__.load({
  id: "subscriptions",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: { title: "AI 订阅", intro: "用 Codex、ChatGPT、Google Antigravity 与 Grok 的订阅账号作为模型来源与工具：在浏览器完成授权后，模型出现在对话的模型选择器中。", accounts: "订阅账号", add: "添加账号", connect: "连接", connected: "已连接", disconnected: "未连接", waiting: "等待授权", defaultTag: "默认账号", setDefault: "设为默认", disconnect: "断开连接", cancel: "取消", confirm: "确认断开", disconnectHint: (a) => `断开 ${a} 并移除本地登录凭证？`, reconnect: "重新登录", planDisabled: "未授权使用套餐", openAuth: "打开授权页面", authHint: "请在浏览器中完成账号授权。若新窗口未打开，点击下方链接继续。", manualOnlyHint: "本机回调端口不可用，已切换为手动登录。请打开授权页面并完成登录；跳转到本机回调地址后，即使浏览器显示无法访问，也请复制地址栏中的完整 URL，粘贴到下方并提交。", manual: "手动提交回调地址", manualHint: "无法自动回到应用时，将浏览器地址栏中的完整回调 URL 粘贴到这里。", submit: "提交", models: "模型", tools: "工具", usage: "用量", refresh: "刷新", loading: "加载中…", retry: "重试", modelHint: "勾选的模型显示在对话中；同类账号共用设置。", contextHint: "支持整数、256K、1M（十进制）。Enter 保存，留空恢复默认。", save: "保存", resetContext: "恢复默认", contextDefault: (v) => `默认 ${v}`, contextMax: (v) => `上限 ${v}`, contextEffective: (v) => `实际生效 ${v}`, contextInvalid: "请输入正整数，或使用 256K、1M 等写法。", contextTooLarge: (m) => `不能超过目录提供的上限 ${m}。`, search: "搜索模型名称或 ID", autoModels: "自动显示所有模型", modelName: "模型", context: "上下文", reasoning: "默认推理强度", providerDefault: "跟随提供方", noModels: "暂无可用模型，请连接账号或刷新模型目录。", noMatches: "没有匹配的模型。", unavailable: "暂时无法读取该账号的模型目录，请稍后刷新。", saved: "设置已保存", toolPolicy: "工具列表按会话创建时的开关设置生成；搜索关闭后也会立即阻止已有会话调用。实际可用性取决于账号权限与剩余额度。", enabled: "已启用", disabled: "已关闭", usageHint: "当前账号的订阅用量。", chatGptUsageHint: "与 Codex / ChatGPT Work 共享套餐额度，应用上限在 ChatGPT 中管理。", manageUsage: "管理用量", unknownUsage: "尚无用量数据", unsupportedUsage: "提供方暂未返回可用的用量窗口。", session: "短期额度", weekly: "每周额度", other: "其他额度", used: "已使用", resets: "重置时间", plan: "订阅方案", unknown: "未知", emptyHint: "在浏览器中完成授权后，可用模型会自动出现在对话的模型选择器中。", chatGptConsentHint: "登录后需授权使用套餐额度。凭据保存在本机；本应用不会获得你的 ChatGPT 对话或记忆。", notConnected: "未连接", refreshRoutes: "刷新模型目录",
        providers: { codex: { name: "Codex", vendor: "OpenAI", intro: "使用 Codex 订阅模型、联网搜索与图像生成。", empty: "连接 Codex 账号", connect: "连接 Codex", callback: "http://localhost:1455/auth/callback?…" }, chatgpt: { name: "ChatGPT", vendor: "OpenAI", intro: "授权本应用使用 ChatGPT 套餐，支持对话与本地工具调用。", empty: "连接 ChatGPT 账号", connect: "使用 ChatGPT 继续", callback: "http://127.0.0.1:1455/auth/callback?…" }, antigravity: { name: "Antigravity", vendor: "Google", intro: "Google Antigravity 订阅，支持账号模型目录、推理强度、上下文配置和用量查询。", empty: "连接你的 Google Antigravity 账号", connect: "连接 Google Antigravity", callback: "http://localhost:51121/oauth-callback?…" }, grok: { name: "Grok", vendor: "xAI", intro: "xAI Grok 订阅，支持账号模型目录、推理强度、上下文配置、用量查询与 X 搜索。", empty: "连接你的 Grok 账号", connect: "连接 Grok", callback: "http://127.0.0.1:56121/callback?…" } },
        toolCards: { "codex.web_search": ["Codex Web Search", "网页与图片搜索、天气、行情和赛事查询。", "codex_web_search"], "codex.image_generate": ["Codex 图像生成与编辑", "支持透明背景与本地参考图编辑。", "codex_image_generate"], "antigravity.web_search": ["Antigravity Web Search", "Google 网页搜索，包含摘要与来源。", "antigravity_web_search"], "antigravity.image_generate": ["Antigravity 图像生成与编辑", "Gemini 3.1 Flash Image，支持生成与编辑。", "antigravity_image_generate"], "grok.image_generate": ["Grok 图像生成与编辑", "grok-imagine-image-2.0，支持生成与参考图编辑。", "grok_image_generate"], "grok.video_generate": ["Grok 视频生成", "grok-imagine-video-1.5，1–15 秒短视频，支持图生视频。", "grok_video_generate"], "grok.x_search": ["Grok X 搜索", "xAI 托管的 X（Twitter）帖子、账号与话题搜索，返回回答与来源。", "grok_x_search"] } },
      en: { title: "AI subscriptions", intro: "Use Codex, ChatGPT, Google Antigravity and Grok subscription accounts as model sources and tools: authorize in the browser and the models appear in the conversation model picker.", accounts: "Subscription accounts", add: "Add account", connect: "Connect", connected: "Connected", disconnected: "Not connected", waiting: "Waiting for authorization", defaultTag: "Default account", setDefault: "Set as default", disconnect: "Disconnect", cancel: "Cancel", confirm: "Disconnect account", disconnectHint: (a) => `Disconnect ${a} and remove its local credentials?`, reconnect: "Sign in again", planDisabled: "Plan usage disabled", openAuth: "Open authorization page", authHint: "Complete account authorization in your browser. If no window opened, use the link below.", manualOnlyHint: "The local callback ports are unavailable. Open the authorization page and sign in. After redirecting to the local callback, copy the full address-bar URL below and submit it, even if the browser says the page cannot be reached.", manual: "Submit callback URL manually", manualHint: "If the automatic callback fails, paste the full callback URL from your browser address bar.", submit: "Submit", models: "Models", tools: "Tools", usage: "Usage", refresh: "Refresh", loading: "Loading…", retry: "Retry", modelHint: "Selected models appear in conversations; shared across accounts of this provider.", contextHint: "Use integers, 256K or 1M (decimal). Enter saves; blank restores the default.", save: "Save", resetContext: "Reset to default", contextDefault: (v) => `Default ${v}`, contextMax: (v) => `Max ${v}`, contextEffective: (v) => `Effective ${v}`, contextInvalid: "Enter a positive whole token count, or use a value such as 256K or 1M.", contextTooLarge: (m) => `Cannot exceed the catalog limit of ${m}.`, search: "Search model name or ID", autoModels: "Show all models automatically", modelName: "Model", context: "Context", reasoning: "Default reasoning effort", providerDefault: "Follow provider", noModels: "No models available. Connect an account or refresh the catalog.", noMatches: "No matching models.", unavailable: "This account’s model catalog is temporarily unavailable. Try refreshing later.", saved: "Settings saved", toolPolicy: "Tool lists use the settings at conversation creation. Disabling search also blocks calls in existing conversations immediately. Access depends on account entitlements and remaining quota.", enabled: "Enabled", disabled: "Disabled", usageHint: "Subscription usage for the selected account.", chatGptUsageHint: "Shares plan usage with Codex / ChatGPT Work. Manage app limits in ChatGPT.", manageUsage: "Manage usage", unknownUsage: "No usage data yet", unsupportedUsage: "The provider has not returned any usage windows.", session: "Short-term window", weekly: "Weekly window", other: "Other window", used: "Used", resets: "Resets", plan: "Plan", unknown: "Unknown", emptyHint: "Authorize in your browser. Available models will appear in the conversation model picker.", chatGptConsentHint: "Allow plan usage when signing in. Credentials stay on this host; this app receives no access to your ChatGPT conversations or memories.", notConnected: "Not connected", refreshRoutes: "Refresh model catalog",
        providers: { codex: { name: "Codex", vendor: "OpenAI", intro: "Use Codex subscription models, web search and image generation.", empty: "Connect your Codex account", connect: "Connect Codex", callback: "http://localhost:1455/auth/callback?…" }, chatgpt: { name: "ChatGPT", vendor: "OpenAI", intro: "Authorize this app to use your ChatGPT plan for conversations and local tools.", empty: "Connect your ChatGPT account", connect: "Continue with ChatGPT", callback: "http://127.0.0.1:1455/auth/callback?…" }, antigravity: { name: "Antigravity", vendor: "Google", intro: "Google Antigravity subscription with account model catalogs, reasoning effort, context settings and usage.", empty: "Connect your Google Antigravity account", connect: "Connect Google Antigravity", callback: "http://localhost:51121/oauth-callback?…" }, grok: { name: "Grok", vendor: "xAI", intro: "xAI Grok subscription with account model catalogs, reasoning effort, context settings, usage and X search.", empty: "Connect your Grok account", connect: "Connect Grok", callback: "http://127.0.0.1:56121/callback?…" } },
        toolCards: { "codex.web_search": ["Codex Web Search", "Web and image search, weather, finance and sports queries.", "codex_web_search"], "codex.image_generate": ["Codex image generation and editing", "Transparent backgrounds and local reference-image editing.", "codex_image_generate"], "antigravity.web_search": ["Antigravity Web Search", "Google web search with summaries and sources.", "antigravity_web_search"], "antigravity.image_generate": ["Antigravity image generation and editing", "Image generation and editing with Gemini 3.1 Flash Image.", "antigravity_image_generate"], "grok.image_generate": ["Grok image generation and editing", "grok-imagine-image-2.0 generation and reference-image editing.", "grok_image_generate"], "grok.video_generate": ["Grok video generation", "grok-imagine-video-1.5 clips of 1–15 seconds, with image-to-video.", "grok_video_generate"], "grok.x_search": ["Grok X Search", "Hosted search of X (Twitter) posts, profiles and threads, with an answer and sources.", "grok_x_search"] } },
    };
    const LOGOS = { codex: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M16.0005 13.5992C16.4972 13.5995 16.9007 14.0029 16.9009 14.4996C16.9009 14.9965 16.4974 15.3997 16.0005 15.4H13.0005C12.5035 15.4 12.1002 14.9967 12.1002 14.4996C12.1004 14.0027 12.5036 13.5992 13.0005 13.5992H16.0005Z" fill="currentColor"/><path d="M8.03765 8.72811C8.46377 8.47284 9.01638 8.61074 9.27203 9.03671L10.6177 11.2789C10.8836 11.7221 10.8834 12.277 10.6177 12.7203L9.27203 14.9625C9.01633 15.3887 8.46385 15.5267 8.03765 15.2711C7.61143 15.0153 7.47333 14.4629 7.72906 14.0367L8.95074 11.9996L7.72906 9.96249C7.47341 9.53628 7.61146 8.98382 8.03765 8.72811Z" fill="currentColor"/><path fill-rule="evenodd" clip-rule="evenodd" d="M9.3316 2.03768C11.1644 1.54688 13.0268 2.04668 14.356 3.20174C16.0859 2.86512 17.9511 3.36418 19.2935 4.70663C20.6356 6.04882 21.1326 7.91288 20.7964 9.64217C21.9527 10.9716 22.4534 12.8349 21.9625 14.6685C21.4711 16.5025 20.1051 17.8657 18.439 18.439C17.8658 20.1047 16.503 21.47 14.6695 21.9615C12.8356 22.4528 10.9727 21.9519 9.64312 20.7955C7.91371 21.1319 6.04993 20.635 4.70757 19.2926C3.36558 17.9505 2.86659 16.0866 3.20269 14.357C2.04693 13.0273 1.54757 11.1638 2.03863 9.33065C2.52997 7.49759 3.89436 6.13282 5.56011 5.55917C6.13382 3.8935 7.49837 2.52891 9.3316 2.03768ZM13.2623 4.63534C12.3606 3.80149 11.067 3.4361 9.79742 3.77596C8.52745 4.11626 7.58924 5.0796 7.22515 6.25253C7.08145 6.71575 6.71753 7.07928 6.25445 7.22323C5.08133 7.58702 4.11844 8.52622 3.77789 9.79647C3.43759 11.0667 3.80148 12.3606 4.63531 13.2623C4.96467 13.6184 5.09776 14.1154 4.99078 14.5885C4.71939 15.7864 5.05109 17.0891 5.98101 18.0191C6.91085 18.949 8.21345 19.2801 9.41168 19.0084L9.58941 18.9791C9.94695 18.9432 10.3065 19.0397 10.5982 19.2496L10.7378 19.3639L10.9117 19.5142C11.8015 20.2407 13.0127 20.5413 14.2037 20.2223C15.4733 19.8818 16.4111 18.9191 16.775 17.7457C16.9189 17.2824 17.2832 16.9186 17.7466 16.775L17.9634 16.6998C19.0376 16.2923 19.9051 15.3936 20.2242 14.2027C20.5641 12.9328 20.1989 11.6385 19.3648 10.7369C19.0353 10.3806 18.9021 9.88399 19.0093 9.41073L19.0533 9.18514C19.2372 8.0514 18.8917 6.85176 18.0201 5.98006C17.0901 5.05003 15.7865 4.71826 14.5884 4.98983C14.1153 5.09712 13.6186 4.96467 13.2623 4.63534Z" fill="currentColor"/></svg>', chatgpt: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"/></svg>', grok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4.5 4.5l15 15M19.5 4.5l-6.2 6.2M4.5 19.5l6.2-6.2"/></svg>' };
    const logo = (id, cls) => { const el = h("span", { class: cls }); if (LOGOS[id]) { const tpl = document.createElement("template"); tpl.innerHTML = LOGOS[id]; el.append(tpl.content.firstChild); } else el.textContent = "G"; return el; };
    const PROVIDERS = ["codex", "chatgpt", "antigravity", "grok"];
    const AUTH_HOSTS = { codex: (u) => u.origin === "https://auth.openai.com" && u.pathname === "/oauth/authorize", chatgpt: (u) => u.origin === "https://auth.openai.com" && u.pathname === "/api/accounts/authorize", grok: (u) => u.protocol === "https:" && (u.hostname === "x.ai" || u.hostname.endsWith(".x.ai")), antigravity: (u) => u.href.startsWith("https://accounts.google.com/o/oauth2/v2/auth") };
    async function call(path, opts) {
      const res = await fetch("/api/subscriptions" + path, { headers: { "content-type": "application/json" }, ...(opts || {}) });
      if (!res.ok) { let detail = `HTTP ${res.status}`; try { const d = (await res.json()).detail; if (typeof d === "string") detail = d; } catch { /* no body */ } throw new Error(detail); }
      return res.json();
    }
    const fmtTokens = (n) => (n == null ? "" : n % 1000000 === 0 ? `${n / 1000000}M` : n % 1000 === 0 ? `${n / 1000}K` : String(n));
    const parseTokens = (text) => { const m = String(text).trim().match(/^(\d+(?:\.\d+)?)\s*([kKmM])?$/); if (!m) return null; const v = Number(m[1]) * (m[2] ? (m[2].toLowerCase() === "k" ? 1000 : 1000000) : 1); return Number.isInteger(v) && v > 0 ? v : null; };
    const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none"><symbol id="i-card" viewBox="0 0 16 16"><rect x="2.25" y="3.5" width="11.5" height="9" rx="1.5"/><path d="M2.25 6.75h11.5M5 10h2.5M10.5 9.25v1.5M9.75 10h1.5"/></symbol></svg>`;

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        if (!document.getElementById("i-card")) document.body.insertAdjacentHTML("beforeend", sprite);
        const style = document.createElement("style");
        style.textContent = `
          .subPage { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0 24px 16px; }
          .subPage .pageHead { flex: none; flex-wrap: wrap; padding-bottom: 10px; }
          .subNotice { margin: 0 0 10px; padding: 7px 12px; border-radius: 8px; font-size: 12px; display: flex; align-items: center; gap: 8px; flex: none; }
          .subNotice span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
          .subNotice[data-kind="ok"] { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }
          .subNotice[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .subBody { flex: 1; min-height: 0; display: flex; gap: 12px; }
          .subSide { width: 220px; flex: none; display: flex; flex-direction: column; gap: 6px; min-height: 0; border-right: 0.5px solid var(--border-l2); padding-right: 12px; }
          .subSide .blockHead { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: var(--label-secondary); padding: 2px 0; }
          .subSide .blockHead span { flex: 1; }
          .subProv { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; padding: 7px 8px; border: none; border-radius: 8px; background: transparent; color: var(--label-primary); }
          .subProv:hover { background: var(--hover); } .subProv[aria-current="true"] { background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .subProv .logo { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; font-weight: 600; font-size: 13px; background: var(--layer-3, var(--layer-2)); color: var(--label-secondary); flex: none; }
          .subProv .logo svg { width: 18px; height: 18px; } .subEmpty .logo svg { width: 28px; height: 28px; }
          .subProv .main b { display: block; font-size: 13px; font-weight: 500; } .subProv .main small { font-size: 11px; color: var(--label-tertiary); }
          .subAccts { display: flex; flex-direction: column; gap: 2px; }
          .subAcct { display: block; width: 100%; text-align: left; padding: 6px 8px; border: none; border-radius: 8px; background: transparent; color: var(--label-primary); }
          .subAcct:hover { background: var(--hover); } .subAcct[aria-current="true"] { background: color-mix(in srgb, var(--info) 12%, transparent); }
          .subAcct b { display: block; font-size: 12.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .subAcct small { font-size: 11px; color: var(--label-tertiary); }
          .subSide .intro { font-size: 11px; color: var(--label-tertiary); padding: 6px 8px; margin-top: auto; }
          .subLink { background: none; border: none; padding: 0; font-size: 12px; color: var(--info); cursor: pointer; } .subLink:disabled { opacity: .5; cursor: default; }
          .subMain { flex: 1; min-width: 0; min-height: 0; overflow: auto; }
          .subCard { padding: 16px 18px; border-radius: 12px; background: var(--layer-1); box-shadow: inset 0 0 0 0.5px var(--border-l2); display: flex; flex-direction: column; gap: 12px; }
          .subEmpty { padding: 40px 20px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; }
          .subEmpty .logo { width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; font-weight: 600; font-size: 20px; background: var(--layer-2); color: var(--label-secondary); }
          .subEmpty h2 { margin: 0; font-size: 16px; font-weight: 500; } .subEmpty p { margin: 0; font-size: 12.5px; color: var(--label-tertiary); max-width: 460px; }
          .subAcctHead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
          .subAcctHead h2 { margin: 0; font-size: 15px; font-weight: 500; } .subAcctHead .spacer { flex: 1; }
          .subAcctHead .ok { font-size: 12px; color: var(--success); } .subAcctHead .meta { font-size: 12px; color: var(--label-tertiary); }
          .subTabs { display: flex; gap: 2px; border-bottom: 0.5px solid var(--border-l2); }
          .subTabs button { padding: 6px 12px; margin-bottom: -1px; border: none; border-bottom: 2px solid transparent; background: transparent; font-size: 13px; color: var(--label-secondary); }
          .subTabs button[aria-selected="true"] { color: var(--label-primary); font-weight: 500; border-bottom-color: var(--info); }
          .subToolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .subToolbar .input { width: 220px; height: 28px; font-size: 12px; }
          .subHint { font-size: 11px; color: var(--label-tertiary); }
          .subTableWrap { border-radius: 10px; box-shadow: inset 0 0 0 0.5px var(--border-l2); overflow: auto; max-height: 55vh; }
          .subTable { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12.5px; }
          .subTable th { position: sticky; top: 0; text-align: left; padding: 8px 10px; background: var(--layer-2); font-weight: 500; color: var(--label-secondary); border-bottom: 0.5px solid var(--border-l2); }
          .subTable td { padding: 7px 10px; border-bottom: 0.5px solid var(--border-l2); vertical-align: top; }
          .subTable td .mid { display: block; font: 11px var(--mono); color: var(--label-tertiary); }
          .subTable td.ctx .input { width: 120px; height: 26px; font-size: 12px; } .subTable td.ctx small { display: block; font-size: 11px; color: var(--label-tertiary); margin-top: 3px; }
          .subTable td.ctx .err { font-size: 11px; color: var(--error); }
          .subToolCard { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 10px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .subToolCard .main { flex: 1; min-width: 0; } .subToolCard .main b { display: block; font-size: 13px; font-weight: 500; } .subToolCard .main small { font-size: 12px; color: var(--label-tertiary); } .subToolCard code { font-size: 11px; color: var(--label-tertiary); }
          .subUsage { padding: 12px 14px; border-radius: 10px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .subUsage .row { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; } .subUsage progress { width: 100%; height: 6px; } .subUsage small { font-size: 11px; color: var(--label-tertiary); }
          .subPending { padding: 14px 16px; border-radius: 10px; background: color-mix(in srgb, var(--info) 8%, transparent); display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; }
          .subPending form { display: flex; gap: 6px; } .subPending form .input { flex: 1; }
          .subMediaPreview img, .subMediaPreview video { max-width: 100%; max-height: 360px; border-radius: 8px; display: block; margin: 6px 0; }
          @container (max-width: 760px) { .subBody { flex-direction: column; } .subSide { width: auto; border-right: none; padding-right: 0; } }
        `;
        document.head.appendChild(style);
        ctx.effect(() => style.remove());

        function modal(inner) {
          const el = h("div", { class: "modal" }); el.innerHTML = `<div class="modalCard narrow" role="dialog" aria-modal="true">${inner}</div>`;
          document.body.appendChild(el);
          const close = () => { el.remove(); document.removeEventListener("keydown", onKey, true); };
          const onKey = (e) => { if (e.key === "Escape") close(); };
          document.addEventListener("keydown", onKey, true);
          el.addEventListener("mousedown", (e) => { if (e.target === el) close(); });
          return { el, close };
        }

        // ------------------------------------------------------------ page
        function page(el) {
          let alive = true;
          const st = { status: null, provider: "codex", account: null, tab: "models", catalog: null, usage: null, notice: null, filter: "", busy: false, pollTimer: null, saved: false };
          const root = h("div", { class: "subPage" }); el.replaceChildren(root);
          const P = (id) => t.providers[id];
          const setNotice = (kind, text) => { st.notice = kind ? { kind, text } : null; render(); };
          const fail = (err) => setNotice("error", err.message || String(err));
          const provStatus = () => (st.status && st.status.providers[st.provider]) || { busy: false, accounts: [] };
          const account = () => provStatus().accounts.find((a) => a.key === st.account) || null;

          async function loadStatus(silent) {
            try { st.status = await call("/status"); if (!alive) return; const ps = provStatus(); if (!st.account || !ps.accounts.find((a) => a.key === st.account)) st.account = ps.accounts[0] ? ps.accounts[0].key : null; if (!silent) st.notice = null; render(); }
            catch (err) { if (!silent) fail(err); }
            schedulePoll();
          }
          function schedulePoll() { clearTimeout(st.pollTimer); if (!alive) return; if (st.status && Object.values(st.status.providers).some((p) => p.busy)) st.pollTimer = setTimeout(() => loadStatus(true), 1500); }
          async function loadCatalog(force) {
            st.catalog = null; render();
            try { const cat = await call(`/provider-settings?provider=${st.provider}${force ? "&force=true" : ""}`); if (!alive || cat.provider !== st.provider) return; st.catalog = cat; render(); }
            catch (err) { fail(err); }
          }
          async function loadUsage(force) {
            if (!st.account) return;
            st.usage = null; render();
            try { const u = await call("/usage", { method: "POST", body: JSON.stringify({ provider: st.provider, account: st.account, force: !!force }) }); if (!alive) return; st.usage = u; render(); }
            catch (err) { st.usage = { error: err.message }; render(); }
          }
          function selectProvider(id) { st.provider = id; st.account = null; st.catalog = null; st.usage = null; st.tab = "models"; const ps = provStatus(); st.account = ps.accounts[0] ? ps.accounts[0].key : null; render(); loadCatalog(false); }

          async function login(accountKey) {
            setNotice(null);
            try {
              const r = await call("/login", { method: "POST", body: JSON.stringify({ provider: st.provider, account: accountKey || undefined }) });
              let ok = false; try { ok = AUTH_HOSTS[st.provider](new URL(r.authorizeUrl)) && !new URL(r.authorizeUrl).username; } catch { ok = false; }
              if (!ok) throw new Error(`Invalid ${P(st.provider).name} authorization URL`);
              window.open(r.authorizeUrl, "_blank", "noopener,noreferrer");
              await loadStatus(true);
            } catch (err) { fail(err); }
          }
          async function cancelLogin() { try { await call("/cancel", { method: "POST", body: JSON.stringify({ provider: st.provider }) }); } catch (err) { fail(err); } loadStatus(true); }
          async function submitManual(text) { try { await call("/manual", { method: "POST", body: JSON.stringify({ provider: st.provider, input: text }) }); setNotice("ok", t.submit); } catch (err) { fail(err); } loadStatus(true); }
          function disconnect(a) {
            const { el, close } = modal(`<div class="modalHead">${esc(t.disconnect)}</div><div class="modalBody"><p>${esc(t.disconnectHint(a.account || P(st.provider).name))}</p></div><div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button><button type="button" class="btn primary" data-yes style="background:var(--error)">${esc(t.confirm)}</button></div>`);
            el.querySelector("[data-no]").onclick = close;
            el.querySelector("[data-yes]").onclick = async () => { close(); try { await call("/logout", { method: "POST", body: JSON.stringify({ provider: st.provider, account: a.key }) }); st.account = null; await loadStatus(false); loadCatalog(false); } catch (err) { fail(err); } };
          }
          async function setDefault(a) { try { await call("/default", { method: "POST", body: JSON.stringify({ provider: st.provider, account: a.key }) }); await loadStatus(false); } catch (err) { fail(err); } }
          async function savePrefs(patch) {
            if (!st.catalog) return;
            const settings = { ...st.catalog.settings, ...patch };
            st.catalog.settings = settings; render();
            try { await call("/provider-settings", { method: "PUT", body: JSON.stringify({ provider: st.provider, settings }) }); st.saved = true; render(); setTimeout(() => { st.saved = false; render(); }, 1500); }
            catch (err) { fail(err); loadCatalog(false); }
          }

          // -------------------------------------------------------- side
          function side() {
            const ps = provStatus();
            const provs = PROVIDERS.map((id) => { const s = (st.status && st.status.providers[id]) || { accounts: [] }; return h("button", { type: "button", class: "subProv", "aria-current": st.provider === id ? "true" : null, disabled: ps.busy && st.provider !== id, onClick: () => selectProvider(id) }, logo(id, "logo"), h("span", { class: "main" }, h("b", null, P(id).name), h("small", null, `${P(id).vendor}${s.accounts.length ? ` · ${s.accounts.length}` : ""}`))); });
            const accts = h("div", { class: "subAccts" });
            if (!st.status) accts.append(h("div", { class: "subHint", style: { padding: "6px 8px" } }, t.loading));
            else if (!ps.accounts.length) accts.append(h("div", { class: "subHint", style: { padding: "6px 8px" } }, t.notConnected));
            for (const a of ps.accounts) accts.append(h("button", { type: "button", class: "subAcct", "aria-current": st.account === a.key ? "true" : null, onClick: () => { st.account = a.key; st.usage = null; render(); if (st.tab === "usage") loadUsage(false); } }, h("b", null, a.account || P(st.provider).name), h("small", null, a.connected === false ? t.disconnected : `${a.plan || P(st.provider).name}${a.isDefault ? ` · ${t.defaultTag}` : ""}`)));
            return h("aside", { class: "subSide" }, h("div", { class: "blockHead" }, h("span", null, t.accounts), h("button", { type: "button", class: "subLink", disabled: ps.busy, onClick: () => login(null) }, "＋ " + t.add)), h("div", null, provs), h("div", { class: "blockHead", style: { marginTop: "6px" } }, h("span", null, P(st.provider).name)), accts, h("div", { class: "intro" }, P(st.provider).intro));
          }

          // -------------------------------------------------------- main
          function pendingBox(ps) {
            const details = h("details", { open: ps.manualOnly ? "" : null }, h("summary", null, t.manual), h("div", { class: "subHint", style: { margin: "6px 0" } }, t.manualHint), h("form", { onSubmit: (e) => { e.preventDefault(); const v = e.target.querySelector("input").value.trim(); if (v) submitManual(v); } }, h("input", { class: "input mono", placeholder: P(st.provider).callback }), h("button", { type: "submit", class: "btn primary sm" }, t.submit)));
            return h("div", { class: "subPending" }, h("b", null, t.waiting), h("span", null, ps.manualOnly ? t.manualOnlyHint : t.authHint), h("div", { style: { display: "flex", gap: "8px" } }, h("button", { type: "button", class: "btn outline sm", onClick: cancelLogin }, t.cancel)), details);
          }
          function emptyState(a) {
            const p = P(st.provider);
            return h("div", { class: "subCard subEmpty" }, logo(st.provider, "logo"), h("h2", null, p.empty), h("p", null, st.provider === "chatgpt" ? t.chatGptConsentHint : t.emptyHint), h("button", { type: "button", class: "btn primary sm", onClick: () => login(a && a.connected === false ? a.key : null) }, p.connect));
          }
          function modelsTab() {
            const cat = st.catalog;
            if (!cat) return h("div", { class: "subHint" }, t.loading);
            const search = h("input", { class: "input", placeholder: t.search, value: st.filter, onInput: (e) => { st.filter = e.target.value; render(); } });
            const visible = cat.settings.visibleModels;
            const auto = h("label", { style: { display: "flex", alignItems: "center", gap: "6px", fontSize: "12px" } }, h("input", { type: "checkbox", checked: visible == null, onChange: (e) => savePrefs({ visibleModels: e.target.checked ? undefined : cat.models.map((m) => m.id) }) }), t.autoModels);
            const f = st.filter.toLowerCase();
            const rows = cat.models.filter((m) => !f || m.id.toLowerCase().includes(f) || m.name.toLowerCase().includes(f));
            const unavailable = cat.accounts.some((a) => a.unavailable);
            const table = h("table", { class: "subTable" }, h("thead", null, h("tr", null, h("th", null, t.modelName), h("th", null, t.context), h("th", null, t.reasoning))), h("tbody", null, rows.map((m) => {
              const checked = visible == null || visible.includes(m.id);
              const toggle = h("input", { type: "checkbox", checked, onChange: (e) => { const list = new Set(visible == null ? cat.models.map((x) => x.id) : visible); if (e.target.checked) list.add(m.id); else list.delete(m.id); savePrefs({ visibleModels: [...list] }); } });
              const configured = cat.settings.contextWindows[m.id];
              const ctxInput = h("input", { class: "input mono", placeholder: fmtTokens(m.defaultContextWindow) || "256K / 1M", value: configured ? fmtTokens(configured) : "" });
              const err = h("div", { class: "err" });
              ctxInput.onkeydown = (e) => {
                if (e.key === "Escape") { ctxInput.value = configured ? fmtTokens(configured) : ""; err.textContent = ""; return; }
                if (e.key !== "Enter") return; e.preventDefault();
                const raw = ctxInput.value.trim(); const windows = { ...cat.settings.contextWindows };
                if (!raw) { delete windows[m.id]; savePrefs({ contextWindows: windows }).then(() => loadCatalog(false)); return; }
                const v = parseTokens(raw); if (!v) { err.textContent = t.contextInvalid; return; }
                if (m.maxContextWindow && v > m.maxContextWindow) { err.textContent = t.contextTooLarge(fmtTokens(m.maxContextWindow)); return; }
                windows[m.id] = v; savePrefs({ contextWindows: windows }).then(() => loadCatalog(false));
              };
              const sub = [t.contextDefault(fmtTokens(m.defaultContextWindow))]; if (m.maxContextWindow) sub.push(t.contextMax(fmtTokens(m.maxContextWindow))); if (m.contextWindow !== m.defaultContextWindow) sub.push(t.contextEffective(fmtTokens(m.contextWindow)));
              const effort = m.efforts && m.efforts.length ? h("span", { class: "selectWrap" }, h("select", { class: "select", style: { height: "26px", fontSize: "12px", width: "auto", padding: "0 24px 0 8px" }, onChange: async (e) => { try { await call("/model-default", { method: "POST", body: JSON.stringify({ provider: st.provider, model: m.id, effort: e.target.value || undefined }) }); m.configured = e.target.value || undefined; st.saved = true; render(); setTimeout(() => { st.saved = false; render(); }, 1500); } catch (e2) { fail(e2); } } }, h("option", { value: "", selected: !m.configured }, t.providerDefault), m.efforts.map((ef) => h("option", { value: ef.id, selected: m.configured === ef.id }, ef.name))), ico("chev-down", "ico chev")) : "—";
              return h("tr", null, h("td", null, h("label", { style: { display: "flex", gap: "8px", alignItems: "flex-start" } }, toggle, h("span", null, m.name, h("span", { class: "mid" }, m.id)))), h("td", { class: "ctx" }, ctxInput, h("small", null, sub.join(" · ")), err), h("td", null, effort));
            })));
            return h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
              h("div", { class: "subToolbar" }, search, h("button", { type: "button", class: "btn outline sm", onClick: () => loadCatalog(true) }, t.refresh), auto, st.saved ? h("span", { class: "subHint", style: { color: "var(--success)" } }, t.saved) : null),
              h("div", { class: "subHint" }, `${t.modelHint} ${t.contextHint}`), unavailable ? h("div", { class: "subNotice", "data-kind": "error" }, h("span", null, t.unavailable)) : null,
              rows.length ? h("div", { class: "subTableWrap" }, table) : h("div", { class: "subHint", style: { padding: "20px", textAlign: "center" } }, cat.models.length ? t.noMatches : t.noModels));
          }
          function toolsTab() {
            const cat = st.catalog;
            if (!cat) return h("div", { class: "subHint" }, t.loading);
            return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } }, cat.tools.map((tool) => { const [title, hint, name] = t.toolCards[`${st.provider}.${tool}`] || [tool, "", tool]; const on = (cat.settings.tools || {})[tool] !== false; return h("div", { class: "subToolCard" }, h("div", { class: "main" }, h("b", null, title), h("small", null, hint), h("div", null, h("code", null, name))), h("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(on), onClick: () => savePrefs({ tools: { ...(cat.settings.tools || {}), [tool]: !on } }) }, h("span", { class: "knob" }))); }), h("div", { class: "subHint" }, t.toolPolicy));
          }
          function usageTab() {
            const u = st.usage;
            const parts = [h("div", { class: "subToolbar" }, h("span", { class: "subHint" }, st.provider === "chatgpt" ? t.chatGptUsageHint : t.usageHint), h("button", { type: "button", class: "btn outline sm", onClick: () => loadUsage(true) }, t.refresh), st.provider === "chatgpt" ? h("a", { class: "subLink", href: "https://chatgpt.com/settings/usage", target: "_blank", rel: "noopener" }, t.manageUsage) : null)];
            if (!u) parts.push(h("div", { class: "subHint" }, t.loading));
            else if (u.error) parts.push(h("div", { class: "subNotice", "data-kind": "error" }, h("span", null, u.error)));
            else {
              if (u.plan) parts.push(h("div", { class: "subHint" }, `${t.plan} · ${u.plan}`));
              if (!u.supported) parts.push(h("div", { class: "subHint" }, t.unsupportedUsage));
              else if (!(u.windows || []).length) parts.push(h("div", { class: "subHint" }, t.unknownUsage));
              for (const w of u.windows || []) parts.push(h("div", { class: "subUsage" }, h("div", { class: "row" }, h("b", null, `${t[w.kind] || w.kind}${w.scope ? ` · ${w.scope}` : ""}`), h("span", null, `${Math.round(w.usedPercent)}% ${t.used}`)), h("progress", { max: 100, value: Math.max(0, Math.min(100, w.usedPercent)) }), h("small", null, `${t.resets} · ${w.resetsAt ? new Date(w.resetsAt).toLocaleString() : t.unknown}`)));
            }
            return h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } }, parts);
          }
          function main() {
            const ps = provStatus(); const a = account();
            if (ps.busy) return h("div", { class: "subCard" }, pendingBox(ps));
            if (!a || a.connected === false) return emptyState(a);
            const head = h("div", { class: "subAcctHead" }, h("h2", null, a.account || P(st.provider).name), h("span", { class: a.planEnabled === false ? "meta" : "ok" }, a.planEnabled === false ? t.planDisabled : "● " + t.connected), h("span", { class: "meta" }, `· ${a.plan || P(st.provider).name}`), h("span", { class: "spacer" }),
              st.provider === "chatgpt" ? h("button", { type: "button", class: "btn outline sm", onClick: () => login(a.key) }, t.reconnect) : null,
              !a.isDefault ? h("button", { type: "button", class: "btn outline sm", onClick: () => setDefault(a) }, t.setDefault) : null,
              h("button", { type: "button", class: "btn outline sm", style: { color: "var(--error)" }, onClick: () => disconnect(a) }, t.disconnect));
            const tabs = [["models", `${t.models}${st.catalog ? ` (${(st.catalog.accounts.find((x) => x.key === a.key) || { models: [] }).models.length})` : ""}`], st.provider !== "chatgpt" ? ["tools", t.tools] : null, ["usage", t.usage]].filter(Boolean);
            const bar = h("div", { class: "subTabs", role: "tablist" }, tabs.map(([k, label]) => h("button", { type: "button", role: "tab", "aria-selected": String(st.tab === k), onClick: () => { st.tab = k; render(); if (k === "usage" && !st.usage) loadUsage(false); } }, label)));
            return h("div", { class: "subCard" }, head, bar, st.tab === "models" ? modelsTab() : st.tab === "tools" ? toolsTab() : usageTab());
          }
          function render() {
            if (!alive) return;
            const head = h("div", { class: "pageHead" }, h("div", null, h("h1", { class: "pageTitle" }, t.title), h("p", { class: "pageIntro" }, t.intro)), h("div", { class: "headTools" }, h("button", { type: "button", class: "btn outline sm", onClick: async () => { try { await call("/refresh", { method: "POST", body: "{}" }); setNotice("ok", t.saved); loadCatalog(false); } catch (err) { fail(err); } } }, t.refreshRoutes), h("button", { type: "button", class: "iconButton", title: t.refresh, onClick: () => { loadStatus(false); loadCatalog(false); } }, ico("refresh"))));
            const parts = [head];
            if (st.notice) parts.push(h("div", { class: "subNotice", "data-kind": st.notice.kind }, h("span", null, st.notice.text), h("button", { type: "button", class: "iconButton sm", onClick: () => setNotice(null) }, ico("x"))));
            parts.push(h("div", { class: "subBody" }, side(), h("div", { class: "subMain" }, main())));
            root.replaceChildren(...parts);
          }
          render(); loadStatus(false).then(() => loadCatalog(false));
          return () => { alive = false; clearTimeout(st.pollTimer); };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "subscriptions", label: t.title, icon: "card", description: t.intro, order: 60 });
        ctx.slots.register({ slot: "main", key: "subscriptions", label: t.title }, page);
      },
    };
  },
});
