from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class NewSession(BaseModel):
    title: str | None = None
    model: str | None = Field(None, description="route:model for this session; null: the default.")
    workspace: str | None = Field(None, description="Absolute workspace directory; null: the default workspace.")
    mode: str | None = Field(None, description="Permission mode; null: the default.")
    preset: str | None = Field(None, description="Agent preset; null: the default.")


class SessionMode(BaseModel):
    mode: str


class SessionPreset(BaseModel):
    preset: str


class WorkspacePath(BaseModel):
    path: str | None = None
    name: str | None = None


class SessionTitle(BaseModel):
    title: str | None = None


class AgentDefaults(BaseModel):
    default_preset: str | None = None
    default_mode: str | None = None
    approval_timeout: float | None = Field(
        None, gt=0, description="Seconds a tool approval waits before it is rejected; null: no limit. Sent to change."
    )


IMAGE_DATA_URL = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)$")
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class InstallBody(BaseModel):
    path: str | None = Field(
        None, description="Directory of a bundle (pyproject.toml with a pyxis_harness.bundles entry point)."
    )
    package: str | None = Field(
        None, description="Package requirement to install from the index, e.g. pyh-todo or pyh-todo==0.1.0."
    )
    index_url: str | None = Field(None, description="Package index for `package`; PyPI when absent.")

    @model_validator(mode="after")
    def one_source(self) -> InstallBody:
        if bool(self.path) == bool(self.package):
            raise ValueError("give exactly one of path or package")
        return self


class EnabledBody(BaseModel):
    enabled: bool


class MCPServerBody(BaseModel):
    transport: Literal["stdio", "streamable_http", "sse"] | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    approval: bool | dict[str, Any] = False
    prefix: bool = True

    @model_validator(mode="after")
    def one_transport(self) -> MCPServerBody:
        if bool(self.command) == bool(self.url):
            raise ValueError("a server needs exactly one of command (stdio) or url (streamable_http / sse)")
        return self


class MCPSettings(BaseModel):
    servers: dict[str, MCPServerBody] = Field(default_factory=dict)

    @field_validator("servers")
    @classmethod
    def names(cls, value: dict[str, MCPServerBody]) -> dict[str, MCPServerBody]:
        for name in value:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
                raise ValueError(f"server name {name!r}: letters, digits, - and _ only")
        return value


class HighlightItem(BaseModel):
    code: str = Field(max_length=400_000)
    lang: str | None = None
    filename: str | None = None


class HighlightRequest(BaseModel):
    items: list[HighlightItem] = Field(max_length=200)


class NewMessage(BaseModel):
    content: str = Field("", description="Text; may be empty when images are attached.")
    images: list[str] = Field(
        default_factory=list, description="Image data URLs (png, jpeg, gif, webp); at most 8, 8 MB each."
    )

    @field_validator("images")
    @classmethod
    def _images(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_IMAGES:
            raise ValueError(f"at most {MAX_IMAGES} images per message")
        for url in value:
            match = IMAGE_DATA_URL.match(url)
            if not match:
                raise ValueError("images must be data URLs of type image/png, image/jpeg, image/gif or image/webp")
            if len(match.group(2)) * 3 // 4 > MAX_IMAGE_BYTES:
                raise ValueError(f"an image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> NewMessage:
        if not self.content.strip() and not self.images:
            raise ValueError("a message needs text or images")
        return self


class Approvals(BaseModel):
    decisions: list[dict[str, Any]]


class QuestionAnswers(BaseModel):
    """Answers to a pending ``ask_user_question`` interrupt: one per question (``id``, ``selected``, ``custom``?)."""

    answers: list[dict[str, Any]]
    interrupt_id: str | None = Field(None, description="Which pending interrupt; the only ask_user one when omitted.")


class CompactionSettings(BaseModel):
    """Fields of the compaction plugin's configuration; ``None`` keeps the saved value."""

    auto: bool | None = None
    threshold_ratio: float | None = Field(None, gt=0, le=1)
    retain_ratio: float | None = Field(None, ge=0, lt=1)
    default_context_window: int | None = Field(None, gt=0)
    summary_model: str | None = None


class RouteSettings(BaseModel):
    """Fields of one model route. ``None`` keeps the saved value; ``api_key`` '' clears the stored credential."""

    type: str | None = None
    title: str | None = None
    protocol: str | None = Field(
        None, description="Custom endpoints: openai-chat, openai-responses, anthropic-messages, gemini."
    )
    base_url: str | None = None
    api_key: str | None = None
    models: list[dict[str, Any]] | None = None
    options: dict[str, Any] | None = None
    retry: dict[str, Any] | None = Field(
        None, description='Retry policy of the route (RetryPolicy fields); {"mode": "inherit"} removes it.'
    )
    model: str | None = Field(None, description="Model id for /test.")


class ModelRetry(BaseModel):
    retry: dict[str, Any] | None = Field(
        None, description="Retry policy for routes without their own (RetryPolicy fields); null: no retries."
    )


class DefaultModel(BaseModel):
    default: str | None = Field(None, description="route:model for new sessions; null clears it.")


class SessionModel(BaseModel):
    model: str | None = Field(None, description="route:model; null returns to the default.")
