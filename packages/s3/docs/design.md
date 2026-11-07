# pyharness-s3

S3 兼容对象存储（object storage）浏览器：MinIO / OSS / COS / R2 / AWS 的桶配置、`s3_*` 工具与 S3 页面。

## 模块

| 模块 | 职责 |
|---|---|
| `__init__.py` | 契约文档；从 `service` 导出公开名；`__all__` |
| `service.py` | `S3Service`、`Config`、提示段 `GUIDANCE`、按配置文件缓存 boto3 客户端、工具与提示段的注册同步 |
| `tools.py` | 11 个 `s3_*` LangChain 工具与 `CopyArgs` 参数模型；结果为模型可读文本 |
| `routes.py` | `/api/s3` 下的 FastAPI 路由；流式下载、原始请求体上传 |
| `engine.py` | `Bucket`：对 boto3 客户端的操作，键相对配置前缀；MIME 表、`clean_key`、`error_text`、`human` |
| `store.py` | `ProfileStore`：`s3.json` 的读写、校验、名称去重；密钥存凭据库 |
| `client.js` | 浏览器模块 `s3`：侧栏「S3」入口与页面（桶配置、对象浏览、上传下载、分享链接、删除、Agent 开关） |

## 对外 API

| 名称 | 类型 | 说明 |
|---|---|---|
| `S3Service` | `Service` 子类 | 服务键 `s3`；entry point `pyharness-s3 = "pyharness_s3:S3Service"` |
| `Config` | pydantic 模型 | 服务配置：`path`、`approval` |
| `GUIDANCE` | `str` | 提示段文本，工具开启时注入系统提示 |

## 服务

| 项 | 值 |
|---|---|
| 服务键 | `s3`，名称 `pyharness-s3` |
| 注入 | `tools`、`prompt`、`http` |
| `Config.path` | 配置文件路径；默认 `<profile data>/toolkit/s3.json`，无 profile 时 `~/.pyharness/data/toolkit/s3.json` |
| `Config.approval` | `s3_delete` 的审批门槛；默认 `False` |
| `start()` | 建 `ProfileStore`（凭据来自 `ctx.profile.credentials`，缺省为内存实现）；挂载路由；`sync()`；向 `webui` 注册 `client.js` |
| `stop()` | 注销工具与提示段；清空客户端缓存 |
| `sync()` | 依据 `settings.agentTools` 注册或注销全部工具与提示段；返回当前是否已注册 |
| 配置变更 | 文件每次写入后清空客户端缓存并 `sync()` |
| `bucket(profile)` | 按 `profile.id` 与 `updatedAt` 缓存 boto3 客户端；返回 `Bucket` |
| `run(id_or_name, fn)` | 在工作线程中以该配置的 `Bucket` 调用 `fn` |

## 事件 / 工具 / 路由 / 提示段

### 工具

全部工具标签 `("s3",)`；仅 `s3_delete` 使用 `Config.approval`，其余审批为 `False`；工具只在 Agent 开关打开时存在。

| 工具 | 作用 |
|---|---|
| `s3_buckets` | 列出桶配置（名称、bucket、endpoint、region、前缀） |
| `s3_list` | 列一级目录或递归遍历；分页 `token`；默认 200 条，上限 500 |
| `s3_stat` | HEAD 一个对象 |
| `s3_get` | 读文本对象；默认 200 KiB，上限 2 MiB；二进制拒绝 |
| `s3_put` | 写文本对象（覆盖） |
| `s3_upload` | 本机文件上传（自动分片） |
| `s3_download` | 对象下载到本机路径（自动建父目录） |
| `s3_copy` | 服务端复制或移动（`from` 别名为 `from_`） |
| `s3_presign` | 预签名 URL；GET 或 PUT；默认 3600 秒，上限 604800 |
| `s3_mkdir` | 创建文件夹标记对象 |
| `s3_delete` | 永久删除；`/` 结尾的键递归；需 `confirm=true` |

### 路由

前缀 `/api`，标签 `pyharness-s3`；JSON 请求体默认上限 64 KiB。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/s3/profiles` | 配置摘要列表（不含密钥） |
| POST | `/s3/profiles` | 新建配置；201 |
| PATCH | `/s3/profiles?id=` | 更新配置 |
| DELETE | `/s3/profiles?id=` | 删除配置及其凭据 |
| GET | `/s3/settings` | `{agentTools}` |
| POST | `/s3/settings` | 设置 `agentTools` 后 `sync()` |
| POST | `/s3/test` | 连接测试：延迟与样例键 |
| GET | `/s3/list?id=&prefix=&token=&max=` | 一级目录分页，默认 1000 条 |
| GET | `/s3/stat?id=&key=` | 对象元数据 |
| GET | `/s3/text?id=&key=` | 文本预览，上限 512 KiB |
| GET | `/s3/object?id=&key=&inline=1` | 流式下载；可预览类型在 `inline=1` 时内联 |
| PUT / POST | `/s3/upload?id=&key=` | 原始请求体上传；上限 50 GiB |
| POST | `/s3/delete` | 批量删除，请求体上限 1 MiB |
| POST | `/s3/folder` | 创建文件夹标记 |
| POST | `/s3/presign` | 预签名 URL |
| POST | `/s3/copy` | 复制或移动 |

### 提示段

| id | order | 文本 |
|---|---|---|
| `plugin:s3` | 152 | `GUIDANCE` |

### Web UI

| 槽位 | 值 |
|---|---|
| `sidebar.panellist` | id `s3`，图标 `archive`，order 50 |
| `main` | key `s3`，S3 页面 |

## 数据

| 项 | 值 |
|---|---|
| 配置文件 | `<profile data>/toolkit/s3.json`；权限 0600；临时文件替换写入；损坏时改名 `s3.json.corrupt-<ms>` |
| 文件结构 | `{version: 1, settings: {agentTools: bool}, profiles: [...]}` |
| 配置记录 | `id`（12 位十六进制）、`name`（唯一，不区分大小写）、`bucket`、`endpoint`、`region`（默认 `us-east-1`）、`accessKeyId`、`pathStyle`、`prefix`（以 `/` 结尾）、`createdAt`、`updatedAt`（毫秒） |
| 摘要字段 | 配置记录去掉 `accessKeyId`，加 `accessKeyHint`（前 4 位 + 后 2 位） |
| 凭据引用 | `S3_<ID 大写>`：Secret Access Key，存于 profile 凭据库 |
| 校验 | `name` 匹配 `^[^\W_][\w .-]{0,63}$`；`bucket` 匹配 `^[a-z0-9][a-z0-9.-]{1,62}$`；`endpoint` 为 http(s) 完整 URL |
