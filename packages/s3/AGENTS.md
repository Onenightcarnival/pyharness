# pyxis-harness-s3

S3 兼容对象存储浏览器（MinIO / OSS / COS / R2 / AWS）。

| 项 | 值 |
|---|---|
| 条目 | `s3`（`toolkit` bundle） |
| 服务 | `S3Service`，`ctx.s3` |
| 注入 | `tools`、`prompt`、`http` |
| 路由前缀 | `/api/s3` |
| 数据 | `<profile data>/toolkit/s3.json`；secret key 在 profile 凭据库 |

## 文件

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 |
| `service.py` | `s3` 服务：profile、缓存的 boto3 client、`s3_*` 工具注册、提示词段 |
| `store.py` | 桶 profile 与 agent 访问设置 |
| `engine.py` | boto3 client 之上的 S3 操作；在此边界上 key 相对于 profile 前缀；client 的 `proxies` 为空，环境变量的代理设置不生效 |
| `tools.py` | `s3_*` LangChain 工具 |
| `routes.py` | S3 页的 FastAPI 路由 |
| `config.toml` | 包数据；`pyxis_harness.package_toml(__file__)` 加载 |
| `prompts.toml` | 模型可见文本；`pyxis_harness.package_prompts(__file__)` 加载 |
| `client.js` | 浏览器模块 |

## 服务

| 成员 | 契约 |
|---|---|
| `store` | `ProfileStore`：桶 profile（secret key 在凭据库）、agent 访问设置 |
| `bucket(p)` | 一个 profile 的 `Bucket`；boto3 client 按 profile 缓存 |
| `sync()` | agent 访问开启期间注册 `s3_*` 工具与提示词段 |

| 配置 | 含义 |
|---|---|
| `path` | profile 文件；默认 `<profile data>/toolkit/s3.json` |
| `approval` | `s3_delete` 的审批门；默认无 |

## Profile

| 项 | 契约 |
|---|---|
| 范围 | 一个 profile 是一个桶 |
| 字段 | endpoint、region、keys、path-style 标志、可选的范围前缀 |
| key | 工具与路由所见的每个 key 都相对于该前缀 |

## 工具

| 项 | 契约 |
|---|---|
| 工具 | `s3_buckets`、`s3_list`、`s3_stat`、`s3_get`、`s3_put`、`s3_upload`、`s3_download`、`s3_copy`、`s3_presign`、`s3_mkdir`、`s3_delete` |
| 形状 | 同 dsh-s3 |
| 结果 | 给模型的文本 |
| `s3_delete` | 需要 `confirm=true` |

## 路由

| 项 | 内容 |
|---|---|
| 使用方 | S3 页 |
| 路径 | `profiles`、`settings`、`test`、`list`、`stat`、`text`、`object`、`upload`、`delete`、`folder`、`presign`、`copy` |
| `object` | 下载 / 行内预览 |
| `upload` | 原始请求体 |

## 存储（`store.py`）

| 项 | 位置 |
|---|---|
| 桶 profile、agent 访问设置 | `<profile data>/toolkit/s3.json` |
| secret key | profile 凭据库，引用 `S3_<ID>` |

## 浏览器模块（`client.js`）

| 位置 | 内容 |
|---|---|
| 左侧栏「S3」页 | 桶 profile、对象浏览器（上传 / 下载 / 预览 / 分享链接 / 重命名 / 文件夹 / 删除）、agent 访问开关 |
