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
| `packages/*/AGENTS.md` | 子包的设计文档；代码文件不带文件头文档 |
| `packages/*/<模块>/__init__.py` | 导入与 `__all__`；实现在具名模块中（`service.py`、`plugin.py`、`bundle.py`） |
| `packages/meta` | `pyxis-harness`：只有依赖的入口发行包 |
| `packages/bundle-base` | `base` bundle |
| `packages/bundle-creator` | `creator` bundle：插件编写 skills |
| `packages/plugin-manager/pyxis_harness_plugin_manager/skills` | agent 可读的 skills；`references/packages.md` 由 `scripts/gen_packages.py` 生成 |
| `scripts/` | 维护脚本 |
| `examples/pyxis-harness-audit` | 第三方 bundle 示例；不属于 workspace |
| `examples/patches` | patch 示例：Postgres、shell |
| `tests/` | 测试 |
| `tests/testkit` | 测试用插件 |
| `docs/` | 设计文档 |
| `manual/` | 用户手册；`images/`：界面的整页截图，1280×800，8 位调色板 PNG |
| `.github/workflows/ci.yml` | CI，Python 3.12：全量测试；Postgres 测试 |

## 代码、文档、注释统一风格要求

1. 声明式。
2. 不自我解释，仅呈现设计结果。
3. 通过结构让读者一眼看明白逻辑。

## 提交

| 规则 | 内容 |
|---|---|
| 粒度 | 一个提交一件事 |
| 说明首行 | 英文祈使句，不超过 72 个字符 |
| 提交前 | `uv run ruff format .`、`uv run ruff check .`、`uv run pytest -q` 通过；CI 检查格式与 lint |
