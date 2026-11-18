from __future__ import annotations

from functools import lru_cache
from html import escape

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.util import ClassNotFound

from pyxis_harness import package_toml

MAX_CHARS = 400_000
FORMATTER = HtmlFormatter(nowrap=True, classprefix="hl-")
# Fence language -> lexer name; ``None`` means plain text (``""`` in the TOML).
ALIASES: dict[str, str | None] = {k: v or None for k, v in package_toml(__file__)["highlight"]["ALIASES"].items()}


@lru_cache(maxsize=256)
def lexer_for(lang: str | None, filename: str | None) -> Lexer | None:
    name = (lang or "").strip().lower()
    if name in ALIASES:
        name = ALIASES[name] or ""
    if name:
        try:
            return get_lexer_by_name(name, stripnl=False, ensurenl=False)
        except ClassNotFound:
            pass
    if filename:
        try:
            return get_lexer_for_filename(filename, stripnl=False, ensurenl=False)
        except ClassNotFound:
            pass
    return None


def lines(code: str, lang: str | None = None, filename: str | None = None) -> list[str] | None:
    """Highlighted HTML per line, or ``None`` when no lexer applies or the input is too large."""
    lexer = lexer_for(lang, filename)
    if lexer is None or len(code) > MAX_CHARS:
        return None
    out = highlight(code, lexer, FORMATTER)
    if out.endswith("\n") and not code.endswith("\n"):
        out = out[:-1]
    parts = out.split("\n")
    expected = code.count("\n") + 1
    if len(parts) != expected:  # a lexer that swallowed or added newlines: fall back to escaped text
        return None
    return parts


def render(code: str, lang: str | None = None, filename: str | None = None) -> dict[str, str | None]:
    parts = lines(code, lang, filename)
    lexer = lexer_for(lang, filename)
    if parts is None:
        return {"html": "", "lang": lexer.aliases[0] if lexer is not None and lexer.aliases else None}
    return {"html": "\n".join(parts), "lang": lexer.aliases[0] if lexer is not None and lexer.aliases else None}


def escaped_lines(code: str) -> list[str]:
    return [escape(line) for line in code.split("\n")]


@lru_cache(maxsize=1)
def style_css() -> str:
    def rules(style: str, selector: str) -> str:
        lines = HtmlFormatter(style=style, classprefix="hl-").get_style_defs(selector).splitlines()
        return "\n".join(line for line in lines if line.startswith(selector + " .hl-"))

    return rules("xcode", ".hl") + "\n" + rules("github-dark", '[data-theme="dark"] .hl') + "\n"
