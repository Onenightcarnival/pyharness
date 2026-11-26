window.__PyhModules__.load({
  id: "__BUNDLE__",
  factory(require) {
    const { h, toast } = require("pyxis-harness");
    return {
      apply(ctx) {
        async function render(el) {
          let data;
          try { data = await ctx.host.call("stats", { locale: ctx.locale }); } catch (err) { toast(err.message); return; }
          const rows = Object.entries(data.tool_calls);
          el.replaceChildren(h("div", { class: "page" },
            h("div", { class: "pageHead" }, h("div", {}, h("h1", { class: "pageTitle" }, "__TITLE__"), h("p", { class: "pageIntro" }, data.greeting))),
            h("div", { class: "group" },
              h("div", { class: "groupHead" }, h("h2", { class: "groupTitle" }, "Tool calls this generation"), h("span", { class: "groupMeta" }, String(rows.length))),
              rows.length ? h("dl", { class: "kvTable" }, rows.flatMap(([name, n]) => [h("dt", {}, name), h("dd", {}, String(n))])) : h("p", { class: "pageIntro" }, "No tool calls yet."))));
        }
        // The panel: mount renders, re-renders when a run finishes, and returns the cleanup.
        ctx.slots.register({ slot: "main", key: "__BUNDLE__", label: "__TITLE__" }, (el) => {
          render(el);
          return ctx.on("run", (ev) => { if (ev.type === "done") render(el); });
        });
        // The sidebar row that opens it (same key as the main panel).
        ctx.slots.register({ slot: "sidebar.panellist", id: "__BUNDLE__", label: "__TITLE__", icon: "box", order: 10 });
      },
    };
  },
});
