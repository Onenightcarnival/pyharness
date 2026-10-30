"""``scripted`` model provider: replies from a list in the entry config."""

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


class ScriptedModel(BaseChatModel):
    replies: list[dict[str, Any]]
    cursor: list[int] = Field(default_factory=lambda: [0])

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        CALLS.append({"messages": [(m.type, m.text) for m in messages]})
        index = self.cursor[0]
        self.cursor[0] += 1
        if index < len(self.replies):
            reply = self.replies[index]
            extra = {"reasoning_content": reply["reasoning"]} if reply.get("reasoning") else {}
            message = AIMessage(content=reply.get("content", ""), tool_calls=reply.get("tool_calls", []), additional_kwargs=extra)
        else:
            message = AIMessage(content="(script exhausted)")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self


def apply(ctx: Any, config: Config) -> None:
    replies = config.by_generation.get(ctx.lifecycle.generation, config.replies)
    ctx.llm.register("scripted", lambda model, **_: ScriptedModel(replies=replies))
