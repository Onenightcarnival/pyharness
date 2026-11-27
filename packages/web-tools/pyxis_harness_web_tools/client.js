window.__PyhModules__.load({
  id: "web-tools",
  factory(require) {
    const { icon, esc, toast, json, T } = require("pyxis-harness");
    const L = {
      zh: { title: "网页搜索", intro: "agent 的 web_search 与 web_fetch 工具。", search: "网页搜索", searchHint: "web_search 工具；更改后重启生效", fetch: "网页获取", fetchHint: "web_fetch 工具：读取一个网址的正文；更改后重启生效", on: "开启", off: "关闭", provider: "搜索提供方", providerHint: "DeepSeek Search API：每次搜索一个直接请求；服务端搜索：一次带搜索工具的 Messages 调用，返回回答与引用", providerApi: "DeepSeek Search API", providerLegacy: "DeepSeek 服务端搜索", key: "API Key", keySet: (ref, source) => `已配置（${source === "env" ? "环境变量" : "凭据文件"} ${ref}）；留空保持不变`, keyUnset: (ref) => `未配置；在此填写，或设置环境变量 ${ref}`, keySaved: "密钥已保存", keyCleared: "密钥已清除", clear: "清除", baseUrl: "Base URL", baseUrlHint: "当前提供方的接口地址", count: "每次搜索结果数", countHint: "一次搜索返回的来源数，1 到 50", uses: "单次请求最多搜索次数", usesHint: "服务端搜索在一次请求里可以搜索的次数，1 到 20", restart: "已保存；重启后生效，没有运行中的轮次时自动重启。" },
      en: { title: "Web search", intro: "The agent's web_search and web_fetch tools.", search: "Web search", searchHint: "The web_search tool; a change takes effect after a restart", fetch: "Web fetch", fetchHint: "The web_fetch tool: reads the text of a URL; a change takes effect after a restart", on: "On", off: "Off", provider: "Search provider", providerHint: "DeepSeek Search API: one direct request per search; server-side search: a Messages call with the search tool, returning an answer with citations", providerApi: "DeepSeek Search API", providerLegacy: "DeepSeek server-side search", key: "API Key", keySet: (ref, source) => `Configured (${source === "env" ? "environment variable" : "credential file"} ${ref}); leave empty to keep it`, keyUnset: (ref) => `Not configured; enter one here, or set the environment variable ${ref}`, keySaved: "Key saved", keyCleared: "Key removed", clear: "Remove", baseUrl: "Base URL", baseUrlHint: "Endpoint of the selected provider", count: "Results per search", countHint: "Sources one search returns, 1 to 50", uses: "Searches per request", usesHint: "Searches the server-side search may run in one request, 1 to 20", restart: "Saved; in effect after a restart, which happens once no turn is running." },
    };
    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        function section(el) {
          let alive = true;
          const row = (title, hint, control) => `<div class="srow"><div class="main"><div class="title">${esc(title)}</div><div class="desc">${esc(hint)}</div></div><div class="ctl">${control}</div></div>`;
          const select = (key, options, value) => `<div class="selectWrap"><select class="select" data-web="${key}">${options.map(([v, label]) => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>${icon("chev-down", "ico chev")}</div>`;
          const number = (key, value, min, max) => `<span class="numField"><input class="input num" type="number" data-web="${key}" value="${value}" min="${min}" max="${max}" step="1" style="width:72px"></span>`;
          const onOff = (key, value) => select(key, [["1", t.on], ["0", t.off]], value ? "1" : "0");
          function render(s) {
            const legacy = s.search_provider === "deepseek-legacy"; const url = legacy ? "base_url" : "search_base_url";
            el.innerHTML = `<p class="sectionIntro">${esc(t.intro)}</p>`
              + row(t.search, t.searchHint, onOff("search", s.search))
              + row(t.provider, t.providerHint, select("search_provider", [["deepseek-search-api", t.providerApi], ["deepseek-legacy", t.providerLegacy]], s.search_provider))
              + row(t.key, s.key.configured ? t.keySet(s.key.reference, s.key.source) : t.keyUnset(s.key.reference), `<input class="input mono" type="password" data-web="api_key" placeholder="${s.key.configured ? "••••••••" : ""}" autocomplete="off" style="width:220px">${s.key.source === "store" ? `<button type="button" class="btn sm outline" data-clear style="margin-left:8px">${esc(t.clear)}</button>` : ""}`)
              + row(t.baseUrl, t.baseUrlHint, `<input class="input mono" data-web="${url}" value="${esc(s[url])}" spellcheck="false" autocomplete="off" style="width:280px">`)
              + row(t.count, t.countHint, number("max_results", s.max_results, 1, 50))
              + (legacy ? row(t.uses, t.usesHint, number("max_uses", s.max_uses, 1, 20)) : "")
              + row(t.fetch, t.fetchHint, onOff("fetch", s.fetch));
            const save = async (fields, done) => {
              try {
                const saved = await json("/web-tools/settings", { method: "PUT", body: JSON.stringify(fields) });
                toast(done || (saved.application === "restart" ? t.restart : T.applied));
                if (alive) render(saved);
              } catch (err) { toast(err.message); if (alive) render(s); }
            };
            el.querySelectorAll("[data-web]").forEach((control) => {
              control.onchange = () => {
                const key = control.dataset.web;
                if (key === "api_key") { if (control.value.trim()) save({ api_key: control.value.trim() }, t.keySaved); return; }
                const value = key === "search" || key === "fetch" ? control.value === "1" : control.type === "number" ? Math.round(+control.value) : control.value.trim();
                save({ [key]: value });
              };
            });
            const clear = el.querySelector("[data-clear]"); if (clear) clear.onclick = () => save({ api_key: "" }, t.keyCleared);
          }
          json("/web-tools/settings").then((s) => { if (alive) render(s); }).catch((err) => { el.textContent = err.message; });
          return () => { alive = false; };
        }
        ctx.slots.register({ slot: "settings.sections", key: "web-tools", label: t.title, icon: "globe", order: 70 }, section);
      },
    };
  },
});
