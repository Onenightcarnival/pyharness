window.__PyhModules__.load({
  id: "http-client",
  factory(require) {
    const { h, icon, esc } = require("pyharness");
    const ico = (name, cls) => { const tpl = document.createElement("template"); tpl.innerHTML = icon(name, cls); return tpl.content.firstChild; };
    const L = {
      zh: {
        entry: "HTTP", title: "HTTP 请求", close: "关闭",
        intro: "HTTP API 客户端：目标与凭证、保存的请求、请求历史与事件流；可开放给 Agent 的 http_* 工具。",
        agentTools: "允许 Agent 使用", toolsOn: "已注册 http_* 工具", toolsOff: "已注销 http_* 工具", resize: "调整请求与响应的比例",
        targetsSelect: "目标", targetsDirect: "无目标",
        targetsDirectHint: "直接请求：填写完整 URL。凭证不由 harness 保管，Agent 不可调用。",
        targetsAdd: "＋ 新增目标…", targetsFromRequest: "由此地址新建目标", targetsEdit: "编辑目标", targetsDelete: "删除目标",
        targetsTest: "测试连接", targetsDeleteConfirm: (name) => `确定删除目标「${name}」？同时删除它保存的请求与请求历史。`,
        targetsTesting: "连接测试中…", targetsTestOk: (status, latency) => `HTTP ${status}（${latency} ms）`,
        targetsTestFail: (error) => `连接失败：${error}`, targetsMutations: "允许变更", targetsReadOnly: "仅读",
        formCreate: "新增目标", formEdit: (name) => `编辑目标「${name}」`, formName: "名称", formNamePlaceholder: "默认用主机名",
        formBaseUrl: "Base URL", formAuth: "认证",
        auth: { none: "无", bearer: "Bearer token", basic: "Basic", header: "自定义 header", query: "Query 参数" },
        authToken: "Token", authUsername: "用户名", authPassword: "密码", authHeaderName: "Header 名", authQueryName: "参数名",
        authValue: "值", authKeep: "留空保留已保存的值",
        formHeaders: "固定 header", formVariables: "变量", formVariablesHint: "在路径、query、header 和 body 中以 {{名称}} 引用。",
        formAllowedHosts: "允许的额外 host", formAllowedHostsHint: "每行一个；Base URL 的 host 始终允许，*.example.com 匹配子域。",
        formAllowMutations: "允许 Agent 使用 POST / PUT / PATCH / DELETE（每次仍需确认）", formAllowPrivate: "允许访问回环与内网地址",
        formTimeout: "超时（毫秒）", formAdvanced: "高级", cancel: "取消", save: "保存", saving: "保存中…",
        kvKey: "名称", kvValue: "值", kvRemove: "移除", kvEnabled: "启用", kvAdd: "添加", kvBulk: "批量编辑", kvTable: "键值编辑",
        kvDeleteAll: "全部删除", kvBulkHint: "每行一条「名称: 值」；以 # 开头的行不发送。",
        requestPath: "路径", requestPathPlaceholder: "/users/42", requestUrlPlaceholder: "输入 URL，或粘贴 cURL 命令",
        requestDirectAuthNote: "此请求未绑定目标：这里的认证随请求保存，并在历史中遮罩。新建目标后凭证由 harness 保管并在发送时注入，Agent 也能按名称调用该目标。",
        requestOwnAuthNote: "目标未配置认证：这里的认证随请求保存，发送时使用，并在历史中遮罩。",
        requestShowSecret: "显示", requestHideSecret: "隐藏", requestImportQuery: "从 URL 导入参数",
        requestCurlImported: "已从 cURL 命令导入请求。",
        requestCurlMultipart: "已从 cURL 命令导入；multipart 表单按 URL 编码表单处理，不支持文件字段。",
        requestSend: "发送", requestTabs: { params: "Params", body: "Body", headers: "Headers", auth: "Auth" },
        requestUrlPreview: "URL 预览", requestCopy: "复制", bodyModes: { none: "无", json: "JSON", text: "文本", form: "表单" },
        requestBodyPlaceholder: '{"name": "..."}', requestBodyNone: "未设置 body。",
        requestNoBody: (method) => `${method} 请求不发送 body。`, requestFormatJson: "格式化",
        requestInvalidJson: (error) => `JSON 无效：${error}`, requestFixedHeaders: "目标的固定 header",
        requestAuthNote: "认证在目标上配置，由 harness 在发送时注入。",
        responseEmpty: "发送请求后在这里查看响应。", responseSending: (seconds) => `发送中… ${seconds} s`, responseCancel: "取消请求",
        streamModes: { events: "事件", text: "文本", raw: "原始" }, streamCount: (count) => `${count} 个事件`,
        streamReceiving: (seconds) => `接收中… ${seconds} s`, streamStop: "停止", streamWaiting: "等待第一个事件…",
        streamEmpty: "流中没有事件。", streamLatest: (count) => `仅显示最近 ${count} 个事件。`,
        streamEnded: { cancelled: "已手动停止，保留已收到的内容。", timeout: "超时时间内没有新数据，连接已关闭。" },
        responseErrorTag: "失败", responseError: (error) => `请求失败：${error}`, responseRedirects: (list) => `经重定向：${list}`,
        responseTabs: { preview: "Preview", headers: "Headers", request: "Request" },
        responseBinary: (size) => `二进制正文（${size}），不显示。`, responseSave: "保存到文件", responseSource: "源码",
        responseRender: "渲染", responseNoBody: "响应没有正文。", responseNoHeaders: "没有响应 header。",
        responseTruncated: (size) => `正文已截断，显示前 ${size}。`, responsePretty: "格式化", responseRaw: "原始",
        responseCopy: "复制正文", responseCopied: "已复制", responseCopyUrl: "复制 URL", responseTime: (ms) => `${ms} ms`,
        responseSentHeaders: "已发送的 header", responseSentBody: "已发送的 body", responseRequestTruncated: "body 已截断保存。",
        responseVersions: "该请求的历次响应", sideRequests: "请求", sideHistory: "历史",
        requestsNew: "新建请求", requestsUntitled: "新请求", requestsFilter: "过滤请求…", requestsEmpty: "还没有保存的请求。",
        requestsNoMatch: "没有匹配的请求。", requestsNone: "新建一个请求开始编辑。", requestsActions: "请求操作",
        requestsRename: "重命名", requestsDuplicate: "创建副本", requestsCopyCurl: "复制为 cURL",
        requestsCurlCopied: "已复制 cURL 命令。", requestsCurlUnavailable: "请求的 URL 无效，无法生成 cURL 命令。",
        requestsDelete: "删除请求", requestsDeleteConfirm: (name) => `确定删除请求「${name}」？`, requestsCopySuffix: "副本",
        requestsSaveFailed: (error) => `请求保存失败：${error}`,
        historySaveAs: "存为请求", historyFilter: "过滤历史…", historyEmpty: "还没有请求记录。", historyNoMatch: "没有匹配的记录。",
        historyCount: (count) => `${count} 条`, historyDelete: "删除记录", historyClear: "清空历史",
        historyClearConfirm: (name) => `确定清空「${name}」的全部请求历史？`, historyLimit: "上限",
        historyLimitHint: (min, max) => `保留的历史条数（${min}–${max}），超出时先丢弃最旧的。`,
        sourcePanel: "面板", sourceAgent: "Agent", historyFailed: "ERR",
        errorDisabled: "HTTP 插件未启用或 API 不可用。", errorIncomplete: "连接在响应完成前关闭。",
      },
      en: {
        entry: "HTTP", title: "HTTP requests", close: "Close",
        intro: "HTTP API client: targets with their credentials, saved requests, request history and event streams; the http_* tools can be opened to the agent.",
        agentTools: "Allow agent", toolsOn: "http_* tools registered", toolsOff: "http_* tools unregistered",
        resize: "Resize request and response", targetsSelect: "Target", targetsDirect: "No target",
        targetsDirectHint: "Direct requests: enter a full URL. Credentials are not kept by the harness, and the agent cannot call them.",
        targetsAdd: "＋ New target…", targetsFromRequest: "New target from this URL", targetsEdit: "Edit target",
        targetsDelete: "Delete target", targetsTest: "Test connection",
        targetsDeleteConfirm: (name) => `Delete target "${name}"? Its saved requests and request history are deleted too.`,
        targetsTesting: "Testing connection…", targetsTestOk: (status, latency) => `HTTP ${status} (${latency} ms)`,
        targetsTestFail: (error) => `Connection failed: ${error}`, targetsMutations: "mutations allowed", targetsReadOnly: "read-only",
        formCreate: "New target", formEdit: (name) => `Edit target "${name}"`, formName: "Name",
        formNamePlaceholder: "Defaults to the host name", formBaseUrl: "Base URL", formAuth: "Authentication",
        auth: { none: "None", bearer: "Bearer token", basic: "Basic", header: "Custom header", query: "Query parameter" },
        authToken: "Token", authUsername: "Username", authPassword: "Password", authHeaderName: "Header name",
        authQueryName: "Parameter name", authValue: "Value", authKeep: "Leave empty to keep the saved value",
        formHeaders: "Fixed headers", formVariables: "Variables",
        formVariablesHint: "Reference them as {{name}} in path, query, headers and body.", formAllowedHosts: "Extra allowed hosts",
        formAllowedHostsHint: "One per line; the base URL host is always allowed, *.example.com matches subdomains.",
        formAllowMutations: "Allow the agent to use POST / PUT / PATCH / DELETE (each call still asks for confirmation)",
        formAllowPrivate: "Allow loopback and private-network addresses", formTimeout: "Timeout (ms)", formAdvanced: "Advanced",
        cancel: "Cancel", save: "Save", saving: "Saving…",
        kvKey: "Name", kvValue: "Value", kvRemove: "Remove", kvEnabled: "Enabled", kvAdd: "Add", kvBulk: "Bulk edit",
        kvTable: "Key-value edit", kvDeleteAll: "Delete all",
        kvBulkHint: 'One "name: value" per line; lines starting with # are not sent.',
        requestPath: "Path", requestPathPlaceholder: "/users/42", requestUrlPlaceholder: "Enter a URL, or paste a cURL command",
        requestDirectAuthNote: "This request has no target: the authentication here is saved with the request and masked in the history. With a target the harness keeps the credentials and injects them when sending, and the agent can call the target by name.",
        requestOwnAuthNote: "The target has no authentication: the authentication here is saved with the request, used when sending and masked in the history.",
        requestShowSecret: "Show", requestHideSecret: "Hide", requestImportQuery: "Import parameters from URL",
        requestCurlImported: "Request imported from the cURL command.",
        requestCurlMultipart: "Imported from the cURL command; multipart form fields became URL-encoded fields, and file fields are not supported.",
        requestSend: "Send", requestTabs: { params: "Params", body: "Body", headers: "Headers", auth: "Auth" },
        requestUrlPreview: "URL preview", requestCopy: "Copy", bodyModes: { none: "None", json: "JSON", text: "Text", form: "Form" },
        requestBodyPlaceholder: '{"name": "..."}', requestBodyNone: "No body set.",
        requestNoBody: (method) => `${method} requests send no body.`, requestFormatJson: "Format",
        requestInvalidJson: (error) => `Invalid JSON: ${error}`, requestFixedHeaders: "Fixed headers of the target",
        requestAuthNote: "Authentication is configured on the target and injected by the harness when sending.",
        responseEmpty: "Send a request to see the response here.", responseSending: (seconds) => `Sending… ${seconds} s`,
        responseCancel: "Cancel request",
        streamModes: { events: "Events", text: "Text", raw: "Raw" }, streamCount: (count) => `${count} events`,
        streamReceiving: (seconds) => `Receiving… ${seconds} s`, streamStop: "Stop", streamWaiting: "Waiting for the first event…",
        streamEmpty: "The stream carried no events.", streamLatest: (count) => `Showing the latest ${count} events.`,
        streamEnded: { cancelled: "Stopped by hand; what arrived is kept.", timeout: "No data within the timeout; the connection was closed." },
        responseErrorTag: "Failed", responseError: (error) => `Request failed: ${error}`,
        responseRedirects: (list) => `Redirected via: ${list}`,
        responseTabs: { preview: "Preview", headers: "Headers", request: "Request" },
        responseBinary: (size) => `Binary body (${size}), not shown.`, responseSave: "Save to file", responseSource: "Source",
        responseRender: "Rendered", responseNoBody: "The response has no body.", responseNoHeaders: "No response headers.",
        responseTruncated: (size) => `Body truncated; showing the first ${size}.`, responsePretty: "Pretty", responseRaw: "Raw",
        responseCopy: "Copy body", responseCopied: "Copied", responseCopyUrl: "Copy URL", responseTime: (ms) => `${ms} ms`,
        responseSentHeaders: "Headers sent", responseSentBody: "Body sent", responseRequestTruncated: "The body is stored truncated.",
        responseVersions: "Responses of this request", sideRequests: "Requests", sideHistory: "History",
        requestsNew: "New request", requestsUntitled: "New request", requestsFilter: "Filter requests…",
        requestsEmpty: "No saved requests yet.", requestsNoMatch: "No matching requests.",
        requestsNone: "Create a request to start editing.", requestsActions: "Request actions", requestsRename: "Rename",
        requestsDuplicate: "Duplicate", requestsCopyCurl: "Copy as cURL", requestsCurlCopied: "cURL command copied.",
        requestsCurlUnavailable: "The request URL is invalid; no cURL command can be written.", requestsDelete: "Delete request",
        requestsDeleteConfirm: (name) => `Delete request "${name}"?`, requestsCopySuffix: "copy",
        requestsSaveFailed: (error) => `Saving the request failed: ${error}`,
        historySaveAs: "Save as request", historyFilter: "Filter history…", historyEmpty: "No requests recorded yet.",
        historyNoMatch: "No matching entries.", historyCount: (count) => `${count} entries`, historyDelete: "Delete entry",
        historyClear: "Clear history", historyClearConfirm: (name) => `Clear the whole request history of "${name}"?`,
        historyLimit: "Limit", historyLimitHint: (min, max) => `Exchanges kept (${min}–${max}); the oldest are dropped first.`,
        sourcePanel: "Panel", sourceAgent: "Agent", historyFailed: "ERR",
        errorDisabled: "The HTTP plugin is disabled or its API is unavailable.",
        errorIncomplete: "The connection closed before the response was complete.",
      },
    };
    const API = "/api/http-client";
    // Scope id of requests sent without a target: a full URL, no harness-side credentials, panel only.
    const DIRECT = "direct";
    const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];
    const AUTH_TYPES = ["none", "bearer", "basic", "header", "query"];
    const BODY_MODES = ["none", "json", "text", "form"];
    const REQUEST_TABS = ["params", "body", "headers", "auth"];
    const RESPONSE_TABS = ["preview", "headers", "request"];
    const STREAM_MODES = ["events", "text", "raw"];
    const DEFAULT_TIMEOUT_MS = 30000;
    const HISTORY_LIMIT_MIN = 10;
    const HISTORY_LIMIT_MAX = 1000;
    const SPLIT_KEY = "pyh-http-client:split";
    const SCOPE_KEY = "pyh-http-client:scope";
    const SPLIT_MIN = 20;
    const SPLIT_MAX = 80;
    // Select value of the "new target" entry.
    const NEW_TARGET = "__new__";
    // Interval of the newest-entry check that picks up requests sent by the agent.
    const HISTORY_POLL_MS = 4000;
    // Quiet time after the last edit before a request form is saved.
    const AUTOSAVE_MS = 500;
    // Event rows kept in the list; a longer stream shows its latest ones.
    const MAX_ROWS = 2000;
    // Distance from the bottom within which new rows keep the event list scrolled to the end.
    const STICK_PX = 48;
    const NO_AUTH = { type: "none" };

    // ------------------------------------------------------------ protocol
    const toPairs = (value) => (value === undefined ? [] : Array.isArray(value) ? value : Object.entries(value));
    const isEventStream = (contentType) => contentType.split(";")[0].trim().toLowerCase() === "text/event-stream";
    const substitute = (text, variables) => text.replace(/\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}/g,
      (match, name) => (Object.prototype.hasOwnProperty.call(variables, name) ? variables[name] : match));

    // Incremental server-sent event parser (WHATWG event stream format): lines end with LF, CR or CRLF; `:` lines are
    // comments; a blank line dispatches the event built from the `event`, `data`, `id` and `retry` fields since the
    // previous one. An event without any field is not dispatched.
    class SseParser {
      constructor() { this.buffer = ""; this.reset(); }
      reset() { this.event = ""; this.data = []; this.id = undefined; this.retry = undefined; this.touched = false; }
      push(chunk) {
        this.buffer += chunk;
        const out = [];
        for (;;) {
          const match = /\r\n|\n|\r/.exec(this.buffer);
          // A CR that ends the buffer may be the first half of a CRLF still in transit.
          if (match === null || (match[0] === "\r" && match.index === this.buffer.length - 1)) break;
          const line = this.buffer.slice(0, match.index);
          this.buffer = this.buffer.slice(match.index + match[0].length);
          const event = this.line(line);
          if (event !== undefined) out.push(event);
        }
        return out;
      }
      flush() {
        const rest = this.buffer.replace(/\r$/, "");
        this.buffer = "";
        return [rest === "" ? undefined : this.line(rest), this.dispatch()].filter((event) => event !== undefined);
      }
      line(line) {
        if (line === "") return this.dispatch();
        if (line.startsWith(":")) return undefined;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        let value = colon < 0 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") { this.event = value; this.touched = true; }
        else if (field === "data") { this.data.push(value); this.touched = true; }
        else if (field === "id" && !value.includes("\0")) { this.id = value; this.touched = true; }
        else if (field === "retry" && /^\d+$/.test(value)) { this.retry = Number(value); this.touched = true; }
        return undefined;
      }
      dispatch() {
        if (!this.touched) return undefined;
        const event = { event: this.event, data: this.data.join("\n") };
        if (this.id !== undefined) event.id = this.id;
        if (this.retry !== undefined) event.retry = this.retry;
        this.reset();
        return event;
      }
    }
    function parseSse(text) {
      const parser = new SseParser();
      return [...parser.push(text), ...parser.flush()];
    }

    const SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;
    // Joins a request path below a base URL, or accepts an absolute URL, and appends the query: the URL the server
    // sends. An empty base URL (a request without a target) takes the path as the whole URL; a missing scheme becomes
    // http for loopback and private literals, https otherwise. Throws on a malformed URL, a scheme other than http(s)
    // and embedded credentials.
    function joinUrl(baseUrl, path, query) {
      const parse = (text) => { try { return new URL(text); } catch { throw new Error(`invalid URL '${path}'`); } };
      let url;
      if (SCHEME.test(path)) url = parse(path);
      else if (baseUrl === "") {
        const bare = path.trim();
        if (bare === "") throw new Error("URL is required");
        if (bare.startsWith("/")) throw new Error("enter a full URL, e.g. https://api.example.com/users");
        url = parse(`${/^(localhost|127\.|10\.|192\.168\.|0\.0\.0\.0|\[)/i.test(bare) ? "http" : "https"}://${bare}`);
      } else {
        const base = new URL(baseUrl);
        const [pathPart, ...queryParts] = path.split("?");
        const basePath = base.pathname.replace(/\/+$/, "");
        const relative = pathPart.replace(/^\/+/, "");
        url = new URL(base.origin);
        url.pathname = relative === "" ? (basePath || "/") : `${basePath}/${relative}`;
        if (queryParts.length > 0) url.search = queryParts.join("?");
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("only http(s) URLs are supported");
      if (url.username !== "" || url.password !== "") throw new Error("URL credentials are not supported; use the target auth setting");
      for (const [name, value] of toPairs(query)) url.searchParams.append(name, value);
      url.hash = "";
      return url;
    }

    // ------------------------------------------------------------ cURL
    // Parsed: method, URL, headers, data (`-d` family, `--json`, `-G`), form fields (`-F`, without files), basic auth
    // (`-u`), bearer (`--oauth2-bearer`), user agent, referer and cookie strings. Other options are skipped.
    const ANSI_ESCAPES = { n: "\n", t: "\t", r: "\r", "\\": "\\", "'": "'", '"': '"', a: "\x07", b: "\b", f: "\f", v: "\v", 0: "\0" };
    // Splits a command line the way a POSIX shell does: quotes, `$'…'`, backslash escapes and line continuations.
    function tokenize(text) {
      const tokens = [];
      let current = ""; let started = false; let i = 0;
      const push = () => { if (started) tokens.push(current); current = ""; started = false; };
      const hexChar = (digits, fallback) => {
        const hex = (new RegExp(`^[0-9a-fA-F]{1,${digits}}`).exec(text.slice(i + 2)) || [""])[0];
        current += hex === "" ? fallback : String.fromCharCode(parseInt(hex, 16));
        i += 2 + hex.length;
      };
      while (i < text.length) {
        const c = text[i];
        if (c === "\\") {
          const next = text[i + 1];
          if (next === "\n") i += 2;
          else if (next === "\r" && text[i + 2] === "\n") i += 3;
          else if (next !== undefined) { current += next; started = true; i += 2; }
          else i++;
        } else if (c === "'") {
          const end = text.indexOf("'", i + 1);
          current += text.slice(i + 1, end < 0 ? text.length : end);
          started = true;
          i = end < 0 ? text.length : end + 1;
        } else if (c === "$" && text[i + 1] === "'") {
          i += 2; started = true;
          while (i < text.length && text[i] !== "'") {
            if (text[i] !== "\\" || i + 1 >= text.length) { current += text[i]; i++; continue; }
            const e = text[i + 1];
            if (e === "x") hexChar(2, "x");
            else if (e === "u") hexChar(4, "u");
            else { current += e in ANSI_ESCAPES ? ANSI_ESCAPES[e] : e; i += 2; }
          }
          i++;
        } else if (c === '"') {
          i++; started = true;
          while (i < text.length && text[i] !== '"') {
            if (text[i] !== "\\" || i + 1 >= text.length) { current += text[i]; i++; continue; }
            const e = text[i + 1];
            if (e !== "\n") current += '"\\$`'.includes(e) ? e : `\\${e}`;
            i += 2;
          }
          i++;
        } else if (c === " " || c === "\t" || c === "\n" || c === "\r") { push(); i++; }
        else { current += c; started = true; i++; }
      }
      push();
      return tokens;
    }
    // Long options that take a value; `true` marks the ones the parser reads.
    const LONG_VALUE = {
      request: true, header: true, data: true, "data-raw": true, "data-binary": true, "data-ascii": true, "data-urlencode": true,
      json: true, form: true, "form-string": true, user: true, "user-agent": true, referer: true, cookie: true, url: true,
      "oauth2-bearer": true, output: false, "max-time": false, "connect-timeout": false, proxy: false, retry: false,
      "write-out": false, "cookie-jar": false, cacert: false, cert: false, key: false, resolve: false, "max-redirs": false,
      "limit-rate": false, range: false, "proxy-user": false, "upload-file": false, interface: false, ciphers: false,
      "tls-max": false, "retry-delay": false, "retry-max-time": false, config: false, "dump-header": false, trace: false,
      "trace-ascii": false, stderr: false, "connect-to": false, "dns-servers": false, "unix-socket": false, "request-target": false,
    };
    // Short options that take a value, by their long names.
    const SHORT_VALUE = {
      X: "request", H: "header", d: "data", F: "form", u: "user", A: "user-agent", e: "referer", b: "cookie", o: "output",
      m: "max-time", x: "proxy", w: "write-out", c: "cookie-jar", T: "upload-file", r: "range", K: "config", D: "dump-header", E: "cert",
    };
    // A pasted cURL command as request fields; undefined when the text is not one or names no URL. `bodyKind` is
    // `raw` (`body` as written) or `form` (`fields` as URL-encoded form fields); `multipart` marks `-F` fields.
    function parseCurl(text) {
      const tokens = tokenize(text.trim());
      if (tokens[0] !== "curl") return undefined;
      let method; let url; let basic; let json = false; let get = false; let head = false;
      const headers = []; const data = []; const fields = [];
      const split = (value, mark) => { const at = value.indexOf(mark); return at < 0 ? [value, ""] : [value.slice(0, at), value.slice(at + 1)]; };
      const option = (name, value) => {
        if (name === "request") method = value.toUpperCase();
        else if (name === "header") { const [key, rest] = split(value, ":"); if (value.indexOf(":") > 0) headers.push([key.trim(), rest.trim()]); }
        else if (name === "data" || name === "data-raw" || name === "data-binary" || name === "data-ascii") data.push(value);
        else if (name === "data-urlencode") {
          const at = value.indexOf("=");
          data.push(at < 0 ? encodeURIComponent(value) : at === 0 ? encodeURIComponent(value.slice(1))
            : `${value.slice(0, at)}=${encodeURIComponent(value.slice(at + 1))}`);
        } else if (name === "json") { data.push(value); json = true; }
        else if (name === "form" || name === "form-string") fields.push(split(value, "="));
        else if (name === "user") { const [username, password] = split(value, ":"); basic = { username, password }; }
        else if (name === "user-agent") headers.push(["User-Agent", value]);
        else if (name === "referer") headers.push(["Referer", value]);
        else if (name === "cookie") { if (value.includes("=")) headers.push(["Cookie", value]); }
        else if (name === "oauth2-bearer") headers.push(["Authorization", `Bearer ${value}`]);
        else if (name === "url" && url === undefined) url = value;
      };
      for (let i = 1; i < tokens.length; i++) {
        const token = tokens[i];
        if (token.startsWith("--") && token.length > 2) {
          const eq = token.indexOf("=");
          const name = eq < 0 ? token.slice(2) : token.slice(2, eq);
          if (name === "get") get = true;
          else if (name === "head") head = true;
          else if (name in LONG_VALUE) {
            const value = eq < 0 ? tokens[++i] : token.slice(eq + 1);
            if (value !== undefined && LONG_VALUE[name]) option(name, value);
          }
        } else if (token.startsWith("-") && token.length > 1) {
          for (let j = 1; j < token.length; j++) {
            const flag = token[j];
            if (flag === "G") get = true;
            else if (flag === "I") head = true;
            else if (flag in SHORT_VALUE) {
              const attached = token.slice(j + 1);
              const value = attached !== "" ? attached : tokens[++i];
              if (value !== undefined && LONG_VALUE[SHORT_VALUE[flag]]) option(SHORT_VALUE[flag], value);
              break;
            }
          }
        } else if (url === undefined) url = token;
      }
      if (url === undefined || url === "") return undefined;

      const hasHeader = (name) => headers.some(([key]) => key.toLowerCase() === name);
      let bodyKind = "none"; let body = "";
      if (data.length > 0 && get) url += (url.includes("?") ? "&" : "?") + data.join("&");
      else if (data.length > 0) {
        body = json ? data.join("") : data.join("&");
        bodyKind = "raw";
        if (json) {
          if (!hasHeader("content-type")) headers.push(["Content-Type", "application/json"]);
          if (!hasHeader("accept")) headers.push(["Accept", "application/json"]);
        } else if (!hasHeader("content-type")) {
          // curl sends -d data as a URL-encoded form unless a header says otherwise.
          if (body !== "" && !/[\s{}[\]"]/.test(body) && body.split("&").every((part) => part.includes("="))) bodyKind = "form";
          else headers.push(["Content-Type", "application/x-www-form-urlencoded"]);
        }
      } else if (fields.length > 0) bodyKind = "form";

      const fallback = head ? "HEAD" : bodyKind !== "none" ? "POST" : "GET";
      return {
        method: METHODS.includes(method) ? method : fallback, url, headers, bodyKind, body: bodyKind === "raw" ? body : "",
        fields: fields.length > 0 ? fields : bodyKind === "form" ? [...new URLSearchParams(body).entries()] : [],
        basic, multipart: fields.length > 0,
      };
    }
    // Splits `?query` off a path or URL into decoded pairs.
    function splitQuery(path) {
      const index = path.indexOf("?");
      if (index < 0) return { path, pairs: [] };
      const decode = (text) => { try { return decodeURIComponent(text.replace(/\+/g, " ")); } catch { return text; } };
      const pairs = path.slice(index + 1).split("&").filter((part) => part !== "").map((part) => {
        const eq = part.indexOf("=");
        return eq < 0 ? [decode(part), ""] : [decode(part.slice(0, eq)), decode(part.slice(eq + 1))];
      });
      return { path: path.slice(0, index), pairs };
    }
    const quote = (text) => `'${text.replace(/'/g, "'\\''")}'`;
    // A request as a multi-line cURL command.
    function toCurl(request) {
      const lines = [`curl${request.method === "GET" ? "" : ` -X ${request.method}`} ${quote(request.url)}`];
      for (const [name, value] of request.headers) lines.push(`  -H ${quote(`${name}: ${value}`)}`);
      if (request.body !== undefined && request.body !== "") lines.push(`  --data-raw ${quote(request.body)}`);
      return lines.join(" \\\n");
    }

    // ------------------------------------------------------------ event streams
    // Rows of a recorded stream: its text parsed again, paired with the recorded arrival times (ms after the request
    // started).
    const sseRows = (body, times) => parseSse(body).map((event, index) => (
      times === undefined || times[index] === undefined ? event : { ...event, at: times[index] }));
    const STREAMS = new WeakMap();
    function streamRows(response) {
      if (!STREAMS.has(response)) STREAMS.set(response, sseRows(response.body, response.stream && response.stream.times));
      return STREAMS.get(response);
    }
    // Text increment carried by one event of a model output stream, or "" when it carries none: OpenAI Chat
    // Completions (`choices[0].delta.content`), completions (`choices[0].text`), Responses
    // (`response.output_text.delta`), Anthropic Messages (`content_block_delta` with `delta.text`) and Gemini
    // (`candidates[0].content.parts[0].text`).
    function deltaText(data) {
      if (data === "" || data[0] !== "{") return "";
      let json;
      try { json = JSON.parse(data); } catch { return ""; }
      const field = (value, key) => (typeof value === "object" && value !== null ? value[key] : undefined);
      const first = (value) => (Array.isArray(value) ? value[0] : undefined);
      const choice = first(field(json, "choices"));
      const found = [
        field(field(choice, "delta"), "content"),
        field(choice, "text"),
        field(json, "type") === "response.output_text.delta" ? field(json, "delta") : undefined,
        field(json, "type") === "content_block_delta" ? field(field(json, "delta"), "text") : undefined,
        field(first(field(field(first(field(json, "candidates")), "content"), "parts")), "text"),
      ].find((value) => typeof value === "string" && value !== "");
      return found === undefined ? "" : found;
    }
    const DELTAS = new WeakMap();
    function rowText(row) {
      if (!DELTAS.has(row)) DELTAS.set(row, deltaText(row.data));
      return DELTAS.get(row);
    }

    // ------------------------------------------------------------ formatting
    const message = (err) => (err && err.message) || String(err);
    const pad = (n) => String(n).padStart(2, "0");
    const clock = (date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    const day = (date) => `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    const formatTime = (at) => { const date = new Date(at); return `${day(date)} ${clock(date)}:${pad(date.getSeconds())}`; };
    // `HH:mm:ss` for today, `MM-DD HH:mm` for other days.
    function shortTime(at) {
      const date = new Date(at);
      return date.toDateString() === new Date().toDateString() ? `${clock(date)}:${pad(date.getSeconds())}` : `${day(date)} ${clock(date)}`;
    }
    function humanSize(bytes) {
      if (!Number.isFinite(bytes)) return "-";
      if (bytes < 1024) return `${bytes} B`;
      const units = ["KB", "MB", "GB"];
      let value = bytes / 1024; let i = 0;
      while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
      return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
    }
    // Tone of a status: 2xx success, 3xx info, 4xx warning, 5xx and no status danger.
    const statusTone = (status) => (
      status === undefined ? "danger" : status < 300 ? "success" : status < 400 ? "info" : status < 500 ? "warning" : "danger");
    // Pretty-printed JSON when the text parses; otherwise the text unchanged.
    function prettyJson(text) {
      const trimmed = text.trim();
      if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return { text, json: false };
      try { return { text: JSON.stringify(JSON.parse(trimmed), null, 2), json: true }; } catch { return { text, json: false }; }
    }
    const sendShortcut = () => (/mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent) ? "⌘ Enter" : "Ctrl Enter");
    // Copies text to the clipboard: the async clipboard API, then a selection-based copy where that API is unavailable
    // or refused. Throws when both ways fail.
    async function copyText(text) {
      try { await navigator.clipboard.writeText(text); return; } catch { /* selection-based copy below */ }
      const area = h("textarea", { readonly: true, style: { position: "fixed", top: "0", left: "0", width: "1px", height: "1px", opacity: "0" } });
      area.value = text;
      document.body.appendChild(area);
      const active = document.activeElement;
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } finally { area.remove(); if (active instanceof HTMLElement) active.focus(); }
      if (!ok) throw new Error("clipboard unavailable");
    }
    const EXTENSIONS = [
      [/json/i, "json"], [/html/i, "html"], [/xml/i, "xml"], [/csv/i, "csv"], [/javascript/i, "js"], [/css/i, "css"], [/^text\//i, "txt"],
      [/png/i, "png"], [/jpe?g/i, "jpg"], [/gif/i, "gif"], [/webp/i, "webp"], [/svg/i, "svg"], [/pdf/i, "pdf"], [/zip/i, "zip"],
    ];
    // File name for a saved body: the URL's last path segment, with an extension from the content type when it has none.
    function saveName(url, contentType) {
      let name = "response";
      try {
        const segment = new URL(url).pathname.split("/").filter((part) => part !== "").pop();
        if (segment !== undefined) name = decodeURIComponent(segment).replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").slice(0, 80) || "response";
      } catch { /* the default name */ }
      if (/\.[A-Za-z0-9]{1,8}$/.test(name)) return name;
      const extension = EXTENSIONS.find(([pattern]) => pattern.test(contentType));
      return extension ? `${name}.${extension[1]}` : name;
    }
    // The body as a Blob: the complete binary body when the server returned it, else the decoded text.
    function bodyBlob(response) {
      const type = response.contentType.split(";")[0].trim() || "application/octet-stream";
      if (response.bodyBase64 !== undefined) return new Blob([Uint8Array.from(atob(response.bodyBase64), (c) => c.charCodeAt(0))], { type });
      return !response.binary && response.body !== "" ? new Blob([response.body], { type: `${type}; charset=utf-8` }) : undefined;
    }
    const escapeAttribute = (text) => text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
    const readSplit = () => {
      try {
        const value = Number(localStorage.getItem(SPLIT_KEY));
        return value >= SPLIT_MIN && value <= SPLIT_MAX ? value : 50;
      } catch { return 50; }
    };
    const readScope = () => { try { return localStorage.getItem(SCOPE_KEY); } catch { return null; } };

    // ------------------------------------------------------------ name/value rows
    // Rows as bulk-edit text: one `name: value` per line, switched-off rows behind `# `.
    const rowsToBulk = (rows) => rows.map((row) => `${row.enabled === false ? "# " : ""}${row.key}: ${row.value}`).join("\n");
    // Bulk-edit text as rows: `name: value` or `name=value` per line; `#` switches a line off; blank lines are skipped.
    function bulkToRows(text) {
      const rows = [];
      for (const raw of text.split(/\r?\n/)) {
        const off = raw.trim().startsWith("#");
        const line = off ? raw.trim().slice(1).trim() : raw.trim();
        if (line === "") continue;
        const marks = [line.indexOf(":"), line.indexOf("=")].filter((at) => at >= 0);
        const index = marks.length ? Math.min(...marks) : -1;
        const row = { key: index < 0 ? line : line.slice(0, index).trim(), value: index < 0 ? "" : line.slice(index + 1).trim() };
        rows.push(off ? { ...row, enabled: false } : row);
      }
      return rows;
    }
    const sent = (row) => row.key.trim() !== "" && row.enabled !== false;
    // Enabled rows with a name, in order, repeated names included.
    const rowsToPairs = (rows) => rows.filter(sent).map((row) => [row.key.trim(), row.value]);
    // Enabled rows with a name, as a record; a repeated name keeps its last value.
    const rowsToRecord = (rows) => Object.fromEntries(rowsToPairs(rows));
    const recordToRows = (value) => toPairs(value).map(([key, rowValue]) => ({ key, value: rowValue }));
    const storedRows = (rows) => rows.map((row) => ({ key: row.key, value: row.value, enabled: row.enabled !== false }));

    // ------------------------------------------------------------ request forms
    // A form is the fields of a saved request edited in the panel: method, path, query, headers, auth, bodyMode, body,
    // form.
    const storedForm = (state) => ({ method: state.method, path: state.path, query: storedRows(state.query), headers: storedRows(state.headers),
      auth: state.auth, bodyMode: state.bodyMode, body: state.body, form: storedRows(state.form) });
    const blankAuth = (type) => ({ none: NO_AUTH, bearer: { type, token: "" }, basic: { type, username: "", password: "" },
      header: { type, name: "", value: "" }, query: { type, name: "", value: "" } }[type]);
    const contentTypeOf = (pairs) => (pairs.find(([name]) => name.toLowerCase() === "content-type") || ["", ""])[1];
    // The form reproducing a recorded exchange; credentials are not part of a record.
    function formFromExchange(exchange) {
      const request = exchange.request;
      let bodyMode = "none";
      if (request.body !== "") {
        const urlencoded = /x-www-form-urlencoded/i.test(contentTypeOf(Object.entries(request.headers)));
        bodyMode = urlencoded ? "form" : prettyJson(request.body).json ? "json" : "text";
      }
      return { method: request.method, path: request.path, query: recordToRows(request.query), headers: recordToRows(request.headers), auth: NO_AUTH,
        bodyMode, body: bodyMode === "form" ? "" : request.body,
        form: bodyMode === "form" ? recordToRows([...new URLSearchParams(request.body).entries()]) : [] };
    }
    // A full URL rewritten as a path below `baseUrl`; unchanged when it lies elsewhere.
    function pathBelow(baseUrl, path) {
      try {
        const full = joinUrl("", path, []);
        const base = new URL(baseUrl);
        const basePath = base.pathname.replace(/\/+$/, "");
        if (full.origin !== base.origin || !(full.pathname === basePath || full.pathname.startsWith(`${basePath}/`))) return path;
        return (full.pathname.slice(basePath.length) || "/") + full.search;
      } catch { return path; }
    }
    // Origin of a full request URL; empty when it does not parse.
    const originOf = (path) => { try { return joinUrl("", path, []).origin; } catch { return ""; } };
    // The form of a parsed cURL command: query split into rows, the URL made relative to the target when it lies
    // below it.
    function formFromCurl(parsed, target) {
      const { path: bare, pairs } = splitQuery(parsed.url);
      const form = parsed.bodyKind === "form";
      return {
        method: parsed.method, path: target.id === DIRECT ? bare : pathBelow(target.baseUrl, bare), query: recordToRows(pairs),
        // The form mode sets its own content type.
        headers: recordToRows(form ? parsed.headers.filter(([name]) => name.toLowerCase() !== "content-type") : parsed.headers),
        auth: parsed.basic ? { type: "basic", ...parsed.basic } : NO_AUTH,
        bodyMode: form ? "form" : parsed.bodyKind === "raw" ? (/json/i.test(contentTypeOf(parsed.headers)) ? "json" : "text") : "none",
        body: parsed.bodyKind === "raw" ? parsed.body : "", form: form ? recordToRows(parsed.fields) : [],
      };
    }
    // The request the server receives for a form.
    function toRequestInput(state) {
      const headers = rowsToRecord(state.headers);
      const typed = Object.keys(headers).some((name) => name.toLowerCase() === "content-type");
      const defaultType = (value) => { if (!typed) headers["content-type"] = value; };
      let body;
      if (state.method !== "GET" && state.method !== "HEAD") {
        if ((state.bodyMode === "json" || state.bodyMode === "text") && state.body !== "") {
          body = state.body;
          defaultType(state.bodyMode === "json" ? "application/json; charset=utf-8" : "text/plain; charset=utf-8");
        } else if (state.bodyMode === "form") {
          body = new URLSearchParams(rowsToPairs(state.form)).toString();
          defaultType("application/x-www-form-urlencoded; charset=utf-8");
        }
      }
      return { method: state.method, path: state.path, query: rowsToPairs(state.query), headers, body,
        ...(state.auth.type === "none" ? {} : { auth: state.auth }) };
    }
    // URL the server will request for a form (query auth excluded): `{ url }`, or `{ error }` when it cannot be built.
    function previewUrl(target, state) {
      const vars = target.variables;
      // A request without a target has nothing to preview until a URL is typed.
      if (target.baseUrl === "" && state.path.trim() === "") return { url: "" };
      try {
        const query = rowsToPairs(state.query).map(([name, value]) => [substitute(name, vars), substitute(value, vars)]);
        return { url: joinUrl(target.baseUrl, substitute(state.path.trim(), vars), query).toString() };
      } catch (err) { return { error: message(err) }; }
    }
    const base64 = (text) => btoa(String.fromCharCode(...new TextEncoder().encode(text)));
    // The request as a cURL command: the target's fixed headers and the request's own authentication included, the
    // target's credentials left out (the browser never holds them). Undefined while the URL cannot be built.
    function curlOf(target, state) {
      const preview = previewUrl(target, state);
      if (!preview.url) return undefined;
      const vars = target.variables;
      const input = toRequestInput(state);
      const url = new URL(preview.url);
      const headers = [...Object.entries(target.headers), ...Object.entries(input.headers).map(([name, value]) => [name, substitute(value, vars)])];
      const auth = target.auth.type === "none" ? state.auth : NO_AUTH;
      if (auth.type === "bearer" && auth.token !== "") headers.push(["Authorization", `Bearer ${auth.token}`]);
      if (auth.type === "basic" && auth.username !== "") headers.push(["Authorization", `Basic ${base64(`${auth.username}:${auth.password}`)}`]);
      if (auth.type === "header" && auth.name !== "" && auth.value !== "") headers.push([auth.name, auth.value]);
      if (auth.type === "query" && auth.name !== "" && auth.value !== "") url.searchParams.set(auth.name, auth.value);
      return toCurl({ method: state.method, url: url.toString(), headers,
        body: input.body === undefined ? undefined : substitute(input.body, vars) });
    }
    // Path and query of a recorded request; the composed path when no URL was built.
    function requestLabel(entry) {
      const url = entry.request.url;
      if (url === "") return entry.request.path || "/";
      try { const parsed = new URL(url); return parsed.pathname + parsed.search; } catch { return url; }
    }

    return {
      // The pure functions of the module; the page reads nothing from here.
      lib: { SseParser, parseSse, isEventStream, sseRows, deltaText, tokenize, parseCurl, splitQuery, toCurl, joinUrl, substitute,
        rowsToBulk, bulkToRows, toRequestInput, previewUrl, curlOf, formFromCurl, formFromExchange, pathBelow, saveName },
      apply(ctx) {
        const t = L[ctx.locale] || L.en;
        const style = document.createElement("style");
        style.textContent = `
          .hc-page { --hc-ok: var(--success); --hc-warn: var(--warn); display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0 24px 16px; font-size: 13px; }
          .hc-page .pageHead { flex: none; align-items: center; padding: 18px 0 10px; }
          .hc-page .headTools { font-size: 12px; color: var(--label-secondary); }
          .hc-banner { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; padding: 7px 12px; border-radius: 8px; font-size: 12.5px; line-height: 18px; flex: none; background: var(--hover); color: var(--label-secondary); }
          .hc-banner > span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
          .hc-banner[data-kind="ok"] { background: color-mix(in srgb, var(--hc-ok) 10%, transparent); color: var(--hc-ok); }
          .hc-banner[data-kind="error"] { background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); }
          .hc-paneBody > .hc-banner { margin: 0; }
          .hc-body { display: flex; flex: 1; min-height: 0; border: 0.5px solid var(--border-l2); border-radius: 10px; overflow: hidden; }
          .hc-spacer { flex: 1; }
          .hc-side { display: flex; flex-direction: column; width: 236px; flex: none; min-height: 0; border-right: 0.5px solid var(--border-l2); background: var(--bg-layer-1); }
          .hc-sideTop { display: flex; flex-direction: column; gap: 8px; padding: 10px; border-bottom: 0.5px solid var(--border-l2); flex: none; }
          .hc-targetRow { display: flex; gap: 6px; align-items: center; }
          .hc-targetRow .selectWrap { flex: 1; min-width: 0; }
          .hc-select { height: 30px; padding: 0 26px 0 8px; border-radius: 8px; font-size: 12.5px; }
          .hc-page .selectWrap .chev { top: 7px; right: 7px; }
          .hc-targetSelect { font-weight: 600; }
          .hc-version { width: auto; max-width: 150px; height: 24px; border-radius: 6px; font-size: 11.5px; font-variant-numeric: tabular-nums; }
          .hc-version + .chev { top: 4px; }
          .hc-boxed { width: 30px; height: 30px; box-shadow: inset 0 0 0 0.5px var(--border-l2); }
          .hc-targetInfo { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; min-width: 0; }
          .hc-targetUrl { font: 11.5px var(--mono); color: var(--label-secondary); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .hc-targetMeta { font-size: 11px; color: var(--label-tertiary); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .hc-targetMeta[data-wrap] { white-space: normal; line-height: 1.5; }
          .hc-targetInfo .hc-link { padding-left: 0; }
          .hc-sideTabs { display: flex; align-items: center; gap: 2px; flex: none; padding: 0 6px; border-bottom: 0.5px solid var(--border-l2); min-height: 34px; }
          .hc-sideFilter { padding: 8px 10px; flex: none; }
          .hc-input { height: 28px; padding: 0 8px; border-radius: 8px; font-size: 12.5px; }
          .hc-input.mono { font-size: 12.5px; }
          .hc-list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 6px 6px; display: flex; flex-direction: column; gap: 1px; }
          .hc-hint { font-size: 12px; line-height: 1.5; color: var(--label-tertiary); padding: 10px 6px; }
          .hc-item { position: relative; display: flex; flex: none; border-radius: 7px; }
          .hc-item:hover { background: var(--hover); }
          .hc-item[data-active] { background: color-mix(in srgb, var(--info) 12%, transparent); }
          .hc-itemMain { flex: 1; min-width: 0; min-height: 28px; display: flex; flex-direction: column; justify-content: center; gap: 2px; padding: 5px 8px; border: none; border-radius: 7px; background: none; text-align: left; }
          .hc-itemLine { display: flex; align-items: center; gap: 6px; min-width: 0; }
          .hc-itemLine[data-sub] { font-size: 11px; color: var(--label-tertiary); font-variant-numeric: tabular-nums; }
          .hc-itemPath { font: 12px var(--mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
          .hc-itemPath[data-named] { font-family: inherit; font-size: 12.5px; }
          .hc-itemActions, .hc-itemMenu { position: absolute; top: 2px; right: 4px; display: flex; gap: 1px; opacity: 0; border-radius: 6px; background: var(--bg-layer-2); }
          .hc-item:hover :is(.hc-itemActions, .hc-itemMenu), .hc-item:focus-within :is(.hc-itemActions, .hc-itemMenu), .hc-item[data-menu-open] .hc-itemMenu { opacity: 1; }
          .hc-menu { position: absolute; top: 26px; right: 0; z-index: 5; min-width: 120px; display: flex; flex-direction: column; padding: 4px; border-radius: 8px; border: 0.5px solid var(--border-l2); background: var(--bg-layer-3); box-shadow: 0 8px 24px rgba(0, 0, 0, .22); }
          .hc-menu button { padding: 6px 10px; border: none; border-radius: 6px; background: none; font-size: 12.5px; text-align: left; white-space: nowrap; }
          .hc-menu button:hover { background: var(--hover); }
          .hc-menu button[data-danger] { color: var(--error); }
          .hc-renameInput { flex: 1; min-width: 0; height: 22px; padding: 0 6px; border-radius: 6px; }
          .hc-sideFoot { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-top: 0.5px solid var(--border-l2); font-size: 11.5px; color: var(--label-tertiary); flex: none; }
          .hc-sideFoot label { display: inline-flex; align-items: center; gap: 4px; }
          .hc-limit { width: 58px; height: 22px; padding: 0 4px; border-radius: 6px; font-size: 11.5px; }
          .hc-methodText, .hc-methodTag { font-family: var(--mono); font-weight: 700; color: var(--label-secondary); }
          .hc-methodText { font-size: 10.5px; flex: none; min-width: 34px; }
          .hc-methodTag { font-size: 11.5px; padding: 1px 6px; border-radius: 5px; background: var(--hover); }
          .hc-page [data-method="GET"] { color: var(--hc-ok); }
          .hc-page [data-method="POST"] { color: var(--hc-warn); }
          .hc-page [data-method="PUT"], .hc-page [data-method="PATCH"] { color: var(--info); }
          .hc-page [data-method="DELETE"] { color: var(--error); }
          .hc-statusText { font-weight: 700; }
          .hc-statusText[data-tone="success"] { color: var(--hc-ok); }
          .hc-statusText[data-tone="info"] { color: var(--info); }
          .hc-statusText[data-tone="warning"] { color: var(--hc-warn); }
          .hc-statusText[data-tone="danger"] { color: var(--error); }
          .hc-page .tag { font-variant-numeric: tabular-nums; }
          .hc-sourceTag { font-size: 10.5px; padding: 0 5px; border-radius: 4px; background: var(--hover); color: var(--label-secondary); line-height: 16px; white-space: nowrap; }
          .hc-sourceTag[data-source="agent"] { color: var(--info); }
          .hc-panesWrap { flex: 1; min-width: 0; min-height: 0; display: flex; container-type: inline-size; }
          .hc-panes { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: row; }
          .hc-pane { position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
          .hc-pane[data-pane="request"] { flex: 0 0 var(--hc-split, 50%); }
          .hc-pane[data-pane="response"] { flex: 1 1 0; }
          .hc-divider { --line: var(--border-l2); --from: 4px; --to: 5px; flex: none; width: 9px; margin: 0 -4px; z-index: 1; cursor: col-resize; background: linear-gradient(to right, transparent var(--from), var(--line) var(--from), var(--line) var(--to), transparent var(--to)); touch-action: none; }
          .hc-divider:hover, .hc-divider:active { --line: var(--info); --from: 3px; --to: 6px; }
          @container (max-width: 720px) {
            .hc-panes { flex-direction: column; }
            .hc-divider { width: auto; height: 9px; margin: -4px 0; cursor: row-resize; background: linear-gradient(to bottom, transparent var(--from), var(--line) var(--from), var(--line) var(--to), transparent var(--to)); }
          }
          .hc-paneHead { display: flex; align-items: center; gap: 8px; flex: none; min-height: 46px; padding: 8px 10px; border-bottom: 0.5px solid var(--border-l2); min-width: 0; }
          .hc-tabs { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; flex: none; padding: 0 8px; border-bottom: 0.5px solid var(--border-l2); min-height: 34px; }
          .hc-tabs > .hc-link { margin-left: 6px; }
          .hc-tabs > .hc-segments { margin: 4px 0; }
          .hc-tab { display: inline-flex; align-items: center; gap: 6px; padding: 8px 9px 7px; border: none; border-bottom: 2px solid transparent; background: none; color: var(--label-secondary); font-size: 12.5px; white-space: nowrap; }
          .hc-tab:hover { color: var(--label-primary); }
          .hc-tab[aria-selected="true"] { color: var(--label-primary); border-bottom-color: var(--info); font-weight: 600; }
          .hc-count { font-size: 10.5px; font-weight: 600; padding: 0 6px; border-radius: 999px; background: var(--hover); color: var(--label-secondary); line-height: 16px; }
          .hc-paneBody { flex: 1; min-height: 0; overflow: auto; padding: 10px; display: flex; flex-direction: column; gap: 10px; }
          .hc-paneBody[data-center] { align-items: center; justify-content: center; }
          .hc-empty { padding: 28px 12px; text-align: center; font-size: 12.5px; color: var(--label-tertiary); }
          .hc-hints { display: flex; flex-direction: column; align-items: center; gap: 12px; color: var(--label-tertiary); font-size: 12.5px; text-align: center; }
          .hc-hintRow { display: inline-flex; align-items: center; gap: 10px; }
          .hc-kbd { font: 11.5px var(--mono); padding: 2px 7px; border-radius: 5px; border: 0.5px solid var(--border-l2); background: var(--bg-layer-2); color: var(--label-secondary); }
          .hc-urlBar { gap: 0; margin: 0; }
          .hc-method { width: auto; height: 30px; padding: 0 24px 0 8px; border-color: var(--border-l2); border-right: none; border-radius: 8px 0 0 8px; font: 700 12px/20px var(--mono); }
          .hc-urlBox { display: flex; align-items: center; flex: 1; min-width: 0; height: 30px; border: 0.5px solid var(--border-l2); background: var(--bg-layer-1); overflow: hidden; }
          .hc-urlBar:focus-within .hc-urlBox { border-color: var(--info); }
          .hc-baseUrl { flex: 0 1 auto; max-width: 62%; padding-left: 8px; font: 12.5px var(--mono); color: var(--label-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; direction: rtl; text-align: left; }
          .hc-urlBox:focus-within .hc-baseUrl { max-width: 32%; }
          .hc-pathInput { flex: 1; min-width: 60px; height: 100%; padding: 0 8px 0 1px; border: none; outline: none; background: transparent; color: var(--label-primary); font: 12.5px var(--mono); }
          .hc-pathInput[data-direct] { padding-left: 8px; }
          .hc-pathInput::placeholder { color: var(--label-tertiary); }
          .hc-send { height: 30px; padding: 0 16px; border-radius: 0 8px 8px 0; font-size: 13px; font-weight: 600; white-space: nowrap; }
          .hc-label { font-size: 11px; font-weight: 600; letter-spacing: .02em; text-transform: uppercase; color: var(--label-tertiary); }
          .hc-previewBox { display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; border-radius: 8px; background: var(--hover); flex: none; }
          .hc-previewHead { display: flex; align-items: center; gap: 8px; }
          .hc-previewUrl { font: 12px/1.5 var(--mono); word-break: break-all; color: var(--label-secondary); }
          .hc-previewUrl[data-error] { color: var(--error); }
          .hc-toolRow { display: flex; align-items: center; gap: 10px; flex: none; }
          .hc-editor { flex: 1; min-height: 140px; width: 100%; resize: none; padding: 10px; border: 0.5px solid var(--border-l2); border-radius: 8px; outline: none; background: var(--bg-layer-1); color: var(--label-primary); font: 12.5px/1.5 var(--mono); tab-size: 2; }
          .hc-editor:focus { border-color: var(--info); }
          .hc-editor::placeholder { color: var(--label-tertiary); }
          .hc-editor:disabled { opacity: .6; }
          .hc-block { display: flex; flex-direction: column; gap: 6px; flex: none; }
          .hc-note { margin: 0; font-size: 12px; line-height: 1.5; color: var(--label-tertiary); overflow-wrap: anywhere; }
          .hc-meta { font-size: 11.5px; color: var(--label-tertiary); font-variant-numeric: tabular-nums; white-space: nowrap; }
          .hc-code { margin: 0; padding: 10px 12px; border-radius: 8px; background: var(--hover); font: 12px/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
          .hc-headersTable { border-collapse: collapse; font: 12px var(--mono); width: 100%; }
          .hc-headersTable th, .hc-headersTable td { padding: 4px 0; border-bottom: 0.5px solid var(--border-l2); vertical-align: top; }
          .hc-headersTable tr:last-child th, .hc-headersTable tr:last-child td { border-bottom: none; }
          .hc-headersTable th { text-align: left; font-weight: 600; color: var(--label-secondary); padding-right: 14px; white-space: nowrap; width: 1%; }
          .hc-headersTable td { word-break: break-all; }
          .hc-overlay { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; background: color-mix(in srgb, var(--bg-base) 82%, transparent); font-size: 13px; color: var(--label-secondary); font-variant-numeric: tabular-nums; }
          .hc-spinner { width: 22px; height: 22px; flex: none; border-radius: 50%; border: 2px solid var(--border-l2); border-top-color: var(--info); animation: hc-spin .8s linear infinite; }
          .hc-spinner[data-small] { width: 12px; height: 12px; }
          @keyframes hc-spin { to { transform: rotate(360deg); } }
          @media (prefers-reduced-motion: reduce) { .hc-spinner { animation-duration: 2.4s; } }
          .hc-sse { display: flex; flex-direction: column; gap: 8px; flex: 1; min-height: 160px; }
          .hc-sseScroll { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
          .hc-sseRow { border-radius: 6px; flex: none; }
          .hc-sseRow[data-open] { background: var(--hover); }
          .hc-sseHead { display: grid; grid-template-columns: 34px 58px minmax(56px, max-content) minmax(0, 1fr); align-items: baseline; gap: 8px; width: 100%; padding: 4px 6px; border: none; border-radius: 6px; background: none; font-size: 12px; text-align: left; }
          .hc-sseHead:hover { background: var(--hover); }
          .hc-sseIndex, .hc-sseTime { color: var(--label-tertiary); font-variant-numeric: tabular-nums; font-size: 11px; }
          .hc-sseIndex { text-align: right; }
          .hc-sseType { font: 11px var(--mono); padding: 0 5px; border-radius: 4px; background: var(--hover); color: var(--label-secondary); white-space: nowrap; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
          .hc-sseType[data-named] { color: var(--info); }
          .hc-sseData { font-family: var(--mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
          .hc-sseDetail { display: flex; flex-direction: column; gap: 4px; padding: 0 6px 6px 48px; }
          .hc-sseDetail .hc-code { background: var(--bg-base); }
          .hc-sseText { font-family: inherit; font-size: 13px; line-height: 1.6; }
          .hc-imageBox { display: flex; align-items: flex-start; justify-content: center; padding: 12px; border-radius: 8px; background: var(--hover); overflow: auto; }
          .hc-image { max-width: 100%; height: auto; }
          .hc-frame { flex: 1; min-height: 240px; width: 100%; border: 0.5px solid var(--border-l2); border-radius: 8px; background: #fff; }
          .hc-kv { display: flex; flex-direction: column; gap: 4px; flex: none; }
          .hc-kvTools { display: flex; align-items: center; gap: 12px; min-height: 22px; }
          .hc-kvTools .hc-link { padding-left: 0; }
          .hc-bulk { min-height: 120px; flex: none; resize: vertical; }
          .hc-kvRow { display: grid; grid-template-columns: minmax(70px, 2fr) minmax(90px, 3fr) 24px; gap: 6px; align-items: center; }
          .hc-kv[data-toggle] .hc-kvRow { grid-template-columns: 16px minmax(70px, 2fr) minmax(90px, 3fr) 24px; }
          .hc-kvRow[data-off] .hc-input { opacity: .5; text-decoration: line-through; }
          .hc-kvRow[data-ghost] :is(.hc-check, .iconButton) { visibility: hidden; }
          .hc-authEditor { display: flex; flex-direction: column; gap: 10px; flex: none; }
          .hc-link { padding: 2px 4px; border: none; border-radius: 4px; background: none; color: var(--info); font-size: 12px; white-space: nowrap; }
          .hc-link:hover:not(:disabled) { text-decoration: underline; }
          .hc-link:disabled { opacity: .5; }
          .hc-link[data-danger], .hc-danger:hover:not(:disabled) { color: var(--error); }
          .hc-accent { color: var(--info); }
          .hc-segments { display: inline-flex; flex: none; border: 0.5px solid var(--border-l2); border-radius: 8px; overflow: hidden; }
          .hc-field > .hc-segments { align-self: flex-start; }
          .hc-segment { padding: 4px 10px; border: none; background: transparent; color: var(--label-secondary); font-size: 12px; white-space: nowrap; }
          .hc-segments[data-small] .hc-segment { padding: 2px 8px; font-size: 11.5px; }
          .hc-segment + .hc-segment { border-left: 0.5px solid var(--border-l2); }
          .hc-segment:hover:not(:disabled) { background: var(--hover); }
          .hc-segment[aria-checked="true"] { background: var(--hover); color: var(--label-primary); font-weight: 600; }
          .hc-segment:disabled { opacity: .5; }
          .hc-checkRow { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 12.5px; }
          .hc-check { width: 15px; height: 15px; margin: 0; accent-color: var(--info); }
          .hc-form { display: flex; flex-direction: column; gap: 12px; padding: 4px 4px 8px; font-size: 13px; }
          .hc-form .input { margin: 0; width: 100%; }
          .hc-formPart { display: flex; flex-direction: column; gap: 12px; }
          .hc-formPart > .hc-link { align-self: flex-start; padding-left: 0; }
          .hc-formRow { display: flex; gap: 12px; }
          .hc-formRow > .hc-field { flex: 1; min-width: 0; }
          .hc-field { display: flex; flex-direction: column; gap: 5px; }
          .hc-fieldLabel { font-size: 12px; font-weight: 600; color: var(--label-secondary); }
          .hc-fieldHint { font-size: 11.5px; color: var(--label-tertiary); line-height: 1.5; }
          .hc-formError { padding: 8px 10px; border-radius: 8px; font-size: 12.5px; background: color-mix(in srgb, var(--error) 8%, transparent); color: var(--error); overflow-wrap: anywhere; flex: none; }
        `;
        document.head.appendChild(style);
        ctx.effect(() => style.remove());

        // ------------------------------------------------------------ API
        async function readJson(res) {
          let body;
          try { body = await res.json(); } catch { /* no JSON body */ }
          if (res.ok) return body === undefined ? {} : body;
          // FastAPI: a string from HTTPException, a list of { loc, msg } from request validation.
          const detail = body && body.detail;
          const issue = (item) => (item && item.msg ? `${(item.loc || []).slice(1).join(".")}: ${item.msg}` : "");
          const listed = Array.isArray(detail) ? detail.map(issue).filter(Boolean).join("; ") : "";
          // A 404 that carries no message of the plugin comes from the router: the routes are not registered.
          if (res.status === 404 && (typeof detail !== "string" || detail === "Not Found")) throw new Error(t.errorDisabled);
          throw new Error(typeof detail === "string" ? detail : listed || `HTTP ${res.status}`);
        }
        const call = async (path, opts) => readJson(await fetch(API + path,
          { headers: { "content-type": "application/json" }, cache: "no-store", ...(opts || {}) }));
        const write = (method, path, body, opts) => call(path,
          { method, body: body === undefined ? undefined : JSON.stringify(body), ...(opts || {}) });
        const byId = (path, id) => `${path}?id=${encodeURIComponent(id)}`;
        const inScope = (path, scope) => `${path}?target=${encodeURIComponent(scope)}`;
        // Sends a request. The server answers in lines: for an event stream the head and each event as it arrives
        // (`handlers`), then the exchange. Aborting `signal` closes the connection; the server stops the outgoing
        // request and records what arrived. A reply that is not line-delimited carries the exchange alone.
        async function sendRequest(id, request, signal, handlers) {
          const res = await fetch(`${API}/send`, { method: "POST", headers: { "content-type": "application/json", accept: "application/x-ndjson" },
            body: JSON.stringify({ id, request }), cache: "no-store", signal });
          if (!res.ok || !res.body || !/ndjson/i.test(res.headers.get("content-type") || "")) return (await readJson(res)).exchange;
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = ""; let exchange;
          const take = (text) => {
            if (text.trim() === "") return;
            const line = JSON.parse(text);
            if (line.type === "head") handlers.onHead(line.head);
            else if (line.type === "event") handlers.onEvent(line.event, line.at);
            else if (line.type === "done") exchange = line.exchange;
            else throw new Error(line.error);
          };
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            for (let index = buffer.indexOf("\n"); index >= 0; index = buffer.indexOf("\n")) {
              take(buffer.slice(0, index));
              buffer = buffer.slice(index + 1);
            }
          }
          take(buffer);
          if (exchange === undefined) throw new Error(t.errorIncomplete);
          return exchange;
        }

        // ------------------------------------------------------------ shared pieces
        function modal(inner, wide, onClose) {
          const el = h("div", { class: "modal" });
          el.innerHTML = `<div class="modalCard${wide ? "" : " narrow"}" role="dialog" aria-modal="true">${inner}</div>`;
          document.body.appendChild(el);
          const close = () => { el.remove(); document.removeEventListener("keydown", onKey, true); onClose(); };
          const onKey = (e) => { if (e.key === "Escape") close(); };
          document.addEventListener("keydown", onKey, true);
          el.addEventListener("mousedown", (e) => { if (e.target === el) close(); });
          return { el, close };
        }
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
        const paneBody = (box) => [...box.children].find((node) => node.classList.contains("hc-paneBody"));
        // Replaces the children of a pane; with `keep` its body stays scrolled where it was.
        function rebuild(box, nodes, keep) {
          const before = paneBody(box);
          const top = keep && before ? before.scrollTop : 0;
          redraw(box, () => box.replaceChildren(...nodes.filter(Boolean)));
          if (top) paneBody(box).scrollTop = top;
        }
        const spacer = () => h("span", { class: "hc-spacer" });
        const note = (text) => h("div", { class: "hc-note" }, text);
        const empty = (text) => h("div", { class: "hc-empty" }, text);
        const tag = (text, tone) => h("span", { class: "tag", "data-tone": tone || "outline" }, text);
        const statusTag = (head) => tag(`${head.status} ${head.statusText}`, statusTone(head.status));
        const methodText = (method) => h("span", { class: "hc-methodText", "data-method": method }, method);
        const table = (pairs) => h("table", { class: "hc-headersTable" },
          h("tbody", null, pairs.map(([name, value]) => h("tr", null, h("th", null, name), h("td", null, value)))));
        const block = (label, ...children) => h("div", { class: "hc-block" }, h("span", { class: "hc-label" }, label), children);
        const field = (label, control, attrs) => h("label", { class: "hc-field", ...(attrs || {}) },
          h("span", { class: "hc-fieldLabel" }, label), control);
        const sendHint = () => h("span", { class: "hc-hintRow" }, h("span", null, t.requestSend), h("kbd", { class: "hc-kbd" }, sendShortcut()));
        const selectBox = (select) => h("span", { class: "selectWrap" }, select, ico("chev-down", "ico chev"));
        // One-of-many buttons; `options` are [value, label] pairs.
        const segments = (name, options, current, onPick, opts = {}) => h("div",
          { class: "hc-segments", role: "radiogroup", "aria-label": opts.label, "data-small": opts.small },
          options.map(([value, label]) => h("button",
            { type: "button", role: "radio", class: "hc-segment", "data-k": `${name}:${value}`,
            "aria-checked": String(current === value),
            disabled: opts.disabled, onClick: () => { if (current !== value) onPick(value); } }, label)));
        // Copies the text and shows the copied label on the button for a moment.
        async function copyFlash(button, text, label) {
          try { await copyText(text); } catch { return; }
          button.textContent = t.responseCopied;
          setTimeout(() => { button.textContent = label; }, 1500);
        }
        function authLabel(auth) {
          if (auth.type === "bearer") return `Bearer ${auth.hint}`;
          if (auth.type === "basic") return `Basic ${auth.username}`;
          if (auth.type === "header") return `${auth.name}: ${auth.hint}`;
          return auth.type === "query" ? `?${auth.name}=${auth.hint}` : t.auth.none;
        }
        function authSummary(auth) {
          const rows = [[t.formAuth, t.auth[auth.type]]];
          if (auth.type === "bearer") rows.push([t.authToken, auth.hint]);
          if (auth.type === "basic") rows.push([t.authUsername, auth.username], [t.authPassword, "••••••"]);
          if (auth.type === "header") rows.push([t.authHeaderName, auth.name], [t.authValue, auth.hint]);
          if (auth.type === "query") rows.push([t.authQueryName, auth.name], [t.authValue, auth.hint]);
          return rows;
        }
        // The fields of one authentication type; `read` and `write` address them as token, username, password, name
        // and value.
        function authFields(type, read, write, opts) {
          const input = (name, attrs) => h("input",
            { class: "input hc-input mono", "data-k": `auth:${name}`, value: read(name),
            disabled: opts.disabled, autocomplete: "off",
            autocapitalize: "off", spellcheck: "false", ...(attrs || {}), onInput: (e) => write(name, e.target.value) });
          const secret = (name) => input(name, { type: opts.reveal ? "text" : "password", autocomplete: opts.autocomplete, placeholder: opts.keep });
          if (type === "bearer") return [field(t.authToken, secret("token"))];
          if (type === "basic") return [h("div", { class: "hc-formRow" }, field(t.authUsername, input("username")),
            field(t.authPassword, secret("password")))];
          if (type === "none") return [];
          return [h("div", { class: "hc-formRow" },
            field(type === "header" ? t.authHeaderName : t.authQueryName,
              input("name", { placeholder: type === "header" ? "X-API-Key" : "api_key" })),
            field(t.authValue, secret("value"), { style: { flex: "2" } }))];
        }
        // Name/value rows. A blank row always follows the last one and typing in it adds the row; `view.text` holds the
        // bulk text while bulk editing is on. Typing never replaces the input it happens in.
        function kvEditor({ name, rows, onChange, view, toggle, tools, disabled }) {
          let list = rows; let wipe = null;
          const root = h("div", { class: "hc-kv", "data-toggle": toggle });
          const emit = (next) => { list = next; if (wipe) wipe.disabled = disabled || !next.length; onChange(next); };
          function rowNode(index) {
            const real = index < list.length;
            const row = real ? list[index] : { key: "", value: "" };
            const update = (patch) => {
              if (index < list.length) { emit(list.map((item, i) => (i === index ? { ...item, ...patch } : item))); return; }
              emit([...list, { key: "", value: "", ...patch }]);
              node.removeAttribute("data-ghost");
              for (const control of [check, remove]) if (control) control.disabled = disabled;
              root.append(rowNode(list.length));
            };
            const check = toggle ? h("input", { type: "checkbox", class: "hc-check", "data-k": `${name}:${index}:on`,
              checked: row.enabled !== false, disabled: disabled || !real, "aria-label": t.kvEnabled,
              onChange: () => { update({ enabled: check.checked }); node.toggleAttribute("data-off", !check.checked); } }) : null;
            const input = (part, key, placeholder) => h("input",
              { class: "input hc-input mono", "data-k": `${name}:${index}:${part}`,
              "data-kv-name": part === "k", value: row[key],
              placeholder, disabled, autocapitalize: "off", autocomplete: "off", spellcheck: "false",
              onInput: (e) => update({ [key]: e.target.value }) });
            const remove = h("button", { type: "button", class: "iconButton sm hc-danger", title: t.kvRemove,
              "aria-label": t.kvRemove, disabled: disabled || !real,
              onClick: () => { emit(list.filter((_, i) => i !== index)); draw(); } }, ico("x"));
            const node = h("div", { class: "hc-kvRow", "data-off": row.enabled === false, "data-ghost": !real }, check,
              input("k", "key", t.kvKey), input("v", "value", t.kvValue), remove);
            return node;
          }
          function draw() {
            const bulk = view.text !== undefined;
            const area = bulk ? h("textarea", { class: "hc-editor hc-bulk", "data-k": `${name}:bulk`, disabled,
              spellcheck: "false", "aria-label": t.kvBulk, placeholder: "name: value",
              onInput: () => { view.text = area.value; emit(bulkToRows(area.value)); } }, view.text) : null;
            wipe = tools ? h("button", { type: "button", class: "hc-link", "data-danger": true,
              "data-k": `${name}:wipe`, disabled: disabled || !list.length,
              onClick: () => { if (view.text !== undefined) view.text = ""; emit([]); draw(); } }, t.kvDeleteAll) : null;
            const bar = tools ? h("div", { class: "hc-kvTools" },
              h("button", { type: "button", class: "hc-link", "data-k": `${name}:add`, disabled: disabled || bulk,
                onClick: () => root.querySelector("[data-ghost] [data-kv-name]").focus() }, `+ ${t.kvAdd}`),
              h("button", { type: "button", class: "hc-link", "data-k": `${name}:mode`, disabled,
                onClick: () => { view.text = bulk ? undefined : rowsToBulk(list); draw(); } },
                bulk ? t.kvTable : t.kvBulk),
              spacer(), wipe) : null;
            const content = bulk ? [area, h("span", { class: "hc-note" },
              t.kvBulkHint)] : [...list.map((_, index) => rowNode(index)), rowNode(list.length)];
            redraw(root, () => root.replaceChildren(...[bar, ...content].filter(Boolean)));
          }
          draw();
          return root;
        }

        // ------------------------------------------------------------ page
        function page(el) {
          let alive = true; let dialog = null; let scopeGen = 0; let newest; let pollTimer = 0; let focusAfterLoad = false;
          // Set by the pane on display: the derived parts of the request form, and the growth of the live event stream.
          let syncForm = () => {}; let liveSync = null;
          // Pending autosave timers by request id.
          const saveTimers = new Map();
          const st = { targets: [], scopeId: DIRECT, agentTools: false, historyLimit: null, banner: null, testing: false, loaded: false,
            requests: [], selected: {}, shown: {}, history: [], sideTab: "requests", requestFilter: "", historyFilter: "", requestTab: "params",
            responseTab: "preview", sending: null, live: null, menuId: null, renaming: null };
          // View state that lasts while one request form and tab, or one exchange, is on display.
          const form = { key: "", reveal: false, bulk: {} };
          const view = { id: undefined, pretty: true, rendered: false, mode: "events", open: new Set() };

          const headBox = h("div", { class: "pageHead" });
          const bannerBox = h("div");
          const sideTopBox = h("div", { class: "hc-sideTop" });
          const sideTabsBox = h("div", { class: "hc-sideTabs", role: "tablist" });
          const filterBox = h("div", { class: "hc-sideFilter" });
          const listBox = h("div", { class: "hc-list", role: "list", onDblclick: onListDblclick });
          const countLabel = h("span");
          const limitInput = h("input", { class: "input hc-limit", type: "number", min: HISTORY_LIMIT_MIN,
            max: HISTORY_LIMIT_MAX, step: 1, disabled: true,
            title: t.historyLimitHint(HISTORY_LIMIT_MIN, HISTORY_LIMIT_MAX), onChange: saveLimit });
          const clearLink = h("button", { type: "button", class: "hc-link", "data-danger": true, onClick: confirmClear }, t.historyClear);
          const footBox = h("div", { class: "hc-sideFoot" }, countLabel, h("label", null, t.historyLimit, limitInput), spacer(), clearLink);
          const requestBox = h("div", { class: "hc-pane", "data-pane": "request" });
          const responseBox = h("div", { class: "hc-pane", "data-pane": "response" });
          const divider = h("div", { class: "hc-divider", role: "separator", "aria-label": t.resize,
            onPointerdown: onDividerDown, onDblclick: () => setSplit(50) });
          const panes = h("div", { class: "hc-panes" }, requestBox, divider, responseBox);
          panes.style.setProperty("--hc-split", `${readSplit()}%`);
          const root = h("section", { class: "hc-page", onKeydown },
            headBox, bannerBox,
            h("div", { class: "hc-body" },
              h("aside", { class: "hc-side" }, sideTopBox, sideTabsBox, filterBox, listBox, footBox),
              h("div", { class: "hc-panesWrap" }, panes)));
          el.replaceChildren(root);

          // Stand-in summary of the scope without a target.
          const directScope = () => ({ id: DIRECT, name: t.targetsDirect, baseUrl: "", auth: NO_AUTH, headers: {}, variables: {} });
          const scopeOf = () => st.targets.find((target) => target.id === st.scopeId) || directScope();
          const currentOf = () => st.requests.find((request) => request.id === st.selected[st.scopeId]) || st.requests[0];
          // Exchanges of the saved request, newest first.
          const versionsOf = (request) => (request ? st.history.filter((entry) => entry.requestId === request.id) : []);
          // The exchange picked for display, else the latest one of the selected request.
          const displayedOf = (versions) => st.shown[st.scopeId] || versions[0];
          // What the response pane shows: it is rebuilt when this changes.
          const responseKey = () => {
            const versions = versionsOf(currentOf()); const shown = displayedOf(versions);
            return `${shown ? shown.id : ""}|${versions.map((entry) => entry.id)}`;
          };
          const requestTitle = (request) => request.name || request.path.trim() || t.requestsUntitled;
          const adopt = (request) => { if (!request.auth) request.auth = NO_AUTH; return request; };
          const setBanner = (kind, text) => { st.banner = kind ? { kind, text } : null; renderBanner(); };
          const fail = (err) => setBanner("error", message(err));
          const focusUrl = () => { const input = requestBox.querySelector("[data-http-url]"); if (input) input.focus(); };
          function openModal(inner, wide) {
            const opened = modal(inner, wide, () => { if (dialog === opened.close) dialog = null; });
            dialog = opened.close;
            return opened;
          }
          // A destructive action named by `label`, which heads the dialog and labels its confirming button.
          function confirmDialog(label, text, run) {
            const { el: box, close } = openModal(`<div class="modalHead">${esc(label)}</div><div class="modalBody"><p>${esc(text)}</p></div>`
              + `<div class="modalFoot"><span class="spacer"></span><button type="button" class="btn outline" data-no>${esc(t.cancel)}</button>`
              + `<button type="button" class="btn primary" data-yes style="background:var(--error)">${esc(label)}</button></div>`);
            box.querySelector("[data-no]").onclick = close;
            box.querySelector("[data-yes]").onclick = () => { close(); run(); };
          }

          // -------------------------------------------------------- loading, scope
          async function refresh() {
            try {
              const [listed, loaded] = await Promise.all([call("/targets"), call("/settings")]);
              if (!alive) return;
              st.targets = listed.targets; st.agentTools = loaded.settings.agentTools; st.historyLimit = loaded.settings.historyLimit;
              limitInput.value = st.historyLimit; limitInput.disabled = false;
              const known = (id) => id === DIRECT || st.targets.some((target) => target.id === id);
              // First load: the scope used last, else the first target, else no target.
              const first = !st.loaded; const last = readScope();
              st.loaded = true;
              const next = !first ? (known(st.scopeId) ? st.scopeId : DIRECT)
                : last !== null && known(last) ? last : st.targets[0] ? st.targets[0].id : DIRECT;
              if (first || next !== st.scopeId) enterScope(next); else renderAll();
            } catch (err) { fail(err); }
          }
          const setScope = (id) => { if (id !== st.scopeId) enterScope(id); };
          function enterScope(id) {
            if (!alive) return;
            // Edits of the scope being left are saved before its forms leave the state.
            flushAll();
            st.scopeId = id; st.requestFilter = ""; st.historyFilter = ""; st.requests = []; st.history = []; st.menuId = null; st.renaming = null;
            try { localStorage.setItem(SCOPE_KEY, id); } catch { /* optional */ }
            const gen = ++scopeGen;
            renderAll();
            call(inScope("/requests", id)).then((data) => {
              if (!alive || gen !== scopeGen) return;
              st.requests = data.requests.map(adopt);
              renderSideTabs(); renderList(); renderRequest(); renderResponse();
              // The caret goes to the URL bar once the requests of a scope just created are on screen.
              if (focusAfterLoad) { focusAfterLoad = false; focusUrl(); }
            }, (err) => { if (alive && gen === scopeGen) fail(err); });
            loadHistory(id);
            // Requests sent by the agent reach the list through a one-entry check.
            clearInterval(pollTimer);
            pollTimer = setInterval(() => {
              if (document.hidden) return;
              call(`${inScope("/history", id)}&limit=1`).then((data) => {
                if (gen === scopeGen && (data.entries[0] || {}).id !== newest) loadHistory(id);
              }, () => {});
            }, HISTORY_POLL_MS);
          }
          async function loadHistory(scope) {
            if (!alive) return;
            try {
              const data = await call(`${inScope("/history", scope)}&limit=100`);
              if (!alive || scope !== st.scopeId) return;
              const before = responseKey();
              st.history = data.entries; newest = (data.entries[0] || {}).id;
              renderSideTabs(); renderList();
              if (responseKey() !== before) renderResponse();
            } catch (err) { if (alive) fail(err); }
          }

          // -------------------------------------------------------- autosave
          // Writes a request form with a pending edit to the server now; `keepalive` lets a save issued while the page
          // unloads complete.
          function flushSave(id, keepalive) {
            const timer = saveTimers.get(id);
            if (timer === undefined) return;
            clearTimeout(timer); saveTimers.delete(id);
            const request = st.requests.find((item) => item.id === id);
            if (!request) return;
            write("PATCH", byId("/requests", id), { name: request.name, ...storedForm(request) }, { keepalive: !!keepalive })
              .catch((err) => setBanner("error", t.requestsSaveFailed(message(err))));
          }
          const flushAll = (keepalive) => { for (const id of [...saveTimers.keys()]) flushSave(id, keepalive); };
          const dropSave = (id) => { clearTimeout(saveTimers.get(id)); saveTimers.delete(id); };
          // Applies a field change to a saved request and schedules its save.
          function editRequest(request, patch) {
            Object.assign(request, patch);
            dropSave(request.id);
            saveTimers.set(request.id, setTimeout(() => flushSave(request.id), AUTOSAVE_MS));
          }

          // -------------------------------------------------------- head, banner
          async function toggleAgentTools(next) {
            st.agentTools = next; renderHead();
            try {
              st.agentTools = (await write("POST", "/settings", { agentTools: next })).settings.agentTools;
              setBanner("ok", st.agentTools ? t.toolsOn : t.toolsOff);
            } catch (err) { st.agentTools = !next; fail(err); }
            renderHead();
          }
          function renderHead() {
            const sw = h("button", { type: "button", class: "switch", role: "switch", "data-k": "agentTools",
              "aria-checked": String(st.agentTools), "aria-label": t.agentTools,
              disabled: !st.loaded, onClick: () => toggleAgentTools(!st.agentTools) }, h("span", { class: "knob" }));
            redraw(headBox, () => headBox.replaceChildren(h("div", null, h("h1", { class: "pageTitle" }, t.title)),
              h("div", { class: "headTools" }, h("span", null, t.agentTools), sw)));
          }
          function renderBanner() {
            bannerBox.replaceChildren();
            if (!st.banner) return;
            bannerBox.append(h("div", { class: "hc-banner", "data-kind": st.banner.kind, role: "status" }, h("span", null, st.banner.text),
              h("button", { type: "button", class: "iconButton sm", title: t.close, "aria-label": t.close,
                onClick: () => setBanner(null) }, ico("x"))));
          }

          // -------------------------------------------------------- sidebar: scope
          async function runTest(target) {
            st.testing = true; setBanner("info", t.targetsTesting); renderSideTop();
            try {
              const result = (await write("POST", "/test", { id: target.id })).result;
              if (result.ok) setBanner("ok", t.targetsTestOk(result.status === undefined ? 0 : result.status, result.latencyMs));
              else setBanner("error", t.targetsTestFail(result.error === undefined ? "?" : result.error));
            } catch (err) { setBanner("error", t.targetsTestFail(message(err))); }
            st.testing = false; renderSideTop();
          }
          function confirmDeleteTarget(target) {
            confirmDialog(t.targetsDelete, t.targetsDeleteConfirm(target.name), async () => {
              // The server deletes the target's requests with it; their pending saves are dropped.
              if (target.id === st.scopeId) { for (const id of [...saveTimers.keys()]) dropSave(id); }
              try { await call(byId("/targets", target.id), { method: "DELETE" }); await refresh(); } catch (err) { fail(err); }
            });
          }
          function renderSideTop() {
            const scope = scopeOf(); const direct = scope.id === DIRECT;
            const select = h("select", { class: "select hc-select hc-targetSelect", "data-k": "scope",
              disabled: !!st.sending, "aria-label": t.targetsSelect,
              onChange: () => {
                const picked = select.value;
                if (picked !== NEW_TARGET) { setScope(picked); return; }
                select.value = st.scopeId;
                openTargetForm({ mode: "create" });
              } },
            h("option", { value: DIRECT, selected: direct }, t.targetsDirect),
            st.targets.map((target) => h("option", { value: target.id, selected: target.id === scope.id }, target.name)),
            h("option", { value: NEW_TARGET }, t.targetsAdd));
            const info = direct ? h("span", { class: "hc-targetMeta", "data-wrap": true }, t.targetsDirectHint) : [
              h("span", { class: "hc-targetUrl", title: scope.baseUrl }, scope.baseUrl),
              h("span", { class: "hc-targetMeta" }, `${authLabel(scope.auth)} · ${scope.allowMutations ? t.targetsMutations : t.targetsReadOnly}`),
              h("button", { type: "button", class: "hc-link", "data-k": "test", disabled: st.testing,
                onClick: () => runTest(scope) }, t.targetsTest)];
            redraw(sideTopBox, () => sideTopBox.replaceChildren(
              h("div", { class: "hc-targetRow" }, selectBox(select),
                h("button", { type: "button", class: "iconButton hc-boxed", "data-k": "editTarget",
                  title: t.targetsEdit, "aria-label": t.targetsEdit, disabled: direct,
                  onClick: () => openTargetForm({ mode: "edit", target: scope }) }, ico("pencil"))),
              h("div", { class: "hc-targetInfo" }, info)));
          }

          // -------------------------------------------------------- sidebar: tabs and lists
          function renderSideTabs() {
            const tab = (key, label, count) => h("button",
              { type: "button", role: "tab", class: "hc-tab", "data-k": `side:${key}`,
              "aria-selected": String(st.sideTab === key),
              onClick: () => { st.sideTab = key; st.menuId = null; st.renaming = null; renderSideTabs(); renderFilter(); renderList(); } },
            label, count > 0 ? h("span", { class: "hc-count" }, count) : null);
            redraw(sideTabsBox, () => sideTabsBox.replaceChildren(tab("requests", t.sideRequests, st.requests.length),
              tab("history", t.sideHistory, st.history.length), spacer(),
              h("button", { type: "button", class: "iconButton sm hc-accent", "data-k": "new", title: t.requestsNew,
                "aria-label": t.requestsNew, disabled: !st.loaded,
                onClick: () => createRequest() }, ico("plus"))));
          }
          function renderFilter() {
            const requests = st.sideTab === "requests";
            const label = requests ? t.requestsFilter : t.historyFilter;
            const input = h("input", { class: "input hc-input", "data-k": "filter",
              value: requests ? st.requestFilter : st.historyFilter, placeholder: label, "aria-label": label,
              spellcheck: "false", onInput: () => { st[requests ? "requestFilter" : "historyFilter"] = input.value; renderList(); } });
            redraw(filterBox, () => filterBox.replaceChildren(input));
          }
          const matching = (items, filter, text) => {
            const needle = filter.trim().toLowerCase();
            return items.filter((item) => needle === "" || text(item).toLowerCase().includes(needle));
          };
          function requestRow(request, current) {
            const renaming = st.renaming && st.renaming.id === request.id; const open = st.menuId === request.id;
            const rename = () => {
              const input = h("input", { class: "input hc-input hc-renameInput", "data-k": "rename",
                value: st.renaming.value, placeholder: request.path.trim() || t.requestsUntitled,
                "aria-label": t.requestsRename, onInput: () => { st.renaming.value = input.value; }, onBlur: commitRename,
                onKeydown: (event) => {
                  if (event.key === "Enter") { event.preventDefault(); commitRename(); }
                  if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); st.renaming = null; refreshRow(request); }
                } });
              return h("div", { class: "hc-itemMain" }, h("span", { class: "hc-itemLine" }, methodText(request.method), input));
            };
            const toggleMenu = () => { if (st.menuId === request.id) closeMenu(); else { st.menuId = request.id; renderList(); } };
            const item = (label, run, danger) => h("button",
              { type: "button", role: "menuitem", "data-danger": danger,
              onClick: () => { closeMenu(); run(request); } }, label);
            return h("div", { role: "listitem", class: "hc-item", "data-id": request.id, "data-active": request === current, "data-menu-open": open },
              renaming ? rename() : h("button", { type: "button", class: "hc-itemMain",
                "data-k": `request:${request.id}`, onClick: () => selectRequest(request.id),
                title: `${request.name === "" ? "" : `${request.name}\n`}${request.method} ${request.path}` },
              h("span", { class: "hc-itemLine" }, methodText(request.method),
                h("span", { class: "hc-itemPath", "data-named": request.name !== "" }, requestTitle(request)))),
              renaming ? null : h("div", { class: "hc-itemMenu", "data-hc-menu": true },
                h("button", { type: "button", class: "iconButton sm", "data-k": `menu:${request.id}`,
                  title: t.requestsActions, "aria-label": t.requestsActions, "aria-haspopup": "menu",
                  "aria-expanded": String(open), onClick: toggleMenu }, ico("dots")),
                open ? h("div", { class: "hc-menu", role: "menu" }, item(t.requestsRename, startRename),
                  item(t.requestsDuplicate, duplicateRequest), item(t.requestsCopyCurl, copyCurl),
                  item(t.requestsDelete, confirmDeleteRequest, true)) : null));
          }
          function historyRow(entry, shown) {
            const response = entry.response;
            return h("div", { role: "listitem", class: "hc-item", "data-active": entry.id === shown },
              h("button", { type: "button", class: "hc-itemMain", "data-k": `entry:${entry.id}`,
                title: entry.request.url || entry.request.path, onClick: () => pickExchange(entry) },
                h("span", { class: "hc-itemLine" }, methodText(entry.request.method), h("span", { class: "hc-itemPath" }, requestLabel(entry))),
                h("span", { class: "hc-itemLine", "data-sub": true },
                  response ? h("span", { class: "hc-statusText", "data-tone": statusTone(response.status) }, response.status)
                    : h("span", { class: "hc-statusText", "data-tone": "danger", title: entry.error }, t.historyFailed),
                  h("span", null, response ? t.responseTime(response.durationMs) : ""), spacer(),
                  entry.source === "agent" ? h("span", { class: "hc-sourceTag", "data-source": "agent" }, t.sourceAgent) : null,
                  h("span", null, shortTime(entry.at)))),
              h("div", { class: "hc-itemActions" },
                h("button", { type: "button", class: "iconButton sm", title: t.historySaveAs,
                  "aria-label": t.historySaveAs, onClick: () => createRequest(formFromExchange(entry)) }, ico("plus")),
                h("button", { type: "button", class: "iconButton sm hc-danger", title: t.historyDelete,
                  "aria-label": t.historyDelete, onClick: () => deleteEntry(entry) }, ico("x"))));
          }
          function renderList() {
            const requests = st.sideTab === "requests";
            let rows;
            if (requests) {
              const current = currentOf();
              rows = matching(st.requests, st.requestFilter,
                (request) => `${request.method} ${request.name} ${request.path}`).map((request) => requestRow(request,
                current));
              if (!rows.length) rows = [h("div", { class: "hc-hint" }, st.requests.length ? t.requestsNoMatch : t.requestsEmpty)];
            } else {
              const shown = displayedOf(versionsOf(currentOf()));
              const text = (entry) => `${entry.request.method} ${requestLabel(entry)} ${entry.response ? entry.response.status : entry.error || ""}`;
              rows = matching(st.history, st.historyFilter, text).map((entry) => historyRow(entry, shown && shown.id));
              if (!rows.length) rows = [h("div", { class: "hc-hint" }, st.history.length ? t.historyNoMatch : t.historyEmpty)];
            }
            redraw(listBox, () => listBox.replaceChildren(...rows));
            footBox.hidden = requests;
            countLabel.textContent = t.historyCount(st.history.length);
            clearLink.disabled = !st.history.length;
          }
          // Redraws the row of one saved request in place, so a click in progress on another row still lands; the
          // whole list when a filter decides which rows show.
          function refreshRow(request) {
            if (st.sideTab !== "requests") return;
            const node = st.requestFilter.trim() === "" && [...listBox.children].find((child) => child.dataset.id === request.id);
            if (node) redraw(listBox, () => node.replaceWith(requestRow(request, currentOf()))); else renderList();
          }
          function closeMenu() {
            st.menuId = null;
            const node = listBox.querySelector("[data-menu-open]");
            if (!node) return;
            node.removeAttribute("data-menu-open");
            node.querySelector(".hc-menu").remove();
            node.querySelector("[aria-expanded]").setAttribute("aria-expanded", "false");
          }
          function onDocumentDown(event) {
            if (st.menuId !== null && !(event.target instanceof Element && event.target.closest("[data-hc-menu]"))) closeMenu();
          }
          function onDocumentKey(event) { if (st.menuId !== null && event.key === "Escape") closeMenu(); }
          function onListDblclick(event) {
            const node = event.target instanceof Element && event.target.closest("button.hc-itemMain");
            const request = node && st.requests.find((item) => item.id === node.parentNode.dataset.id);
            if (request) startRename(request);
          }
          function startRename(request) {
            st.renaming = { id: request.id, value: request.name };
            refreshRow(request);
            const input = listBox.querySelector(".hc-renameInput");
            if (input) input.focus();
          }
          function commitRename() {
            const renaming = st.renaming;
            if (!renaming) return;
            st.renaming = null;
            const request = st.requests.find((item) => item.id === renaming.id);
            if (!request) return;
            editRequest(request, { name: renaming.value.trim() });
            refreshRow(request);
          }
          function renderSide() { renderSideTop(); renderSideTabs(); renderFilter(); renderList(); }

          // -------------------------------------------------------- saved requests
          function selectRequest(id) {
            st.selected[st.scopeId] = id; delete st.shown[st.scopeId]; st.responseTab = "preview";
            renderList(); renderRequest(); renderResponse();
          }
          // Adds a request to the current scope, selects it and puts the caret in its URL bar.
          async function createRequest(fields) {
            const targetId = st.scopeId;
            try {
              const created = adopt((await write("POST", "/requests", { ...(fields || {}), targetId })).request);
              if (!alive || targetId !== st.scopeId) return;
              st.requests.push(created); st.selected[targetId] = created.id; delete st.shown[targetId];
              st.requestFilter = ""; st.sideTab = "requests"; st.requestTab = "params";
              renderSide(); renderRequest(); renderResponse(); focusUrl();
            } catch (err) { fail(err); }
          }
          const duplicateRequest = (request) => createRequest({ ...storedForm(request),
            name: request.name === "" ? "" : `${request.name} ${t.requestsCopySuffix}` });
          async function copyCurl(request) {
            const command = curlOf(scopeOf(), request);
            if (command === undefined) { setBanner("error", t.requestsCurlUnavailable); return; }
            try { await copyText(command); setBanner("ok", t.requestsCurlCopied); } catch (err) { fail(err); }
          }
          function confirmDeleteRequest(request) {
            confirmDialog(t.requestsDelete, t.requestsDeleteConfirm(requestTitle(request)), async () => {
              dropSave(request.id);
              try {
                await call(byId("/requests", request.id), { method: "DELETE" });
                st.requests = st.requests.filter((item) => item !== request);
                renderSideTabs(); renderList(); renderRequest(); renderResponse();
              } catch (err) { fail(err); }
            });
          }

          // -------------------------------------------------------- request pane
          function renderRequest() {
            const request = currentOf();
            const key = request ? `${request.id}:${st.requestTab}` : "";
            if (key !== form.key) Object.assign(form, { key, reveal: false, bulk: { query: {}, headers: {}, form: {} } });
            syncForm = () => {};
            rebuild(requestBox, request ? requestForm(scopeOf(),
              request) : [h("div", { class: "hc-paneBody", "data-center": true },
              st.loaded ? h("div", { class: "hc-hints" },
              h("span", null, t.requestsNone), h("button",
                { type: "button", class: "btn primary sm", "data-k": "create", onClick: () => createRequest() },
                t.requestsNew), sendHint()) : null)], true);
          }
          function requestForm(target, request) {
            const direct = target.id === DIRECT; const sending = !!st.sending; const tab = st.requestTab;
            // The request's own authentication is in effect when the target brings none.
            const ownAuth = target.auth.type === "none";
            const bodyAllowed = request.method !== "GET" && request.method !== "HEAD";
            // `redo` rebuilds the pane; without it only the parts derived from the fields follow, and the input being
            // typed in stays in place.
            const set = (patch, redo) => {
              editRequest(request, patch);
              if (redo) renderRequest(); else syncForm();
              if ("path" in patch || "method" in patch) refreshRow(request);
            };
            const count = (rows) => rows.filter(sent).length || undefined;
            const badge = (value) => {
              if (value === "params") return count(request.query);
              if (value === "headers") return count(request.headers);
              if (value === "body") return bodyAllowed && request.bodyMode !== "none" ? t.bodyModes[request.bodyMode] : undefined;
              const type = ownAuth ? request.auth.type : target.auth.type;
              return type === "none" ? undefined : t.auth[type];
            };
            const tabs = h("div", { class: "hc-tabs", role: "tablist" });
            const drawTabs = () => tabs.replaceChildren(...REQUEST_TABS.map((value) => {
              const label = badge(value);
              return h("button", { type: "button", role: "tab", class: "hc-tab", "data-k": `tab:${value}`, "aria-selected": String(tab === value),
                onClick: () => { st.requestTab = value; renderRequest(); } }, t.requestTabs[value],
                label === undefined ? null : h("span", { class: "hc-count" }, label));
            }));
            const kv = (name) => kvEditor({ name, rows: request[name], onChange: (rows) => set({ [name]: rows }),
              view: form.bulk[name], toggle: true, tools: true, disabled: sending });

            // A pasted cURL command replaces the whole form.
            const onPaste = (event) => {
              const text = event.clipboardData.getData("text");
              const parsed = /^\s*curl\s/.test(text) ? parseCurl(text) : undefined;
              if (!parsed) return;
              event.preventDefault();
              form.key = "";
              set(formFromCurl(parsed, target), true);
              setBanner("info", parsed.multipart ? t.requestCurlMultipart : t.requestCurlImported);
            };
            const method = h("select", { class: "select hc-method", "data-k": "method", "data-method": request.method, "aria-label": "method",
              onChange: () => set({ method: method.value }, true) },
              METHODS.map((value) => h("option", { value, selected: value === request.method }, value)));
            const url = h("input", { class: "hc-pathInput", "data-http-url": true, "data-k": "url", "data-direct": direct, value: request.path,
              placeholder: direct ? t.requestUrlPlaceholder : t.requestPathPlaceholder, autocapitalize: "off",
              spellcheck: "false", "aria-label": t.requestPath,
              onInput: () => set({ path: url.value }), onPaste });
            const bar = h("form", { class: "hc-paneHead hc-urlBar", onSubmit: (event) => { event.preventDefault(); send(); } }, selectBox(method),
              h("div", { class: "hc-urlBox" }, direct ? null : h("span",
                { class: "hc-baseUrl", title: target.baseUrl }, h("bdi", null, target.baseUrl)), url),
              h("button", { type: "submit", class: "btn primary hc-send", "data-k": "send", disabled: sending,
                title: sendShortcut() }, t.requestSend));

            let sync = () => {};
            function paramsTab() {
              const box = h("div", { class: "hc-previewBox" });
              const importQuery = () => {
                const { path, pairs } = splitQuery(request.path);
                const query = [...request.query, ...recordToRows(pairs)];
                if (form.bulk.query.text !== undefined) form.bulk.query.text = rowsToBulk(query);
                set({ path, query }, true);
              };
              sync = () => {
                const preview = previewUrl(target, request);
                box.replaceChildren(h("div", { class: "hc-previewHead" }, h("span", { class: "hc-label" }, t.requestUrlPreview), spacer(),
                  request.path.includes("?") ? h("button",
                    { type: "button", class: "hc-link", "data-k": "import", disabled: sending, onClick: importQuery },
                    t.requestImportQuery) : null,
                  h("button", { type: "button", class: "hc-link", "data-k": "copyPreview", disabled: !preview.url,
                    onClick: (event) => copyFlash(event.currentTarget, preview.url, t.requestCopy) }, t.requestCopy)),
                h("code", { class: "hc-previewUrl", "data-error": preview.error !== undefined },
                  preview.error !== undefined ? preview.error : preview.url || "—"));
              };
              return [box, kv("query")];
            }
            function bodyTab() {
              if (!bodyAllowed) return [empty(t.requestNoBody(request.method))];
              const mode = request.bodyMode;
              const format = h("button", { type: "button", class: "hc-link", "data-k": "format",
                onClick: () => set({ body: prettyJson(request.body).text }, true) }, t.requestFormatJson);
              const problem = h("div", { class: "hc-formError" });
              sync = () => {
                let error;
                if (mode === "json" && request.body.trim() !== "") { try { JSON.parse(request.body); } catch (err) { error = message(err); } }
                format.disabled = error !== undefined || request.body.trim() === "";
                problem.hidden = error === undefined;
                problem.textContent = error === undefined ? "" : t.requestInvalidJson(error);
              };
              // Tab indents by two spaces in the body editor.
              const onKeydown = (event) => {
                if (event.key !== "Tab" || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) return;
                event.preventDefault();
                editor.setRangeText("  ", editor.selectionStart, editor.selectionEnd, "end");
                set({ body: editor.value });
              };
              const editor = h("textarea", { class: "hc-editor", "data-k": "body",
                placeholder: mode === "json" ? t.requestBodyPlaceholder : null, spellcheck: "false",
                disabled: sending, onInput: () => set({ body: editor.value }), onKeydown }, request.body);
              return [
                h("div", { class: "hc-toolRow" }, segments("bodyMode",
                  BODY_MODES.map((value) => [value, t.bodyModes[value]]), mode,
                  (value) => set({ bodyMode: value }, true)),
                  spacer(), mode === "json" ? format : null),
                mode === "form" ? kv("form") : mode === "none" ? empty(t.requestBodyNone) : editor, problem];
            }
            function headersTab() {
              const fixed = Object.entries(target.headers);
              return [kv("headers"), fixed.length ? block(t.requestFixedHeaders, table(fixed)) : null];
            }
            function authTab() {
              if (!ownAuth) {
                return [h("div", { class: "hc-block" }, table(authSummary(target.auth)), h("p", { class: "hc-note" }, t.requestAuthNote),
                  h("div", null, h("button", { type: "button", class: "btn outline sm", "data-k": "editTarget",
                    onClick: () => openTargetForm({ mode: "edit", target }) }, t.targetsEdit)))];
              }
              const auth = request.auth;
              return [
                h("div", { class: "hc-authEditor" },
                  h("div", { class: "hc-toolRow" },
                    segments("auth", AUTH_TYPES.map((type) => [type, t.auth[type]]), auth.type,
                      (type) => set({ auth: blankAuth(type) }, true), { label: t.formAuth, disabled: sending }),
                    spacer(), auth.type === "none" ? null : h("button", { type: "button", class: "hc-link", "data-k": "reveal",
                      onClick: () => { form.reveal = !form.reveal; renderRequest(); } }, form.reveal ? t.requestHideSecret : t.requestShowSecret)),
                  authFields(auth.type, (name) => request.auth[name],
                    (name, value) => set({ auth: { ...request.auth, [name]: value } }),
                    { disabled: sending, reveal: form.reveal })),
                h("p", { class: "hc-note" }, direct ? t.requestDirectAuthNote : t.requestOwnAuthNote),
                direct ? h("div", null, h("button", { type: "button", class: "btn outline sm", "data-k": "promote",
                  onClick: () => openTargetForm({ mode: "create", fromRequest: request }) }, t.targetsFromRequest)) : null];
            }
            const content = { params: paramsTab, body: bodyTab, headers: headersTab, auth: authTab }[tab]();
            syncForm = () => { drawTabs(); sync(); };
            syncForm();
            return [bar, tabs, h("div", { class: "hc-paneBody", role: "tabpanel" }, content)];
          }

          // -------------------------------------------------------- sending
          const cancel = () => { if (st.sending) st.sending.controller.abort(); };
          function tickElapsed() {
            if (!st.sending) return;
            const seconds = (Math.max(0, Date.now() - st.sending.since) / 1000).toFixed(1);
            for (const node of responseBox.querySelectorAll("[data-elapsed]")) {
              node.textContent = node.dataset.elapsed === "stream" ? t.streamReceiving(seconds) : t.responseSending(seconds);
            }
          }
          async function send() {
            const request = currentOf();
            if (!request || st.sending) return;
            const controller = new AbortController(); const targetId = st.scopeId;
            flushSave(request.id);
            st.sending = { since: Date.now(), controller }; st.banner = null;
            // Stream events reach the page once per frame.
            const pending = []; let frame = 0;
            const flush = () => {
              frame = 0;
              const batch = pending.splice(0);
              if (!st.live) return;
              st.live.rows.push(...batch);
              if (liveSync) liveSync(batch);
            };
            const ticker = setInterval(tickElapsed, 100);
            renderBanner(); renderSideTop(); renderRequest(); renderResponse();
            try {
              const exchange = await sendRequest(targetId, { ...toRequestInput(request), requestId: request.id }, controller.signal, {
                onHead: (head) => { st.live = { head, rows: [], open: new Set() }; st.responseTab = "preview"; renderResponse(); },
                onEvent: (event, at) => { pending.push({ ...event, at }); if (frame === 0) frame = requestAnimationFrame(flush); },
              });
              st.shown[targetId] = exchange; st.responseTab = "preview";
            } catch (err) {
              // A stopped request shows what the server recorded for it: the latest exchange of this request.
              if (controller.signal.aborted) delete st.shown[targetId]; else fail(err);
            }
            cancelAnimationFrame(frame); clearInterval(ticker);
            st.live = null; st.sending = null;
            renderSideTop(); renderList(); renderRequest(); renderResponse();
            // A cancelled request is recorded by the server once its connection closes.
            if (controller.signal.aborted) setTimeout(() => loadHistory(targetId), 400); else loadHistory(targetId);
          }

          // -------------------------------------------------------- history
          // Shows a recorded exchange; its saved request, when it still exists, becomes the selected one.
          function pickExchange(entry) {
            const before = currentOf();
            if (st.requests.some((request) => request.id === entry.requestId)) st.selected[st.scopeId] = entry.requestId;
            st.shown[st.scopeId] = entry; st.responseTab = "preview";
            renderList();
            if (currentOf() !== before) renderRequest();
            renderResponse();
          }
          async function deleteEntry(entry) {
            try {
              await call(byId("/history", entry.id), { method: "DELETE" });
              const before = responseKey();
              st.history = st.history.filter((item) => item.id !== entry.id); newest = (st.history[0] || {}).id;
              if ((st.shown[st.scopeId] || {}).id === entry.id) delete st.shown[st.scopeId];
              renderSideTabs(); renderList();
              if (responseKey() !== before) renderResponse();
            } catch (err) { fail(err); }
          }
          function confirmClear() {
            const target = scopeOf();
            confirmDialog(t.historyClear, t.historyClearConfirm(target.name), async () => {
              try {
                await call(inScope("/history", target.id), { method: "DELETE" });
                delete st.shown[target.id];
                if (target.id !== st.scopeId) return;
                st.history = []; newest = undefined;
                renderSideTabs(); renderList(); renderResponse();
              } catch (err) { fail(err); }
            });
          }
          async function saveLimit() {
            try {
              st.historyLimit = (await write("POST", "/settings", { historyLimit: Number(limitInput.value) })).settings.historyLimit;
              loadHistory(st.scopeId);
            } catch (err) { fail(err); }
            limitInput.value = st.historyLimit;
          }

          // -------------------------------------------------------- response pane
          // Event stream view: the events as a list that grows while the stream is read, the text assembled from model
          // output increments, and the raw stream text once it is complete. `append` takes rows already added to `rows`.
          function sseView({ rows, open, raw, streaming, ended }) {
            let text = rows.map(rowText).join(""); let stick = true;
            const tools = h("div", { class: "hc-toolRow" });
            const latest = note(t.streamLatest(MAX_ROWS));
            const scroll = h("div", { class: "hc-sseScroll",
              onScroll: () => { stick = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < STICK_PX; } });
            const modes = () => STREAM_MODES.filter((mode) => (mode === "text" ? text !== "" : mode === "raw" ? raw !== undefined : true));
            const current = () => (modes().includes(view.mode) ? view.mode : "events");
            // New content keeps the view at the end while the reader has not scrolled away from it.
            const toEnd = () => { if (streaming && stick) scroll.scrollTop = scroll.scrollHeight; };
            const detail = (row) => h("div", { class: "hc-sseDetail" },
              row.id === undefined && row.retry === undefined ? null : h("span", { class: "hc-meta" },
                [row.id === undefined ? "" : `id: ${row.id}`, row.retry === undefined ? "" : `retry: ${row.retry}`].filter(Boolean).join(" · ")),
              h("pre", { class: "hc-code" }, prettyJson(row.data).text));
            function rowNode(index) {
              const row = rows[index];
              const head = h("button", { type: "button", class: "hc-sseHead", onClick: () => { if (!open.delete(index)) open.add(index); show(); } },
                h("span", { class: "hc-sseIndex" }, index + 1),
                h("span", { class: "hc-sseTime" }, row.at === undefined ? "" : `+${(row.at / 1000).toFixed(2)}s`),
                h("span", { class: "hc-sseType", "data-named": row.event !== "" }, row.event === "" ? "message" : row.event),
                h("span", { class: "hc-sseData" }, row.data.length > 240 ? `${row.data.slice(0, 240)}…` : row.data));
              const node = h("div", { class: "hc-sseRow" }, head);
              const show = () => {
                const expanded = open.has(index);
                head.setAttribute("aria-expanded", String(expanded));
                node.toggleAttribute("data-open", expanded);
                if (expanded) node.append(detail(row)); else if (head.nextSibling) head.nextSibling.remove();
              };
              show();
              return node;
            }
            function draw() {
              const mode = current();
              const pick = segments("stream", modes().map((value) => [value, t.streamModes[value]]), mode,
                (value) => { view.mode = value; draw(); }, { small: true });
              redraw(tools, () => tools.replaceChildren(pick, spacer(),
                ended === "cancelled" || ended === "timeout" ? note(t.streamEnded[ended]) : ""));
              const offset = Math.max(0, rows.length - MAX_ROWS);
              latest.hidden = offset === 0;
              if (mode === "text") scroll.replaceChildren(h("pre", { class: "hc-code hc-sseText" }, text));
              else if (mode === "raw") scroll.replaceChildren(h("pre", { class: "hc-code" }, raw));
              else if (!rows.length) scroll.replaceChildren(empty(streaming ? t.streamWaiting : t.streamEmpty));
              else scroll.replaceChildren(latest, ...rows.slice(offset).map((_, position) => rowNode(offset + position)));
              requestAnimationFrame(toEnd);
            }
            function append(batch) {
              const silent = text === ""; const first = rows.length === batch.length;
              text += batch.map(rowText).join("");
              const mode = current();
              // The first text adds the text mode; the first rows replace the waiting line.
              if ((silent && text !== "") || (mode === "events" && first)) { draw(); return; }
              if (mode === "text") scroll.firstChild.textContent = text;
              else {
                for (let index = rows.length - batch.length; index < rows.length; index++) scroll.append(rowNode(index));
                while (scroll.childElementCount - 1 > MAX_ROWS) latest.nextSibling.remove();
                latest.hidden = rows.length <= MAX_ROWS;
              }
              toEnd();
            }
            draw();
            return { el: h("div", { class: "hc-sse" }, tools, scroll), append };
          }
          const responseTabs = (values, active, headerCount, tools) => h("div", { class: "hc-tabs", role: "tablist" },
            values.map((value) => h("button", { type: "button", role: "tab", class: "hc-tab",
              "data-k": `response:${value}`, "aria-selected": String(active === value),
              onClick: () => { st.responseTab = value; renderResponse(); } }, t.responseTabs[value],
              value === "headers" && headerCount > 0 ? h("span", { class: "hc-count" }, headerCount) : null)),
            tools);
          const overlay = () => (st.sending ? h("div", { class: "hc-overlay", role: "status" },
            h("span", { class: "hc-spinner", "aria-hidden": "true" }), h("span", { "data-elapsed": "request" }),
            h("button", { type: "button", class: "btn outline sm", "data-k": "cancel", onClick: cancel }, t.responseCancel)) : null);
          // The event stream being read, from its response head on; it replaces the waiting overlay.
          function liveView(live) {
            const headers = Object.entries(live.head.headers);
            const tab = st.responseTab === "headers" ? "headers" : "preview";
            const count = tag(t.streamCount(live.rows.length));
            const stream = tab === "preview" ? sseView({ rows: live.rows, open: live.open, streaming: true }) : null;
            liveSync = (batch) => { count.textContent = t.streamCount(live.rows.length); if (stream) stream.append(batch); };
            return [
              h("div", { class: "hc-paneHead" }, statusTag(live.head), count, spacer(),
                h("span", { class: "hc-spinner", "data-small": true, "aria-hidden": "true" }),
                h("span", { class: "hc-meta", "data-elapsed": "stream" }),
                h("button", { type: "button", class: "btn outline sm", "data-k": "cancel", onClick: cancel },
                  t.streamStop)),
              responseTabs(["preview", "headers"], tab, headers.length),
              h("div", { class: "hc-paneBody", role: "tabpanel" }, stream ? stream.el : table(headers))];
          }
          function saveBody(exchange) {
            const blob = bodyBlob(exchange.response);
            if (!blob) return;
            const href = URL.createObjectURL(blob);
            const link = h("a", { href, download: saveName(exchange.request.url, exchange.response.contentType) });
            document.body.appendChild(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(href), 10000);
          }
          function exchangeView(exchange, versions) {
            const { request, response } = exchange; const tab = st.responseTab;
            const formatted = response ? prettyJson(response.body) : { text: "", json: false };
            const rows = response && (response.stream || isEventStream(response.contentType)) ? streamRows(response) : undefined;
            const headers = Object.entries(response ? response.headers : {});
            const mediaType = (response ? response.contentType : "").split(";")[0].trim().toLowerCase();
            const textual = !!response && !response.binary && response.body !== "";
            const html = textual && (mediaType === "text/html" || mediaType === "application/xhtml+xml");
            const image = response && response.bodyBase64 !== undefined && mediaType.startsWith("image/")
              ? `data:${mediaType};base64,${response.bodyBase64}` : undefined;
            const bodyText = response && view.pretty && formatted.json ? formatted.text : response ? response.body : "";
            const pick = h("select", { class: "select hc-select hc-version", "data-k": "version",
              title: t.responseVersions, "aria-label": t.responseVersions,
              onChange: () => { st.shown[st.scopeId] = versions.find((entry) => entry.id === pick.value); renderList(); renderResponse(); } },
            versions.map((entry) => h("option", { value: entry.id, selected: entry.id === exchange.id },
              `${shortTime(entry.at)} · ${entry.response ? entry.response.status : t.historyFailed}`)));
            const head = h("div", { class: "hc-paneHead" },
              response ? [statusTag(response), tag(t.responseTime(response.durationMs)),
                tag(humanSize(response.bodyBytes)), rows ? tag(t.streamCount(rows.length)) : null]
                : tag(t.responseErrorTag, "danger"),
              spacer(),
              versions.length > 1 && versions.some((entry) => entry.id === exchange.id) ? selectBox(pick) : h("span",
                { class: "hc-meta" }, formatTime(exchange.at)),
              h("span", { class: "hc-sourceTag", "data-source": exchange.source }, exchange.source === "agent" ? t.sourceAgent : t.sourcePanel));
            const toggle = (field, options) => segments(field, options, view[field],
              (value) => { view[field] = value; renderResponse(); }, { small: true });
            const tools = tab !== "preview" ? [spacer()] : [spacer(),
              response && formatted.json ? toggle("pretty", [[true, t.responsePretty], [false, t.responseRaw]]) : null,
              html ? toggle("rendered", [[false, t.responseSource], [true, t.responseRender]]) : null,
              textual ? h("button", { type: "button", class: "hc-link", "data-k": "copyBody",
                onClick: (event) => copyFlash(event.currentTarget, bodyText, t.responseCopy) }, t.responseCopy) : null,
              textual || (response && response.bodyBase64 !== undefined) ? h("button",
                { type: "button", class: "hc-link", "data-k": "save", onClick: () => saveBody(exchange) },
                t.responseSave) : null];
            let content;
            if (tab === "headers") content = headers.length ? table(headers) : empty(t.responseNoHeaders);
            else if (tab === "request") {
              const sentHeaders = Object.entries(request.sentHeaders || request.headers);
              content = [
                h("div", { class: "hc-previewBox" },
                  h("div", { class: "hc-previewHead" }, h("span", { class: "hc-methodTag", "data-method": request.method }, request.method), spacer(),
                    h("button", { type: "button", class: "hc-link", "data-k": "copyUrl", disabled: request.url === "",
                      onClick: (event) => copyFlash(event.currentTarget, request.url, t.responseCopyUrl) }, t.responseCopyUrl)),
                  h("code", { class: "hc-previewUrl" }, request.url || request.path)),
                sentHeaders.length ? block(t.responseSentHeaders, table(sentHeaders)) : null,
                request.body === "" ? null : block(t.responseSentBody, h("pre", { class: "hc-code" }, request.body),
                  request.bodyTruncated ? note(t.responseRequestTruncated) : null)];
            } else {
              let body = null;
              if (image !== undefined) body = h("div", { class: "hc-imageBox" },
                h("img", { class: "hc-image", src: image, alt: saveName(request.url, response.contentType) }));
              else if (response && response.binary) body = empty(t.responseBinary(humanSize(response.bodyBytes)));
              else if (response && response.body === "") body = empty(t.responseNoBody);
              else if (rows) body = sseView({ rows, open: view.open, raw: response.body, streaming: false,
                ended: response.stream && response.stream.ended }).el;
              // Scripts, forms and same-origin access stay off; relative links resolve against the request URL.
              else if (html && view.rendered) body = h("iframe",
                { class: "hc-frame", sandbox: "", referrerpolicy: "no-referrer", title: t.responseRender,
                srcdoc: `<base href="${escapeAttribute(request.url)}">${response.body}` });
              else if (response) body = h("pre", { class: "hc-code" }, bodyText);
              content = [
                exchange.error === undefined ? null : h("div",
                  { class: "hc-banner", "data-kind": "error", role: "alert" },
                  h("span", null, t.responseError(exchange.error))),
                response && response.redirects.length ? note(t.responseRedirects(response.redirects.join(" → "))) : null,
                body, response && response.bodyTruncated ? note(t.responseTruncated(humanSize(response.bodyBytes))) : null];
            }
            return [head, responseTabs(RESPONSE_TABS, tab, headers.length, tools),
              h("div", { class: "hc-paneBody", role: "tabpanel" }, content), overlay()];
          }
          function renderResponse() {
            const versions = versionsOf(currentOf()); const exchange = displayedOf(versions);
            const same = (exchange ? exchange.id : undefined) === view.id;
            if (!same) Object.assign(view, { id: exchange ? exchange.id : undefined, rendered: false, open: new Set() });
            liveSync = null;
            const nodes = st.sending && st.live ? liveView(st.live) : exchange ? exchangeView(exchange, versions)
              : [h("div", { class: "hc-paneBody", "data-center": true },
                h("div", { class: "hc-hints" }, h("span", null, t.responseEmpty), sendHint())), overlay()];
            rebuild(responseBox, nodes, same);
            tickElapsed();
          }

          // -------------------------------------------------------- target dialog
          // Saves the dialog's payload. A target created from a request takes that request below it, its URL made
          // relative; any other new target starts with one request form ready to edit.
          async function saveTarget(spec, payload) {
            if (spec.mode === "edit") {
              const saved = (await write("PATCH", byId("/targets", spec.target.id), payload)).target;
              await refresh();
              setScope(saved.id);
              return;
            }
            const saved = (await write("POST", "/targets", payload)).target;
            const moving = spec.fromRequest && st.requests.find((request) => request === spec.fromRequest);
            let first;
            if (moving) {
              dropSave(moving.id);
              // Authentication taken over by the target leaves the request.
              const fields = { name: moving.name, ...storedForm(moving),
                auth: saved.auth.type === "none" ? moving.auth : NO_AUTH, targetId: saved.id,
                path: pathBelow(saved.baseUrl, moving.path) };
              first = await write("PATCH", byId("/requests", moving.id), fields).catch(() => undefined);
            } else first = await write("POST", "/requests", { targetId: saved.id }).catch(() => undefined);
            focusAfterLoad = true;
            await refresh();
            if (first) st.selected[saved.id] = first.request.id;
            st.sideTab = "requests";
            setScope(saved.id);
          }
          // Create / edit dialog; on edit, empty secret fields keep the stored values.
          function openTargetForm(spec) {
            const target = spec.mode === "edit" ? spec.target : null;
            const stored = target ? target.auth : NO_AUTH;
            // A target created from a request starts with the origin of its URL and its authentication.
            const { type: seedType, ...seed } = spec.fromRequest ? spec.fromRequest.auth : NO_AUTH;
            const d = {
              name: target ? target.name : "", baseUrl: target ? target.baseUrl : spec.fromRequest ? originOf(spec.fromRequest.path) : "",
              type: target ? stored.type : seedType,
              auth: { token: "", username: stored.username || "", password: "", name: stored.name || "", value: "", ...seed },
              headers: recordToRows(target ? target.headers : {}), variables: recordToRows(target ? target.variables : {}),
              allowedHosts: target ? target.allowedHosts.join("\n") : "",
              allowMutations: !!target && target.allowMutations, allowPrivate: !!target && target.allowPrivate,
              timeoutMs: String(target ? target.timeoutMs : DEFAULT_TIMEOUT_MS),
              advanced: !!target && (target.allowedHosts.length > 0 || target.allowPrivate || target.timeoutMs !== DEFAULT_TIMEOUT_MS
                || Object.keys(target.variables).length > 0),
            };
            const { el: box, close } = openModal("", true);
            const text = (key, attrs) => h("input",
              { class: "input hc-input", "data-k": key, value: d[key], ...(attrs || {}),
              onInput: (e) => { d[key] = e.target.value; } });
            const check = (key, label) => h("label", { class: "hc-checkRow" },
              h("input", { type: "checkbox", class: "hc-check", "data-k": key, checked: d[key],
                onChange: (e) => { d[key] = e.target.checked; } }), h("span", null, label));
            const authBox = h("div", { class: "hc-formPart" });
            const drawAuth = () => redraw(authBox, () => authBox.replaceChildren(
              h("div", { class: "hc-field" }, h("span", { class: "hc-fieldLabel" }, t.formAuth),
                segments("type", AUTH_TYPES.map((type) => [type, t.auth[type]]), d.type, (type) => { d.type = type; drawAuth(); })),
              ...authFields(d.type, (name) => d.auth[name], (name, value) => { d.auth[name] = value; },
                { autocomplete: "new-password", keep: target && stored.type === d.type ? t.authKeep : null })));
            const moreBox = h("div", { class: "hc-formPart" });
            const drawMore = () => redraw(moreBox, () => moreBox.replaceChildren(...[
              h("button", { type: "button", class: "hc-link", "data-k": "advanced", "aria-expanded": String(d.advanced),
                onClick: () => { d.advanced = !d.advanced; drawMore(); } },
                `${d.advanced ? "▾" : "▸"} ${t.formAdvanced}`),
              ...(d.advanced ? [
                h("div", { class: "hc-field" }, h("span", { class: "hc-fieldLabel" }, t.formVariables),
                  kvEditor({ name: "variables", rows: d.variables, onChange: (rows) => { d.variables = rows; },
                    view: {} }), h("span", { class: "hc-fieldHint" }, t.formVariablesHint)),
                field(t.formAllowedHosts, [h("textarea",
                  { class: "input mono", rows: 2, placeholder: "cdn.example.com\n*.example.net", spellcheck: "false",
                  onInput: (e) => { d.allowedHosts = e.target.value; } }, d.allowedHosts),
                  h("span", { class: "hc-fieldHint" }, t.formAllowedHostsHint)]),
                h("div", { class: "hc-formRow" }, field(t.formTimeout,
                  text("timeoutMs", { class: "input hc-input mono", inputmode: "numeric" }),
                  { style: { flex: "0 0 160px" } }),
                  h("div", { class: "hc-field", style: { justifyContent: "flex-end", paddingBottom: "6px" } },
                    check("allowPrivate", t.formAllowPrivate)))] : [])]));
            const problem = h("div", { class: "hc-formError", hidden: true });
            const save = h("button", { type: "button", class: "btn primary", onClick: submit }, t.save);
            const buttons = [save, h("button", { type: "button", class: "btn outline", onClick: close }, t.cancel),
              target ? h("button", { type: "button", class: "hc-link", "data-danger": true,
                onClick: () => { close(); confirmDeleteTarget(target); } }, t.targetsDelete) : null].filter(Boolean);
            const busy = (on) => { for (const button of buttons) button.disabled = on; save.textContent = on ? t.saving : t.save; };
            async function submit() {
              if (save.disabled) return;
              busy(true); problem.hidden = true;
              const auth = d.type === "bearer" ? { token: d.auth.token }
                : d.type === "basic" ? { username: d.auth.username, password: d.auth.password }
                  : d.type === "none" ? {} : { name: d.auth.name, value: d.auth.value };
              const allowedHosts = d.allowedHosts.split(/\r?\n/).map((host) => host.trim()).filter((host) => host !== "");
              try {
                await saveTarget(spec, { name: d.name, baseUrl: d.baseUrl, auth: { type: d.type, ...auth },
                  headers: rowsToRecord(d.headers), variables: rowsToRecord(d.variables), allowedHosts,
                  allowMutations: d.allowMutations, allowPrivate: d.allowPrivate, timeoutMs: Number(d.timeoutMs) });
                close();
              } catch (err) { problem.textContent = message(err); problem.hidden = false; busy(false); }
            }
            const base = text("baseUrl", { class: "input hc-input mono", placeholder: "https://api.example.com/v1",
              autocapitalize: "off", spellcheck: "false" });
            box.firstChild.append(
              h("div", { class: "modalHead" }, target ? t.formEdit(target.name) : t.formCreate),
              h("div", { class: "modalBody" }, h("form", { class: "hc-form", onSubmit: (event) => { event.preventDefault(); submit(); } },
                h("div", { class: "hc-formRow" }, field(t.formBaseUrl, base, { style: { flex: "2" } }),
                  field(t.formName, text("name", { placeholder: t.formNamePlaceholder }))),
                authBox,
                h("div", { class: "hc-field" }, h("span", { class: "hc-fieldLabel" }, t.formHeaders),
                  kvEditor({ name: "headers", rows: d.headers, onChange: (rows) => { d.headers = rows; }, view: {} })),
                check("allowMutations", t.formAllowMutations), moreBox, problem, h("button", { type: "submit", hidden: true }))),
              h("div", { class: "modalFoot" }, buttons[2], h("span", { class: "spacer" }), buttons[1], save));
            drawAuth(); drawMore(); base.focus();
          }

          // -------------------------------------------------------- divider, shortcut
          function setSplit(value) {
            panes.style.setProperty("--hc-split", `${value}%`);
            try { localStorage.setItem(SPLIT_KEY, String(value)); } catch { /* optional */ }
          }
          // Drag the divider: the request pane takes the pointer's share of the panes box, along its main axis.
          function onDividerDown(event) {
            event.preventDefault();
            divider.setPointerCapture(event.pointerId);
            const move = (e) => {
              const rect = panes.getBoundingClientRect();
              const column = getComputedStyle(panes).flexDirection === "column";
              const ratio = column ? (e.clientY - rect.top) / rect.height : (e.clientX - rect.left) / rect.width;
              setSplit(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, Math.round(ratio * 1000) / 10)));
            };
            const up = () => {
              divider.removeEventListener("pointermove", move);
              divider.removeEventListener("pointerup", up);
              divider.removeEventListener("pointercancel", up);
            };
            divider.addEventListener("pointermove", move);
            divider.addEventListener("pointerup", up);
            divider.addEventListener("pointercancel", up);
          }
          function onKeydown(event) {
            if (dialog || !(event.metaKey || event.ctrlKey) || event.key !== "Enter") return;
            event.preventDefault();
            send();
          }

          function renderAll() { renderHead(); renderBanner(); renderSide(); renderRequest(); renderResponse(); }
          const onHide = () => flushAll(true);
          window.addEventListener("pagehide", onHide);
          document.addEventListener("mousedown", onDocumentDown);
          document.addEventListener("keydown", onDocumentKey);
          renderAll(); refresh();
          return () => {
            alive = false;
            if (dialog) dialog();
            clearInterval(pollTimer);
            flushAll();
            window.removeEventListener("pagehide", onHide);
            document.removeEventListener("mousedown", onDocumentDown);
            document.removeEventListener("keydown", onDocumentKey);
          };
        }

        ctx.slots.register({ slot: "sidebar.panellist", id: "http-client", label: t.entry, icon: "globe", description: t.intro, order: 52 });
        ctx.slots.register({ slot: "main", key: "http-client", label: t.entry }, page);
      },
    };
  },
});
