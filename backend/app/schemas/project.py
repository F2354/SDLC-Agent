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


class ToolUsageOut(BaseModel):
    tool: str
    count: int


class StageContractOut(BaseModel):
    """阶段契约摘要：输入/输出约束与配对验证关系。"""

    inputs: list[str] | None = None
    outputs: dict[str, int] = {}
    pair_stage: str | None = None
    pair_stage_name: str | None = None
    note: str = ""


class ProjectFlowStage(BaseModel):
    stage: StageOut
    status: str
    stage_run_id: int | None = None
    dependencies: list[str] = []
    # 过程模型视图所需：这一阶段由谁执行、用什么模型、调了哪些工具、与谁并行。
    agent_role: str | None = None
    agent_role_name: str | None = None
    model: str | None = None
    tool_usage: list[ToolUsageOut] = []
    tool_call_count: int = 0
    parallel_peers: list[str] = []
    contract: StageContractOut | None = None


class ProjectFlowOut(BaseModel):
    process_model: ProcessModelSummary
    stages: list[ProjectFlowStage]
    auto_advance: bool = False
