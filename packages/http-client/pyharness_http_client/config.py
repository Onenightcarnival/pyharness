from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    data_dir: str | None = Field(
        None,
        description="Directory of targets.json, requests.json and history.jsonl; default "
        "<profile data>/toolkit/http-client.",
    )
