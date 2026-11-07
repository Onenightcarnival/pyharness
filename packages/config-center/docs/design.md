# pyharness-config-center

`ctx.configCenter`：配置中心（对齐 dsh-config-center）：MCP 页（服务器、连接测试、启动等待）、用户 skills、受管 bun 运行时。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__` | `Config`、`ConfigCenterService`；`/api/config-center` 路由 |
| `environment` | `BunManager`：固定版本 bun 的下载、`SHASUMS256.txt` 校验、原子替换、状态；`BUN_VERSION`、`target_of`、`bun_env` |
| `skills` | `SkillStore`：`toolkit/skills/`（启用）与 `toolkit/disabled-skills/`（停用）；列表、详情、文件预览、ZIP 安装、启停、删除、打开目录；`fenced` 路径围栏 |
| `client.js` | 浏览器模块：「MCP」页、「技能」页、设置 →「环境依赖」分区 |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `BunManager` | 类 | `BunManager(root, version=BUN_VERSION)`：`status()`、`install()`、`wait()`、`installed_version()`、`exe`、`bunx` |
| `ConfigCenterService` | 类 | `Service`，key `configCenter`；属性 `skills`、`bun` |
| `SkillStore` | 类 | `SkillStore(base)`：`list`、`locate`、`detail`、`read_file`、`set_enabled`、`remove`、`exists`、`install_zip`、`open_folder`；`enabled_dir`、`disabled_dir` |

## 服务

| 项 | 值 |
|---|---|
| key | `configCenter` |
| name | `pyharness-config-center` |
| inject | `http`、`webui`、`agentLoop` |
| `Config.bun_version` | `BUN_VERSION` = `"1.4.4"` |
| `Config.skills_presets` | `None`；看到用户 skills 的预设，`None` 为全部 |
| 数据根 | `<profile data>/toolkit/`；无 profile 时 `~/.pyharness/data/toolkit/` |
| `start()` | `SkillStore(data)`、`BunManager(data/"bun", bun_version)`；`ctx.agentLoop.add_skills(skills.enabled_dir, "user", presets=skills_presets)`（挂载为 `/skills/user/`）；`ctx.http.include_router(prefix="/api/config-center", tags=["pyharness-config-center"])`；`ctx.webui.register_client(client.js)` |
| `stop()` | 无 |

| `BunManager` | 契约 |
|---|---|
| `status()` | `state`（`downloading` / `verifying` / `installing` / `unsupported` / `missing` / `ready` / `error`）、`ready`、`supported`、`target`、`recommendedVersion`、`path`、`dataDirectory`、`version`?、`progress`?、`error`? |
| `install()` | 后台线程，一次一个；立即返回 `status()`；不支持的平台 → `RuntimeError` |
| 安装步骤 | 取 `installation` 锁文件（等待至多 360 秒）→ 下载 `bun-<target>.zip`（上限 200 MB，超时 300 秒）→ 比对 `SHASUMS256.txt` → 解出 `bun` 到临时目录，`bunx` 为符号链接（Windows 复制）→ `--version` 等于配置版本 → 原子换入 `bin/`（旧版先改名备份）→ 写 `installed.json` |
| 支持平台 | darwin arm64 / x86_64、linux x86_64 / aarch64（非 musl）、win32 amd64 / x86_64 |

| `SkillStore` | 契约 |
|---|---|
| skill 名 | `^[a-z0-9]+(?:-[a-z0-9]+)*$`，至多 64 字符 |
| `list()` | 两个目录合并，启用副本优先；每项 `name`、`description`、`version`、`kind: "bundle"`、`enabled` |
| `detail(name)` | 另含 `path`、`entryFile: "SKILL.md"`、`frontmatter`、`files`（深 12 层、至多 400 项、跳过符号链接与 `.git` / `node_modules`）、`truncated` |
| `read_file(name, rel)` | 文本至多 256 KB；含 `\0` → 拒绝 |
| `install_zip(data, filename, policy)` | ZIP 上限 32 MB、解压 100 MB、4000 项；根 `SKILL.md` → 以文件名命名的一个 skill；`<dir>/SKILL.md` → 各一个；顶层 `*.md`（非 `readme.md`）→ `<name>/SKILL.md`；`policy`：`ask`（有冲突时只报告）、`skip`、`replace`（备份后覆盖并启用） |
| `set_enabled` / `remove` | 移动目录 / 删除两处同名目录 |
| `open_folder(name?)` | `open` / `explorer.exe` / `xdg-open` |

## 路由

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/config-center/mcp` | | `{"servers": ctx.mcp.servers(), "connectTimeout"}`；无 `mcp` 服务 503 |
| PUT | `/api/config-center/mcp/timeout` | `{"connectTimeout": 1..86400}` | `manage.set_entry_config("mcp", {"connect_timeout"}, merge=True, preflight=False)` 并就地更新；拒绝 422 |
| POST | `/api/config-center/mcp/test` | `{"name"?, "server": ServerConfig, "timeout"?}` | `{"result": ctx.mcp.probe(cfg)}`；`env` / `headers` 中的 `"••••"` 以已保存值代入，无已保存值 422 |
| GET | `/api/config-center/skills` | | `{"directory", "skills"}` |
| POST | `/api/config-center/skills` | `{"name", "enabled"}` | 启停后返回列表 |
| DELETE | `/api/config-center/skills?name=` | | 删除后返回列表 |
| GET | `/api/config-center/skills/detail?name=` | | `SkillStore.detail` |
| GET | `/api/config-center/skills/file?name=&file=` | | `{"text", "size", "truncated"}` |
| POST | `/api/config-center/skills/install` | `{"filename", "data": base64, "policy": "ask" / "skip" / "replace"}`（体积上限约 32 MB 的 base64） | `{"installed", "skipped", "conflicts"}` |
| POST | `/api/config-center/skills/open?name=` | | `{"ok": true}` |
| GET | `/api/config-center/environment` | | `BunManager.status()` |
| POST | `/api/config-center/environment` | | 202，启动安装并返回状态 |

| 错误 | 状态码 |
|---|---|
| 请求体超限 / 非 JSON 对象 | 413 / 400 |
| `SkillError` | 400 |
| 无 profile | 503 |

MCP 服务器列表的保存经 `PUT /api/settings/mcp`（`pyharness-api`），重启生效。

## Web UI

| 槽位 | key / id | order | 内容 |
|---|---|---|---|
| `sidebar.panellist` | `mcp` | 55 | 「MCP」入口 |
| `main` | `mcp` | | 服务器列表与状态、编辑器、连接测试、启动等待、粘贴 `mcpServers` JSON 导入 |
| `sidebar.panellist` | `skills` | 56 | 「技能」入口 |
| `main` | `skills` | | skills 列表、ZIP 安装、启停、删除、文件预览、打开目录 |
| `settings.sections` | `environment` | 120 | 受管 bun 的状态与安装 |

## 数据

| 路径 | 内容 |
|---|---|
| `<profile data>/toolkit/skills/<name>/SKILL.md` | 启用的用户 skill；挂载为 `/skills/user/` |
| `<profile data>/toolkit/disabled-skills/<name>/` | 停用的 skill |
| `<profile data>/toolkit/bun/bin/bun`、`bunx` | 受管 bun |
| `<profile data>/toolkit/bun/cache/` | bun 缓存（`BUN_INSTALL_CACHE_DIR`） |
| `<profile data>/toolkit/bun/installed.json` | `version`、`target`、`installedAt` |
| `<profile data>/toolkit/bun/installation` | 安装锁文件 |
| 条目 `mcp` 的 `config.connect_timeout` | profile patch，经 `PUT /mcp/timeout` 写入 |
