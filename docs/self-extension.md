# agent 自扩展

agent 编写插件、安装进自己的 profile，在下一代中使用。

## 流程

```
agent ──harness_inspect──────────────▶ 服务方法、事件模式、配置 schema、工具、路由
      ──plugin_manager template───────▶ bundle 模板 → 工作区 /plugins/<name>/
      ──plugin_manager install_bundle─▶ [人工批准] → 安装到 profile site/
                                         → 预检（独立进程）
                                            ├ 拒绝：恢复快照，错误返回 agent
                                            └ 保存：本轮结束后重启
supervisor ──▶ 第 N+1 代 ──▶ 续跑消息 ──▶ agent 验证新能力
```

## 工具

### `harness_inspect`

只读。

| topic | 内容 |
|---|---|
| `overview` | 代、profile、条目计数、服务 key、事件 |
| `services` | 服务 key；带 `name`：类型、归属、方法 |
| `events` | 名称、模式、声明方、监听者 |
| `plugins` | Loader 条目与状态 |
| `config` | 条目；带 `name`：config JSON Schema、生效配置、包目录 |
| `tools` | 已注册工具与审批闸门；带 `name`：参数 schema |
| `routes` | HTTP 路由及其贡献插件 |
| `prompt` | 系统提示词片段 |

生效配置中来自 `${env:...}` 的值、名称类似密钥的字段：脱敏。

### `plugin_manager`

| action | 参数 | 审批 | 效果 |
|---|---|---|---|
| `list` | — | 否 | 条目与状态；已安装 bundle |
| `template` | `target=<name>` | 否 | bundle 模板文件 |
| `install_bundle` | `target=<dir>` | 是 | 从工作区目录安装 bundle |
| `uninstall_bundle` | `target=<bundle>` | 是 | 移除已安装的 bundle |
| `set_bundle_enabled` | `target=<bundle> enabled=<bool>` | 是 | 启用 / 停用 bundle |
| `set_plugin_enabled` | `target=<entry id> enabled=<bool>` | 是 | 启用 / 停用条目 |
| `restart` | — | 是 | 本轮结束后重启 |

| `application` | 含义 |
|---|---|
| `rejected` | 预检失败；profile 未变 |
| `restart-scheduled` | 已保存；受 supervisor 管理，本轮结束后重启，本会话续跑 |
| `saved-restart-required` | 已保存；不受 supervisor 管理，下次启动生效 |
| `unchanged` | 无变化 |

| 配置 | 默认 | 效果 |
|---|---|---|
| `require_approval` | `true` | 变更动作需人工批准 |
| `guidance` | `true` | 系统提示词中的插件编写片段 |

## 边界

| 防线 | 范围 |
|---|---|
| 审批 | `plugin_manager` 的全部变更动作 |
| 工具管线 | `tools/execute`、`tools/result` 覆盖 deepagents 子 agent（`task`）内的工具调用 |
| 审批闸门归属 | 一个插件撤不掉另一个插件的闸门 |
| 工作区 | 工作区根目录位于 harness home 之内 → 插件失败；harness home 位于工作区之内 → 文件工具对其读写一律拒绝 |

- 安装的插件代码运行在 harness 进程内，权限同 harness 进程，不受工作区限制。
- 审批是安装代码的唯一闸门。
