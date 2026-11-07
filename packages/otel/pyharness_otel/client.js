// Browser module of the `otel` entry: the Settings → Observability section (endpoint, keys, toggles, advanced
// options, send test, check exports, status and counters).
window.__PyhModules__.load({
  id: "otel",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: { title: "可观测", intro: "把每一轮对话以 OpenTelemetry GenAI 语义约定上报到 OTLP 后端（如 Langfuse）：一轮一条 trace，包含 agent、步骤、模型调用与工具调用。", reporting: "上报中", inactive: "未上报", refresh: "刷新状态", startFail: "采集器启动失败：", exportFail: "最近一次上报失败：", note: "提示：", endpoint: "Endpoint", publicKey: "Public Key", secretKey: "Secret Key", secretSaved: "已保存（留空保持不变）", enable: "启用上报", capture: "采集正文", captureHint: "（含对话内容、系统提示、工具定义与工具输入输出）", advancedShow: "高级设置 ▾", advancedHide: "收起高级设置 ▴", gzip: "gzip 压缩", maxChars: "正文截断上限（字符）", batch: "单批最大 span 数", verify: "检查上报", verifyTip: "检查最近的 Trace 是否已入库（Langfuse）", verifying: "检查中…", test: "发送测试", testing: "测试中…", save: "保存", saving: "保存中…", savedOn: "已保存，上报已启动", savedOff: "已保存，上报当前为停用状态", savedFail: "已保存，但采集器未能启动", details: "详情", trace: "Trace：", run: (b, s) => `本次运行：${b} 批 / ${s} 个 span`, last: (t, ok) => `；最近一次 ${t}（${ok ? "成功" : "失败"}）`, passed: "测试通过", failed: "操作失败" },
      en: { title: "Observability", intro: "Export every turn to an OTLP backend such as Langfuse using the OpenTelemetry GenAI semantic conventions: one trace per turn with the agent, steps, model calls and tool calls.", reporting: "Reporting", inactive: "Inactive", refresh: "Refresh status", startFail: "Collector failed to start: ", exportFail: "Last export failed: ", note: "Note: ", endpoint: "Endpoint", publicKey: "Public Key", secretKey: "Secret Key", secretSaved: "Saved (leave blank to keep)", enable: "Enable reporting", capture: "Capture content", captureHint: " (conversations, system prompt, tool definitions and tool inputs / outputs)", advancedShow: "Advanced settings ▾", advancedHide: "Hide advanced settings ▴", gzip: "gzip compression", maxChars: "Content limit (characters)", batch: "Maximum spans per batch", verify: "Check exports", verifyTip: "Check whether recent traces were stored (Langfuse)", verifying: "Checking…", test: "Send test", testing: "Testing…", save: "Save", saving: "Saving…", savedOn: "Saved. Reporting is active.", savedOff: "Saved. Reporting is disabled.", savedFail: "Saved. Collector failed to start.", details: "Details", trace: "Trace: ", run: (b, s) => `This run: ${b} batches / ${s} spans`, last: (t, ok) => `; last export ${t} (${ok ? "succeeded" : "failed"})`, passed: "Tests passed", failed: "Operation failed" },
    };
    async function call(path, opts) {
      const res = await fetch("/api/otel" + path, { headers: { "content-type": "application/json" }, ...(opts || {}) });
      if (!res.ok) { let detail = `HTTP ${res.status}`; try { const d = (await res.json()).detail; if (typeof d === "string") detail = d; } catch { /* no body */ } throw new Error(detail); }
      return res.json();
    }

    return {
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        const style = document.createElement("style");
        style.textContent = `
          .otelCard { padding: 16px 18px; border-radius: 12px; background: var(--layer-2); box-shadow: inset 0 0 0 0.5px var(--border-l2); display: flex; flex-direction: column; gap: 12px; max-width: 760px; }
          .otelHead { display: flex; align-items: center; gap: 10px; max-width: 760px; margin-bottom: 10px; }
          .otelHead .spacer { flex: 1; }
          .otelLink { background: none; border: none; padding: 0; font-size: 12px; color: var(--info); cursor: pointer; }
          .otelCard label.f { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--label-secondary); }
          .otelCard label.check { flex-direction: row; align-items: center; gap: 6px; font-size: 13px; color: var(--label-primary); }
          .otelCard label.check small { color: var(--label-tertiary); }
          .otelAdv { border: 0.5px dashed var(--border-l3); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; }
          .otelAdv .input { width: 180px; }
          .otelRow { display: flex; align-items: center; gap: 8px; } .otelRow .spacer { flex: 1; }
          .otelBox { padding: 8px 12px; border-radius: 8px; font-size: 12px; max-width: 760px; }
          .otelBox[data-kind="ok"] { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }
          .otelBox[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .otelBox details { margin-top: 4px; } .otelBox pre { margin: 4px 0 0; white-space: pre-wrap; font: 11px/16px var(--mono); }
          .otelMeta { font-size: 12px; color: var(--label-tertiary); max-width: 760px; overflow-wrap: anywhere; }
        `;
        document.head.appendChild(style);
        ctx.effect(() => style.remove());

        function section(el) {
          let alive = true; let status = null; let busy = null; let advanced = false; let result = null;
          const d = { endpoint: "", publicKey: "", secretKey: "", secretDirty: false, enabled: true, captureContent: true, gzip: false, contentMaxChars: "128000", maxExportBatchSize: "512" };
          const root = h("div"); el.replaceChildren(root);
          async function load() {
            try {
              status = await call("/status"); if (!alive) return;
              Object.assign(d, { endpoint: status.endpoint || "", publicKey: status.publicKey || "", enabled: status.configured ? !!status.enabled : true, captureContent: status.captureContent !== false, gzip: !!status.gzip, contentMaxChars: String(status.contentMaxChars || 128000), maxExportBatchSize: String(status.maxExportBatchSize || 512) });
            } catch (err) { result = { kind: "error", text: err.message }; }
            render();
          }
          const num = (v, def) => { const n = Number(v); return v === "" || !Number.isFinite(n) || n <= 0 || n === def ? null : Math.round(n); };
          const payload = () => { const p = { endpoint: d.endpoint, publicKey: d.publicKey, enabled: d.enabled, captureContent: d.captureContent, gzip: d.gzip, contentMaxChars: num(d.contentMaxChars, 128000), maxExportBatchSize: num(d.maxExportBatchSize, 512) }; if (d.secretDirty) p.secretKey = d.secretKey; return p; };
          async function save() {
            busy = "save"; render();
            try { status = await call("/settings", { method: "PUT", body: JSON.stringify(payload()) }); d.secretDirty = false; d.secretKey = ""; result = status.running ? { kind: "ok", text: t.savedOn } : status.enabled ? { kind: "error", text: t.savedFail + (status.lastError ? ": " + status.lastError : "") } : { kind: "ok", text: t.savedOff }; }
            catch (err) { result = { kind: "error", text: t.failed, detail: err.message }; }
            busy = null; render();
          }
          async function test() {
            busy = "test"; render();
            try { const r = await call("/test", { method: "POST", body: JSON.stringify({ endpoint: d.endpoint, publicKey: d.publicKey, secretKey: d.secretDirty ? d.secretKey : undefined, gzip: d.gzip }) }); result = { kind: "ok", text: t.passed, detail: r.message + (r.traceEndpoint ? `\n${t.trace}${r.traceEndpoint}` : "") }; }
            catch (err) { result = { kind: "error", text: t.failed, detail: err.message }; }
            busy = null; load();
          }
          async function verify() {
            busy = "verify"; render();
            try { const r = await call("/verify", { method: "POST", body: "{}" }); result = { kind: r.ok ? "ok" : "error", text: r.message, detail: JSON.stringify(r.found, null, 2) }; }
            catch (err) { result = { kind: "error", text: t.failed, detail: err.message }; }
            busy = null; render();
          }
          function render() {
            if (!alive) return;
            const s = status;
            const pill = h("span", { class: "tag", "data-tone": s && s.running ? "success" : "quiet" }, s ? (s.running ? t.reporting : t.inactive) : "…");
            const head = h("div", { class: "otelHead" }, h("p", { class: "sectionIntro", style: { margin: 0, flex: 1 } }, t.intro), pill, h("button", { type: "button", class: "iconButton", title: t.refresh, onClick: load }, ico("refresh")));
            const boxes = [];
            if (s && s.lastError) boxes.push(h("div", { class: "otelBox", "data-kind": "error" }, t.startFail + s.lastError));
            if (s && s.lastExportError) boxes.push(h("div", { class: "otelBox", "data-kind": "error" }, t.exportFail + s.lastExportError));
            const input = (key, attrs = {}) => h("input", { class: "input" + (attrs.mono ? " mono" : ""), value: d[key], ...attrs, onInput: (e) => { d[key] = e.target.value; } });
            const secret = h("input", { class: "input", type: "password", autocomplete: "new-password", placeholder: s && s.secretKeySet ? t.secretSaved : "sk-lf-…", onInput: (e) => { d.secretKey = e.target.value; d.secretDirty = true; } });
            const adv = advanced ? h("div", { class: "otelAdv" },
              h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.gzip, onChange: (e) => { d.gzip = e.target.checked; } }), t.gzip),
              h("label", { class: "f" }, t.maxChars, input("contentMaxChars", { type: "number", min: 100 })),
              h("label", { class: "f" }, t.batch, input("maxExportBatchSize", { type: "number", min: 1, max: 4096 }))) : null;
            const card = h("div", { class: "otelCard" },
              h("label", { class: "f" }, t.endpoint, input("endpoint", { mono: true, placeholder: "https://cloud.langfuse.com/api/public/otel" })),
              h("label", { class: "f" }, t.publicKey, input("publicKey", { mono: true, placeholder: "pk-lf-…", autocomplete: "off" })),
              h("label", { class: "f" }, t.secretKey, secret),
              h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.enabled, onChange: (e) => { d.enabled = e.target.checked; } }), t.enable),
              h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.captureContent, onChange: (e) => { d.captureContent = e.target.checked; } }), t.capture, h("small", null, t.captureHint)),
              h("button", { type: "button", class: "otelLink", style: { alignSelf: "flex-start" }, onClick: () => { advanced = !advanced; render(); } }, advanced ? t.advancedHide : t.advancedShow),
              adv,
              h("div", { class: "otelRow" }, h("span", { class: "spacer" }),
                h("button", { type: "button", class: "btn outline sm", title: t.verifyTip, disabled: !!busy || !(s && s.running), onClick: verify }, busy === "verify" ? t.verifying : t.verify),
                h("button", { type: "button", class: "btn outline sm", disabled: !!busy, onClick: test }, busy === "test" ? t.testing : t.test),
                h("button", { type: "button", class: "btn primary sm", disabled: !!busy, onClick: save }, busy === "save" ? t.saving : t.save)));
            const res = result ? h("div", { class: "otelBox", "data-kind": result.kind }, result.text, result.detail ? h("details", null, h("summary", null, t.details), h("pre", null, result.detail)) : null) : null;
            const meta = [];
            if (s && s.running && s.traceEndpoint) meta.push(h("div", { class: "otelMeta" }, t.trace + s.traceEndpoint));
            if (s && (s.exportedBatches || s.exportedSpans)) meta.push(h("div", { class: "otelMeta" }, t.run(s.exportedBatches, s.exportedSpans) + (s.lastExportAt ? t.last(new Date(s.lastExportAt * 1000).toLocaleTimeString(), s.lastExportOk) : "")));
            root.replaceChildren(...[head, ...boxes, card, res, ...meta].filter(Boolean));
          }
          render(); load();
          return () => { alive = false; };
        }
        ctx.slots.register({ slot: "settings.sections", key: "observability", label: t.title, icon: "eye", order: 110 }, section);
      },
    };
  },
});
