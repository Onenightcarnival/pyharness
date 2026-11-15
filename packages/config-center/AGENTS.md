# pyharness-config-center

配置中心：MCP 页、用户技能、JavaScript MCP 服务器的受管 bun 运行时。

| 项 | 值 |
|---|---|
| 条目 | `config-center`（`toolkit` bundle） |
| 服务 | `ConfigCenterService`，`ctx.configCenter` |
| 注入 | `http`、`webui`、`agentLoop` |
| 路由前缀 | `/api/config-center` |
| 数据根 | `<profile data>/toolkit/` |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | `ConfigCenterService`、`Config`、路由 |
| `skills.py` | `SkillStore`：用户技能 |
| `environment.py` | `BunManager`：受管 bun |
| `config.toml` | 受管 bun 的常量；`environment.py` 读取 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `skills` | `SkillStore`：`toolkit/skills/` 与 `toolkit/disabled-skills/` |
| `bun` | `BunManager`：`toolkit/bun/` 下固定版本的 bun |

| 配置 | 含义 | 默认 |
|---|---|---|
| `bun_version` | 安装的 bun 版本 | `BUN_VERSION` |
| `skills_presets` | 能看到用户技能的 agent 预设 | 全部 |

## 路由

| 路径 | 方法 | 作用 |
|---|---|---|
| `mcp` | GET | 服务器列表、连接状态、启动等待秒数 |
| `mcp/test` | POST | 连接一份服务器配置，列出它的工具 |
| `mcp/timeout` | PUT | 启动等待秒数 |
| `mcp/credentials` | PUT、DELETE | 凭据值 |
| `skills` | GET、POST、DELETE | 列表、启停、删除 |
| `skills/detail` | GET | 一个技能的信息与文件树 |
| `skills/file` | GET | 一个技能里的文件 |
| `skills/install` | POST | ZIP 安装 |
| `skills/open` | POST | 在系统文件管理器中打开目录 |
| `environment` | GET、POST | bun 状态、安装 |

MCP 服务器列表的保存：API 的 `PUT /api/settings/mcp`，重启后生效。

### `mcp/credentials`

| 请求 | 契约 |
|---|---|
| `PUT` `{reference, value}` | 值存入 profile 凭据库；名称或值非法 → 400 |
| `DELETE ?reference=` | 删除已存的值 |
| 应答 | `{credential: {reference, configured, source}, application}` |

| `application` | 条件 |
|---|---|
| `restart-scheduled` | 凭据库有变化，且被启用的 MCP 服务器引用，受托管 |
| `saved-restart-required` | 同上，未受托管 |
| `saved` | 其余情况 |

## 用户技能（`skills.py`）

| 目录 | 状态 |
|---|---|
| `<profile data>/toolkit/skills/<name>/SKILL.md` | 启用；挂载给 agent：`/skills/user/` |
| `<profile data>/toolkit/disabled-skills/` | 停用；保留，不挂载 |

| 操作 | 方式 |
|---|---|
| 启用、停用 | 在两个目录之间移动技能目录 |
| 安装 | ZIP |
| 删除、读文件 | 按技能名 |
| 列表 | 含 `SKILL.md` 的目录 |

| 技能名 | 规则 |
|---|---|
| 形式 | 一个可见、可移植的路径段 |
| 长度 | 至多 128 个字符 |

| ZIP 安装 | 规则 |
|---|---|
| 解压 | 每个条目保留路径与字节；不读取文件内容 |
| 安装单元 | 每个顶层条目一个，以条目名命名；同名的已有条目整体替换 |
| 顶层 `.md` | 存为 `<name>/SKILL.md` |
| 可执行位 | 归档记录了才设置（Unix 或 macOS 主机写出的归档） |
| `__MACOSX` | 不解压 |
| 上限 | 归档 32 MB；解压后 100 MB、4000 个条目 |

## 受管 bun（`environment.py`）

| 项 | 契约 |
|---|---|
| 位置 | `<profile data>/toolkit/bun/` |
| 版本 | 固定：`BUN_VERSION` |
| 校验 | 发行版的 `SHASUMS256.txt` |
| 使用方 | 命令为裸 `bun` / `bunx` 的 MCP 服务器：`pyharness_mcp.managed_bun` |
| `PATH` | 不改动 |

| `config.toml` 的键 | 含义 |
|---|---|
| `BUN_VERSION` | 固定的 bun 版本 |
| `RELEASE` | 发行资产的下载 URL 模板（`{version}`、`{asset}`）；`SHASUMS256.txt` 同源 |
| `TARGETS` | `(system, machine)` → bun 发行目标；未列出的平台不受支持 |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「MCP」页 | 服务器、编辑器、凭据、连接测试、启动等待 |
| 左侧栏「技能」页 | 用户技能、ZIP 安装、文件 |
| 设置 →「环境依赖」 | 受管 bun |
