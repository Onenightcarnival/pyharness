from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from pyxis_harness import package_toml

_CFG = package_toml(__file__)["store"]
PROVIDERS: tuple[str, ...] = tuple(_CFG["PROVIDERS"])
PROVIDER_TOOLS: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in _CFG["PROVIDER_TOOLS"].items()}


class JsonFile:
    def __init__(self, path: Path, default: Any) -> None:
        self.path = path
        self.default = default
        self.lock = threading.RLock()

    def read(self) -> Any:
        with self.lock:
            try:
                return json.loads(self.path.read_text("utf-8"))
            except FileNotFoundError:
                return json.loads(json.dumps(self.default))
            except ValueError:
                return json.loads(json.dumps(self.default))

    def write(self, data: Any) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
            tmp.chmod(0o600)
            tmp.replace(self.path)

    def update(self, fn: Any) -> Any:
        with self.lock:
            data = self.read()
            result = fn(data)
            self.write(data)
            return result


class AuthStore:
    """``{"<provider>": {"default": key, "accounts": {key: session}}}``; sections outside ``PROVIDERS`` are dropped."""

    def __init__(self, base: Path) -> None:
        self.file = JsonFile(base / "auth.json", {})
        if set(self.file.read()) - set(PROVIDERS):
            self.file.update(lambda data: [data.pop(key) for key in set(data) - set(PROVIDERS)])

    def _section(self, data: dict[str, Any], provider: str) -> dict[str, Any]:
        section = data.setdefault(provider, {})
        section.setdefault("accounts", {})
        section.setdefault("default", None)
        return section

    def accounts(self, provider: str) -> dict[str, dict[str, Any]]:
        return dict(self._section(self.file.read(), provider)["accounts"])

    def default_key(self, provider: str) -> str | None:
        section = self._section(self.file.read(), provider)
        key = section.get("default")
        if key in section["accounts"]:
            return key
        return next(iter(section["accounts"]), None)

    def ordered_keys(self, provider: str) -> list[str]:
        default = self.default_key(provider)
        keys = list(self.accounts(provider))
        return ([default] if default else []) + [k for k in keys if k != default]

    def get(self, provider: str, key: str | None = None) -> dict[str, Any] | None:
        accounts = self.accounts(provider)
        key = key or self.default_key(provider)
        return dict(accounts[key]) if key and key in accounts else None

    def save(self, provider: str, key: str, session: dict[str, Any]) -> None:
        def go(data: dict[str, Any]) -> None:
            section = self._section(data, provider)
            section["accounts"][key] = session
            if not section.get("default") or section["default"] not in section["accounts"]:
                section["default"] = key

        self.file.update(go)

    def delete(self, provider: str, key: str) -> bool:
        def go(data: dict[str, Any]) -> bool:
            section = self._section(data, provider)
            existed = section["accounts"].pop(key, None) is not None
            if section.get("default") == key:
                section["default"] = next(iter(section["accounts"]), None)
            return existed

        return self.file.update(go)

    def set_default(self, provider: str, key: str) -> bool:
        def go(data: dict[str, Any]) -> bool:
            section = self._section(data, provider)
            if key not in section["accounts"]:
                return False
            section["default"] = key
            return True

        return self.file.update(go)


class ProviderSettings:
    """Model visibility, context windows, tool switches (with history) and account preferences per provider."""

    def __init__(self, base: Path) -> None:
        self.file = JsonFile(base / "provider-settings.json", {"providers": {}, "toolHistory": []})

    def get(self, provider: str) -> dict[str, Any]:
        data = self.file.read()
        prefs = dict((data.get("providers") or {}).get(provider) or {})
        prefs.setdefault("accounts", {})
        prefs.setdefault("contextWindows", {})
        prefs.setdefault("tools", {})
        return prefs

    def set(self, provider: str, prefs: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        if isinstance(prefs.get("visibleModels"), list):
            clean["visibleModels"] = [str(m) for m in prefs["visibleModels"]]
        clean["contextWindows"] = {
            str(k): int(v)
            for k, v in (prefs.get("contextWindows") or {}).items()
            if isinstance(v, int) and not isinstance(v, bool) and v > 0
        }
        tools = prefs.get("tools") or {}
        for name in tools:
            if name not in PROVIDER_TOOLS.get(provider, ()):
                raise ValueError(f"unknown tool {name!r} for {provider}")
        clean["tools"] = {k: bool(v) for k, v in tools.items()}
        clean["accounts"] = {
            str(k): {
                kk: vv
                for kk, vv in (v or {}).items()
                if kk in ("alias", "poolEnabled", "independentEntry", "poolModels")
            }
            for k, v in (prefs.get("accounts") or {}).items()
        }

        def go(data: dict[str, Any]) -> dict[str, Any]:
            providers = data.setdefault("providers", {})
            previous = (providers.get(provider) or {}).get("tools") or {}
            providers[provider] = clean
            if previous != clean["tools"]:
                data.setdefault("toolHistory", []).append(
                    {"at": int(time.time() * 1000), "provider": provider, "tools": dict(clean["tools"])}
                )
            return clean

        return self.file.update(go)

    def tool_enabled(self, provider: str, tool: str, at_ms: int | None = None) -> bool:
        """Replay the switch history up to ``at_ms`` (``None``: now); absent or not ``False`` means enabled."""
        data = self.file.read()
        if at_ms is None:
            return (self.get(provider).get("tools") or {}).get(tool) is not False
        state: Any = None
        for entry in data.get("toolHistory") or []:
            if entry.get("provider") == provider and int(entry.get("at") or 0) <= at_ms:
                state = (entry.get("tools") or {}).get(tool)
        return state is not False


class ModelDefaults:
    def __init__(self, base: Path) -> None:
        self.file = JsonFile(base / "model-defaults.json", {})

    def get(self, provider: str, model: str) -> str | None:
        return ((self.file.read().get(provider) or {}).get(model)) or None

    def set(self, provider: str, model: str, effort: str | None) -> None:
        def go(data: dict[str, Any]) -> None:
            section = data.setdefault(provider, {})
            if effort:
                section[model] = effort
            else:
                section.pop(model, None)

        self.file.update(go)


class CatalogCache:
    """Last-known catalogs: ``{"<provider>": {"at": ms, "models": [...]}}`` (default account) and ``accounts``."""

    TTL_MS = 5 * 60 * 1000

    def __init__(self, base: Path) -> None:
        self.file = JsonFile(base / "models.json", {})

    def get(self, provider: str, account: str | None = None) -> dict[str, Any] | None:
        data = self.file.read()
        if account:
            return ((data.get("accounts") or {}).get(provider) or {}).get(account)
        return data.get(provider)

    def set(self, provider: str, models: list[dict[str, Any]], account: str | None = None) -> None:
        def go(data: dict[str, Any]) -> None:
            entry = {"at": int(time.time() * 1000), "models": models}
            if account:
                data.setdefault("accounts", {}).setdefault(provider, {})[account] = entry
            else:
                data[provider] = entry

        self.file.update(go)

    def fresh(self, provider: str, account: str | None = None) -> bool:
        entry = self.get(provider, account)
        return bool(entry) and int(time.time() * 1000) - int(entry.get("at") or 0) < self.TTL_MS

    def clear(self, provider: str | None = None) -> None:
        def go(data: dict[str, Any]) -> None:
            if provider is None:
                data.clear()
            else:
                data.pop(provider, None)
                (data.get("accounts") or {}).pop(provider, None)

        self.file.update(go)


class MediaStore:
    def __init__(self, base: Path) -> None:
        self.images = base / "images"
        self.videos = base / "videos"

    @staticmethod
    def stamp() -> str:
        return time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime()) + "Z"

    def image_path(self, index: int, ext: str) -> Path:
        self.images.mkdir(parents=True, exist_ok=True)
        return self.images / f"image-{self.stamp()}-{os.urandom(4).hex()[:6]}-{index}.{ext}"

    def video_path(self) -> Path:
        self.videos.mkdir(parents=True, exist_ok=True)
        return self.videos / f"video-{self.stamp()}-{os.urandom(4).hex()[:6]}.mp4"


def image_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"GIF8"):
        return "gif"
    return "png"
