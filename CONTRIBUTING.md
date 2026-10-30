# 参与开发

## 环境

Python 3.12（`.python-version`），uv。

```bash
uv sync                         # workspace 与 dev 依赖组
uv run pytest -q                # 全部测试
uv run ruff format .            # 格式化
uv run ruff check --fix .       # lint；规则见 pyproject.toml [tool.ruff]
uv run python scripts/gen_packages.py   # 新增或改动插件包后：重新生成 skills 的包清单
```

| 测试 | 条件 |
|---|---|
| `tests/test_postgres.py` | `PYH_TEST_POSTGRES_DSN` 指向可写的 UTF8 数据库；未设置时跳过 |
| `tests/test_live.py`、`tests/test_supervisor.py` | 真实子进程；本机空闲端口 |

```bash
PYH_TEST_POSTGRES_DSN=postgresql://user@127.0.0.1:5432/pyh_test uv run pytest -q tests/test_postgres.py
```

## 目录

| 路径 | 内容 |
|---|---|
| `packages/core` | 内核：服务容器、事件、组合、Loader、生命周期、CLI |
| `packages/*` | 内核插件；每个包一个 entry point |
| `packages/bundle-base` | `base` bundle |
| `packages/bundle-creator` | `creator` bundle：插件编写 skills |
| `packages/plugin-manager/src/pyharness_plugin_manager/skills` | agent 可读的 skills；`references/packages.md` 由 `scripts/gen_packages.py` 生成 |
| `scripts/` | 维护脚本 |
| `examples/pyharness-audit` | 第三方 bundle 示例；不属于 workspace |
| `examples/patches` | patch 示例：Postgres、shell |
| `tests/` | 测试 |
| `tests/testkit` | 测试用插件 |
| `docs/` | 设计文档 |
| `.github/workflows/ci.yml` | CI，Python 3.12：全量测试；Postgres 测试 |

## 写作规范

适用于代码注释、文档字符串、文档、界面文案、模型可见文本（系统提示词、工具描述、续跑消息）。

| 规则 | 写法 | 不写 |
|---|---|---|
| 声明式 | 现在时陈述句：「返回…」「`x` 是…」「失败时抛出…」 | 「我们…」「这里会…」「接下来…」 |
| 不自我解释 | 只写契约 | because、so that、note、「这样做是为了」「这意味着」「否则」 |
| 只呈现设计结果 | 当前的行为、输入输出、失败方式、时序、所有权 | 历史、变更过程、被否决的方案、推导过程 |
| 结构优先 | 表格、列表、短标题；一行一个事实 | 长段落、括号插话 |
| 一个事实一个归属 | 在归属处写一次，其余处链接 | 复述 |

落到具体位置：

| 位置 | 形式 |
|---|---|
| 模块文档字符串 | 一句话定位 + 契约列表或表格 |
| 函数文档字符串 | 一句话；签名表达不了的参数、返回值、异常才单列 |
| 行内注释 | 只写代码表达不了的不变量；不复述代码 |
| 文档 | 中文；术语首次出现附英文原名 |
| 代码、注释、文档字符串 | 英文 |
| 界面文案 | 中英两套，按浏览器语言选择 |

## 提交

| 规则 | 内容 |
|---|---|
| 粒度 | 一个提交一件事 |
| 说明首行 | 英文祈使句，不超过 72 个字符 |
| 提交前 | `uv run ruff format .`、`uv run ruff check .`、`uv run pytest -q` 通过；CI 检查格式与 lint |
