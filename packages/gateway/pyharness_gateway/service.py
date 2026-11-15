from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from pyharness import Service

from .backend import LangChainBackend
from .config import Config
from .images import ImageResolver
from .keys import KeyStore
from .listener import Listener
from .models import ModelCatalog
from .routes import build_router
from .server import GatewayDeps, create_app
from .settings import SettingsStore
from .usage import UsageStore

INITIAL_KEY_NAME = "default"


class GatewayService(Service):
    """Local LLM API gateway over the routes of ``ctx.llm``."""

    key = "gateway"
    name = "pyharness-gateway"
    inject: ClassVar[list[str]] = ["llm", "http", "webui"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        base = self._data()
        defaults = {"enabled": config.listen, "host": config.host, "port": config.port}
        self.settings = SettingsStore(base / "settings.json", defaults)
        self.keys = KeyStore(base / "keys.json")
        self.usage = UsageStore(base / "usage.sqlite")
        self.images = ImageResolver()
        self.catalog = ModelCatalog(lambda: ctx.llm.directory()["groups"], ctx.llm.routes, self.settings.get)
        self.app = create_app(
            GatewayDeps(
                generate=LangChainBackend(ctx.llm).stream,
                catalog=self.catalog,
                keys=self.keys,
                usage=self.usage,
                load_image=self.images,
                max_body_bytes=config.max_body_bytes,
                logger=ctx.logger,
            )
        )
        self.listener = Listener(self.app, ctx.logger)

    def _data(self) -> Path:
        if self.config.data_dir:
            return Path(self.config.data_dir).expanduser()
        profile = self.ctx.get("profile", None)
        base = (
            Path(profile.data)
            if profile is not None and hasattr(profile, "data")
            else Path.home() / ".pyharness" / "data"
        )
        return base / "toolkit" / "gateway"

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.keys.ensure_one(INITIAL_KEY_NAME) is not None:
            self.ctx.logger.info('gateway: API key "%s" generated; copy it from the API gateway page', INITIAL_KEY_NAME)
        self.ctx.http.include_router(build_router(self), prefix="/api/gateway", tags=["pyharness-gateway"])
        self.ctx.webui.register_client(Path(__file__).with_name("client.js"))
        self.ctx.on("app/serve", self._listen)
        self.ctx.on("app/stopping", self.listener.close)

    async def stop(self) -> None:
        await self.listener.close()
        self.usage.close()

    async def _listen(self) -> None:
        current = self.settings.get()
        await self.listener.apply(current["enabled"], current["host"], current["port"])

    # ------------------------------------------------------------------ management
    def status(self) -> dict[str, Any]:
        """Settings, listener state, the model list and the key list."""
        return {
            "settings": self.settings.get(),
            "listening": self.listener.listening,
            "listenError": self.listener.error,
            "models": self.catalog.list(),
            "keys": self.keys.list(),
        }

    async def save_settings(self, raw: Any) -> dict[str, Any]:
        """Persist the complete settings object and restart the listener; returns the status."""
        self.settings.save(raw)
        await self._listen()
        return self.status()
