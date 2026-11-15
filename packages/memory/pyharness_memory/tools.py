from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Protocol

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.config import get_config
from pydantic import BaseModel, ConfigDict, Field, create_model

from pyharness import package_prompts

from .store import FIELD_DESCRIPTIONS, FIELDS, KIND_GUIDE


class Host(Protocol):
    """The service, as the tools use it."""

    def read(self, node_id: str | None, offset: int | None, limit: int | None) -> dict[str, Any]: ...
    def save(self, state_token: str, summary: str, changes: list[dict[str, Any]], source: str) -> dict[str, Any]: ...


PROMPTS = package_prompts(__file__)
GET_DESCRIPTION: str = PROMPTS["tools"]["GET_DESCRIPTION"]
SAVE_DESCRIPTION: str = PROMPTS["tools"]["SAVE_DESCRIPTION"]


# ---------------------------------------------------------------------- change schemas (one per kind, as dsh-memory)
def _fields_model(kind: str) -> type[BaseModel]:
    spec = {key: (str | None, Field(None, description=FIELD_DESCRIPTIONS[key])) for key in FIELDS[kind]}
    return create_model(f"{kind.capitalize()}Fields", __config__=ConfigDict(extra="forbid"), **spec)  # type: ignore[call-overload]


FIELDS_DOC = "Only changed fields. Omitted fields stay unchanged; an empty string clears a field."
ID_DOC = "Existing record id for update. Omit to create; the server assigns its id."
REF_DOC = "Optional batch-local reference name for a new entry, e.g. project1; use @project1 in parent fields."


class ProfileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["profile"] = Field(description=KIND_GUIDE["profile"])
    fields: _fields_model("profile") = Field(description=FIELDS_DOC)  # type: ignore[valid-type]


class WorkChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["work"] = Field(description=KIND_GUIDE["work"])
    id: str | None = Field(None, description=ID_DOC)
    ref: str | None = Field(None, description=REF_DOC)
    fields: _fields_model("work") = Field(description=FIELDS_DOC)  # type: ignore[valid-type]


class ProjectChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["project"] = Field(description=KIND_GUIDE["project"])
    id: str | None = Field(None, description=ID_DOC)
    ref: str | None = Field(None, description=REF_DOC)
    fields: _fields_model("project") = Field(description=FIELDS_DOC)  # type: ignore[valid-type]


class LessonChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["lesson"] = Field(description=KIND_GUIDE["lesson"])
    id: str | None = Field(None, description=ID_DOC)
    ref: str | None = Field(None, description=REF_DOC)
    fields: _fields_model("lesson") = Field(description=FIELDS_DOC)  # type: ignore[valid-type]


class RemoveChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["remove"]
    id: str = Field(description="Existing entry to remove; no cascading deletion. History remains.")


Change = Annotated[
    ProfileChange | WorkChange | ProjectChange | LessonChange | RemoveChange, Field(discriminator="kind")
]


# ---------------------------------------------------------------------- tools
def _thread_id() -> str | None:
    try:
        return dict(get_config().get("configurable") or {}).get("thread_id")
    except RuntimeError:  # no run in progress
        return None


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def get_tool(service: Host):
    @tool("memory_get", description=GET_DESCRIPTION)
    def memory_get(
        id: str | None = Field(None, description="Node id. Omit or pass profile for the root."),
        offset: int | None = Field(None, description="Zero-based offset, default 0."),
        limit: int | None = Field(None, description="Page size from 1 to 20, default 10."),
    ) -> str:
        return _dump(service.read(id, offset, limit))

    return memory_get


def save_tool(service: Host):
    @tool("memory_save", description=SAVE_DESCRIPTION)
    def memory_save(
        stateToken: str = Field(
            description="Opaque stateToken from the latest read; never use the displayed version as this token."
        ),
        summary: str = Field(description="Short factual description of this durable update."),
        changes: list[Change] = Field(description="1–100 typed changes applied atomically."),
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
    ) -> str:
        raw = [c.model_dump(exclude_none=True) for c in changes]
        return _dump(
            service.save(
                stateToken, summary, raw, f"session:{_thread_id() or 'unknown'}/call:{tool_call_id or 'unknown'}"
            )
        )

    return memory_save
