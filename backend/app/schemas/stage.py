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


class ChecklistVerdictIn(BaseModel):
    """单项清单结论：item id → 判定与说明。"""

    verdict: str = Field(default="passed")
    note: str = Field(default="", max_length=500)


class ReviewRequest(BaseModel):
    comment: str = Field(default="", max_length=2000)
    # 结构化评审清单结论：{检查项 id: {verdict, note}}
    checklist: dict[str, ChecklistVerdictIn] = Field(default_factory=dict)


class ChecklistItemOut(BaseModel):
    id: str
    text: str
    hint: str = ""
    verdict: str | None = None
    note: str = ""


class StageChecklistOut(BaseModel):
    """阶段的评审清单：检查项 + Agent 建议 + 上次人工结论。"""

    stage_code: str
    items: list[ChecklistItemOut] = []
    agent: dict[str, ChecklistVerdictIn] = Field(default_factory=dict)


class ActivityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage_run_id: int | None = None
    event_type: str
    message: str
    created_at: datetime


class ArtifactUpdate(BaseModel):
    content_md: str = Field(min_length=1, max_length=20000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage_run_id: int
    artifact_id: int | None = None
    reviewer_type: str
    result: str
    comment: str
    checklist_json: str | None = None
    created_at: datetime
