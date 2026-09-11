from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    code: str
    name: str
    description: str = ""


class ProcessModelSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str = ""
    version: str = "1.0"


class ProcessModelOut(ProcessModelSummary):
    stages: list[StageOut] = []


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    process_model_code: str = Field(default="waterfall")
    folder: str | None = Field(default=None, max_length=500)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    auto_advance: bool | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    folder: str | None = None
    status: str
    auto_advance: bool = False
    process_model: ProcessModelSummary
    owner_id: int
    created_at: datetime
    updated_at: datetime


class ProjectFlowStage(BaseModel):
    stage: StageOut
    status: str
    stage_run_id: int | None = None


class ProjectFlowOut(BaseModel):
    process_model: ProcessModelSummary
    stages: list[ProjectFlowStage]
    auto_advance: bool = False
