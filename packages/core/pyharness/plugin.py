from __future__ import annotations

import difflib
import importlib
import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel

from .config import ConfigError, PatchOp, load_yaml, parse_ops
from .context import Service

PLUGIN_GROUP = "pyharness.plugins"
BUNDLE_GROUP = "pyharness.bundles"
DOCS_NAME = "AGENTS.md"  # design documentation of a package


class PluginError(RuntimeError):
    """Plugin import or definition failure."""


class PluginNotFound(PluginError, LookupError):
    """No plugin or bundle under the name."""


@dataclass
class PluginDef:
    """Plugin defined as a value instead of module attributes."""

    name: str
    apply: Callable[..., Any]
    inject: list[str] = field(default_factory=list)
    Config: type[BaseModel] | None = None
    doc: str = ""


def define_plugin(
    name: str,
    apply: Callable[..., Any],
    *,
    inject: Iterable[str] = (),
    config: type[BaseModel] | None = None,
    doc: str = "",
) -> PluginDef:
    return PluginDef(name=name, apply=apply, inject=list(inject), Config=config, doc=doc or (apply.__doc__ or ""))


@dataclass
class PluginSpec:
    name: str
    kind: str  # "function" | "service"
    inject: list[str]
    config_model: type[BaseModel] | None
    apply: Callable[..., Any] | None = None
    service_cls: type[Service] | None = None
    doc: str = ""
    module: str | None = None
    dist: str | None = None
    package_dir: str | None = None
    docs: str | None = None  # the package's AGENTS.md

    def validate_config(self, raw: dict[str, Any] | None) -> Any:
        if self.config_model is None:
            return dict(raw or {})
        return self.config_model.model_validate(raw or {})

    def config_schema(self) -> dict[str, Any] | None:
        return self.config_model.model_json_schema() if self.config_model is not None else None


def to_spec(obj: Any, fallback_name: str) -> PluginSpec:
    module = getattr(obj, "__module__", None) if not isinstance(obj, ModuleType) else obj.__name__
    if inspect.isclass(obj) and issubclass(obj, Service):
        if not getattr(obj, "key", None):
            raise PluginError(f"service plugin {obj.__qualname__} has no `key`")
        return PluginSpec(
            name=obj.name or fallback_name,
            kind="service",
            inject=list(obj.inject),
            config_model=obj.Config,
            service_cls=obj,
            doc=inspect.getdoc(obj) or "",
            module=module,
        )
    apply = getattr(obj, "apply", None)
    if apply is None and inspect.isfunction(obj):
        apply, obj = obj, None
    if apply is None or not callable(apply):
        raise PluginError(f"{fallback_name!r} is not a plugin: expected `apply(ctx[, config])` or a Service subclass")
    source = obj if obj is not None else apply
    config_model = getattr(source, "Config", None)
    if config_model is not None and not (inspect.isclass(config_model) and issubclass(config_model, BaseModel)):
        raise PluginError(f"{fallback_name!r}: `Config` must be a pydantic BaseModel subclass")
    doc = getattr(source, "doc", "") or inspect.getdoc(source) or ""
    return PluginSpec(
        name=getattr(source, "name", None) or fallback_name,
        kind="function",
        inject=list(getattr(source, "inject", []) or []),
        config_model=config_model,
        apply=apply,
        doc=doc,
        module=module,
    )


def call_apply(spec: PluginSpec, ctx: Any, config: Any) -> Any:
    assert spec.apply is not None
    try:
        params = [
            p
            for p in inspect.signature(spec.apply).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):  # pragma: no cover
        params = []
    if len(params) >= 2:
        return spec.apply(ctx, config)
    return spec.apply(ctx)


# ---------------------------------------------------------------------- discovery
def _entry_points(group: str) -> dict[str, metadata.EntryPoint]:
    found: dict[str, metadata.EntryPoint] = {}
    for ep in metadata.entry_points(group=group):
        found.setdefault(ep.name, ep)
    return found


def plugin_entry_points() -> dict[str, metadata.EntryPoint]:
    return _entry_points(PLUGIN_GROUP)


def bundle_entry_points() -> dict[str, metadata.EntryPoint]:
    return _entry_points(BUNDLE_GROUP)


def _module_dir(module_name: str | None) -> str | None:
    if not module_name:
        return None
    try:
        mod = importlib.import_module(module_name.split(":")[0])
    except Exception:  # pragma: no cover
        return None
    file = getattr(mod, "__file__", None)
    return str(Path(file).parent) if file else None


def _package_docs(package_dir: str | None) -> str | None:
    """
    ``AGENTS.md`` of a package: inside the module directory (an installed wheel), else beside the ``pyproject.toml``
    one level up (a source checkout).
    """
    if not package_dir:
        return None
    module_dir = Path(package_dir)
    inside, beside = module_dir / DOCS_NAME, module_dir.parent / DOCS_NAME
    if inside.is_file():
        return str(inside)
    if beside.is_file() and (module_dir.parent / "pyproject.toml").is_file():
        return str(beside)
    return None


def load_plugin(name: str) -> PluginSpec:
    eps = plugin_entry_points()
    if name in eps:
        ep = eps[name]
        try:
            obj = ep.load()
        except Exception as exc:
            raise PluginError(f"importing plugin {name!r} ({ep.value}) failed: {exc!r}") from exc
        spec = to_spec(obj, name)
        spec.dist = ep.dist.name if ep.dist else None
        spec.module = ep.module
        spec.package_dir = _module_dir(ep.module)
        spec.docs = _package_docs(spec.package_dir)
        return spec
    module_name, _, attr = name.partition(":")
    if module_name.replace(".", "").replace("_", "").isalnum() and not module_name[:1].isdigit():
        try:
            obj: Any = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name.split(".")[0] and exc.name != module_name:
                raise PluginError(f"importing plugin module {module_name!r} failed: {exc!r}") from exc
            obj = None
        except Exception as exc:
            raise PluginError(f"importing plugin module {module_name!r} failed: {exc!r}") from exc
    else:
        obj = None
    if obj is not None:
        for part in filter(None, attr.split(".")):
            try:
                obj = getattr(obj, part)
            except AttributeError:
                raise PluginNotFound(f"module {module_name!r} has no attribute {attr!r}") from None
        spec = to_spec(obj, name)
        spec.package_dir = _module_dir(module_name)
        spec.docs = _package_docs(spec.package_dir)
        return spec
    close = difflib.get_close_matches(name, list(eps), n=3)
    hint = f"; close matches: {', '.join(close)}" if close else ""
    raise PluginNotFound(f"no plugin named {name!r} in entry-point group {PLUGIN_GROUP!r}{hint}")


@dataclass
class BundleInfo:
    name: str
    title: str
    description: str
    ops: list[PatchOp]
    dist: str | None
    version: str | None
    location: str | None
    optional: bool = False  # on unless the profile lists it under ``disabled``; the Web UI may toggle it
    builtin: bool = False  # part of every profile (after its ``bundles``); cannot be disabled or uninstalled


def load_bundle(name: str) -> BundleInfo:
    eps = bundle_entry_points()
    if name not in eps:
        close = difflib.get_close_matches(name, list(eps), n=3)
        hint = f"; close matches: {', '.join(close)}" if close else ""
        raise PluginNotFound(f"no bundle named {name!r} in entry-point group {BUNDLE_GROUP!r}{hint}")
    ep = eps[name]
    try:
        obj = ep.load()
    except Exception as exc:
        raise PluginError(f"importing bundle {name!r} ({ep.value}) failed: {exc!r}") from exc
    return bundle_from_object(name, obj, ep)


def bundle_from_object(name: str, obj: Any, ep: metadata.EntryPoint | None = None) -> BundleInfo:
    data: Any = obj
    if isinstance(obj, (str, Path)):
        path = Path(obj)
        data = load_yaml(path, default=None)
        if data is None:
            raise ConfigError(f"bundle {name!r}: {path} is missing or empty")
    if callable(data) and not isinstance(data, (list, dict)):
        data = data()
    if isinstance(data, list):
        data = {"patch": data}
    if not isinstance(data, dict):
        raise ConfigError(f"bundle {name!r} must be a patch list, a mapping or a YAML path")
    dist = ep.dist if ep is not None else None
    return BundleInfo(
        name=name,
        title=str(data.get("title") or name),
        description=str(data.get("description") or ""),
        ops=parse_ops(data.get("patch") or [], f"bundle:{name}"),
        dist=dist.name if dist else None,
        version=dist.version if dist else None,
        location=str(dist.locate_file("")) if dist else None,
        optional=bool(data.get("optional", False)),
        builtin=bool(data.get("builtin", False)),
    )
