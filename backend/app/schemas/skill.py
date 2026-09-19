from pydantic import BaseModel, Field


class SkillSummaryOut(BaseModel):
    name: str
    description: str
    path: str
    source: str
    metadata: dict = Field(default_factory=dict)


class SkillOut(SkillSummaryOut):
    content: str
