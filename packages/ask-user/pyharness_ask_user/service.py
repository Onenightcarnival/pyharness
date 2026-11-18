from __future__ import annotations

import json
from typing import Any, ClassVar

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from pyharness import Service, package_prompts

KIND = "ask_user"
PROMPTS = package_prompts(__file__)

DESCRIPTION: str = PROMPTS["tools"]["ask_user_question"]


class Option(BaseModel):
    label: str = Field(description="Short user-facing option label.")
    description: str | None = Field(None, description="One sentence explaining the tradeoff or impact.")


class Question(BaseModel):
    id: str = Field(description="Stable id for this question; echoed in the answer.")
    question: str = Field(description="The specific question to ask the user.")
    header: str | None = Field(None, description='Optional short heading, such as "Confirm" or "Choose mode".')
    options: list[Option] | None = Field(None, description="Optional choices to show the user.")
    multi_select: bool = Field(False, description="Whether the user may select more than one option.")


class Answer(BaseModel):
    id: str
    selected: list[str] = Field(default_factory=list)
    custom: str | None = None


class Config(BaseModel):
    approval: bool | dict[str, Any] = False


def normalize_answers(questions: list[dict[str, Any]], raw: Any) -> list[dict[str, Any]]:
    """Answers as the tool reports them: one per question in question order; unknown ids rejected."""
    if isinstance(raw, dict):
        raw = raw.get("answers", raw)
    if not isinstance(raw, list):
        raise ValueError("answers must be a list of {id, selected, custom?}")
    by_id = {}
    for item in raw:
        answer = Answer.model_validate(item)
        by_id[answer.id] = answer
    ids = [q["id"] for q in questions]
    unknown = [i for i in by_id if i not in ids]
    if unknown:
        raise ValueError(f"answers for unknown question ids: {', '.join(unknown)}; expected {', '.join(ids)}")
    out = []
    for qid in ids:
        answer = by_id.get(qid) or Answer(id=qid)
        custom = (answer.custom or "").strip()
        out.append({"id": qid, "selected": list(answer.selected), **({"custom": custom} if custom else {})})
    return out


class AskUserService(Service):
    key = "askUser"
    name = "pyxis-harness-ask-user"
    inject: ClassVar[list[str]] = ["tools"]
    Config = Config

    async def start(self) -> None:
        @tool("ask_user_question", description=DESCRIPTION)
        def ask_user_question(questions: list[Question]) -> str:
            """Ask the user one or more questions and wait for the answers."""
            if not questions:
                raise ValueError("questions must contain at least one question")
            ids = [q.id for q in questions]
            if len(set(ids)) != len(ids):
                raise ValueError("question ids must be unique within one call")
            payload = [q.model_dump(exclude_none=True) for q in questions]
            raw = interrupt({"kind": KIND, "questions": payload})
            return json.dumps({"answers": normalize_answers(payload, raw)}, ensure_ascii=False)

        self.ctx.tools.register(ask_user_question, approval=self.config.approval, tags=("ask-user",))
