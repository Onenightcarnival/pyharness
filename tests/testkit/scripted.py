"""``scripted`` model provider: replies from a list in the entry config; a reply ``{"error": {...}}`` raises."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

name = "testkit-scripted"
inject = ["llm"]

# Model calls of every ScriptedModel (in-process tests).
CALLS: list[dict[str, Any]] = []


class Config(BaseModel):
    replies: list[dict[str, Any]] = Field(default_factory=list)
    by_generation: dict[int, list[dict[str, Any]]] = Field(default_factory=dict)


class ScriptedError(RuntimeError):
    """The failure of a reply ``{"error": {...}}``: ``code`` (a failure code) or ``status_code`` (an HTTP status)."""

    def __init__(
        self,
        message: str = "scripted failure",
        *,
        code: str | None = None,
        status_code: int | None = None,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.retry_after_ms = retry_after_ms


class ScriptedModel(BaseChatModel):
    replies: list[dict[str, Any]]
    model_name: str = "test"
    cursor: list[int] = Field(default_factory=lambda: [0])

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        CALLS.append(
            {
                "via": self.model_name,
                "messages": [(m.type, m.text) for m in messages],
                "images": sum(
                    1
                    for m in messages
                    if isinstance(m.content, list)
                    for b in m.content
                    if isinstance(b, dict) and b.get("type") == "image_url"
                ),
            }
        )
        index = self.cursor[0]
        self.cursor[0] += 1
        if index < len(self.replies):
            reply = self.replies[index]
            if reply.get("error"):
                raise ScriptedError(**reply["error"])
            extra = {"reasoning_content": reply["reasoning"]} if reply.get("reasoning") else {}
            content: Any = reply.get("content", "")
            if reply.get("images"):
                content = [{"type": "text", "text": content}] + [
                    {"type": "image_url", "image_url": {"url": u}} for u in reply["images"]
                ]
            message = AIMessage(content=content, tool_calls=reply.get("tool_calls", []), additional_kwargs=extra)
        else:
            message = AIMessage(content="(script exhausted)")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self


def apply(ctx: Any, config: Config) -> None:
    replies = config.by_generation.get(ctx.lifecycle.generation, config.replies)

    def factory(model: str, **_: Any) -> ScriptedModel:
        CALLS.append({"model": model})
        return ScriptedModel(replies=replies, model_name=model)

    ctx.llm.register("scripted", factory)
