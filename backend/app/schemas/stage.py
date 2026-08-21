from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StageStartRequest(BaseModel):
    mode: Literal["auto", "chat"] = "auto"
    provider_id: int | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage_run_id: int
    type: str
    title: str
    content_md: str
    current_version: int
    status: str
    created_at: datetime
    updated_at: datetime


class StageRunOut(BaseModel):
    id: int
    project_id: int
    stage_id: int
    stage_code: str
    stage_name: str
    provider_id: int | None
    status: str
    mode: str
    error: str | None = None
    artifacts: list[ArtifactOut] = []
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage_run_id: int
    role: str
    agent_code: str | None = None
    content: str
    created_at: datetime


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ReviewRequest(BaseModel):
    comment: str = Field(default="", max_length=2000)
