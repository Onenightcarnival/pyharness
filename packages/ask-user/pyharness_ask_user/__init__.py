"""``ask_user_question``: the agent asks the user and waits for the answer.

The tool raises a LangGraph interrupt whose value is ``{"kind": "ask_user", "questions": [...]}``; the run ends
``interrupted`` and the Web UI shows a question card. The answer resumes the run through
``POST /sessions/{id}/answers`` (``agents.start_run(resume={interrupt_id: {"answers": [...]}})``); the tool then
returns ``{"answers": [{"id", "selected", "custom"?}]}`` as JSON — a skipped question has an empty ``selected``
and no ``custom``. Question and answer shapes follow dsh's ``ask_user_question`` so prompts written for either work.
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from pyharness import Service

KIND = "ask_user"

DESCRIPTION = dedent(
    """
    Ask the user brief, direct, self-contained questions when you need confirmation, a choice, or missing
    information before proceeding. Use user-facing terms; assume no knowledge of background work or internal
    names. Give each question a distinct stable id. Offer options when a choice is expected; put a recommended
    option first with "(Recommended)" appended to its label. The run pauses until the user answers; a skipped
    question comes back with an empty selection and no custom text.
    """
).strip()


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
    name = "pyharness-ask-user"
    inject = ["tools"]
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


__all__ = ["KIND", "Answer", "AskUserService", "Config", "Option", "Question", "normalize_answers"]
