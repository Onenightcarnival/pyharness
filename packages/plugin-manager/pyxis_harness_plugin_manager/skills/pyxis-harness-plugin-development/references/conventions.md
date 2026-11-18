# Code conventions

The packages shipped with the harness follow these conventions; a plugin written here follows them too. A shipped package is a worked example: `harness_inspect topic=config name=<entry id>` returns its `package_dir` and `docs`, the path of its `AGENTS.md` (`s3`, `memory`, `gateway` are multi-module packages).

## Layout

A plugin that fits one file is `<module>/plugin.py`, as in the templates. A plugin that outgrows one file splits into modules:

```
AGENTS.md         # design of the package
pyproject.toml
<module>/
  __init__.py     # imports of the public names, __all__; no other code
  plugin.py       # a function plugin: name, doc, inject, Config, apply
  bundle.py       # BUNDLE: the path of bundle.yaml
  config.py       # Config (pydantic); a leaf every other module may import
  service.py      # the Service subclass: lifecycle, wiring, public methods
  tools.py        # LangChain tools bound to the service
  routes.py       # FastAPI router bound to the service
  <domain>.py     # stores, clients, parsers; no import of service.py
  config.toml     # constants: limits, defaults, tables
  prompts.toml    # model-visible text
  client.js       # browser module (ui-plugin.md)
  bundle.yaml
```

| subject | rule |
|---|---|
| `AGENTS.md` | the design of the package, beside `pyproject.toml`: one sentence, an overview table (entry, service or `apply`, inject), a table of files, then one section of tables per subject (configuration, routes, events, storage, rules) |
| file headers | none: no module docstring, no leading comment block in `.toml` or `client.js`; class and function docstrings stay |
| `__init__.py` | imports only: `from .x import …` and `__all__` with the names other packages may import; every definition, constant included, lives in a named module |
| `doc` | a function plugin states its one-line description as the module attribute `doc`, beside `name` and `inject`; a service plugin's description is the docstring of its `Service` class |
| imports between modules | a module imports its siblings (`from .store import Store`), never the package `__init__` |
| dependency direction | `service.py` imports `tools.py` and `routes.py`; they do not import `service.py` |
| what `tools.py` / `routes.py` need from the service | a `typing.Protocol` in that module listing only the members it uses; with one or two members, pass them as arguments instead |
| `if TYPE_CHECKING:` | not used; an import cycle is removed with a Protocol or by moving the class to a leaf module |
| a class several modules need | a leaf module (`config.py` for `Config`) |

```python
# tools.py
class Host(Protocol):
    """The service, as the tools use it."""

    store: Store

    async def run(self, name: str) -> str: ...


def build_tools(service: Host) -> list[Any]: ...
```

## Modules

| subject | rule |
|---|---|
| first statement | `from __future__ import annotations` |
| imports | at the top of the file, none inside a function; an optional dependency is imported at the top in `try` / `except ImportError` with a `None` sentinel |
| `inject` on a `Service` subclass | `inject: ClassVar[list[str]] = ["tools"]`; the module-level `inject = ["tools"]` of an `apply` plugin stays a plain list |
| line width | 120 |
| multi-line text | triple-quoted, indented with the code, `dedent("""…""").strip()` |
| exception classes | end in `Error`; never the name of a builtin (`MemoryError`, `KeyError`) |
| files and paths | `pathlib` (`path.open()`, `path.replace()`, `path.chmod()`) |
| a failure that is ignored | `with contextlib.suppress(SomeError):` |
| `subprocess.run` | states `check=` |

## Data files

| content | where | read with |
|---|---|---|
| what a user configures | `Config` | the entry's `config` in the patch |
| constants a user does not configure: limits, defaults, endpoint tables | `config.toml` | `pyxis_harness.package_toml(__file__)` |
| model-visible text: tool descriptions, prompt sections, messages returned to the model | `prompts.toml` | `pyxis_harness.package_prompts(__file__)`; every string is stripped |

`config.toml` and `prompts.toml` sit beside the module that reads them, one table per module. A key bound to a Python constant carries the constant's name; other keys (tool names) are lower case:

```toml
# config.toml
[tools]
MAX_ROWS = 500

# prompts.toml
[tools]
notes_add = """
Keep a short note. Returns the note count.
"""
too_long = "note rejected: longer than ${limit} characters"
```

```python
_CFG = package_toml(__file__)["tools"]
PROMPTS = package_prompts(__file__)["tools"]
MAX_ROWS: int = _CFG["MAX_ROWS"]


@tool("notes_add", description=PROMPTS["notes_add"])
def notes_add(text: str) -> str: ...
```

Placeholders in prompt text are `string.Template` fields (`${limit}`; `$$` is a literal `$`). Every file under the package directory ships with the distribution; `AGENTS.md` ships through `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml`, as in the templates. A one-file plugin keeps its tool description in the function docstring.

## Dependencies

`dependencies` lists only packages the harness does not provide, each pinned to an exact version (`httpx==0.28.1`).

## Text

`AGENTS.md`, comments, docstrings, tool descriptions and prompt sections state the contract in the present tense: behavior, inputs and outputs, failures, ownership. No history, no reasoning, no instructions to the reader. One fact is written in one place.
