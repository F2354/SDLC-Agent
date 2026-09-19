from pydantic import BaseModel, Field


class AgentProfileOut(BaseModel):
    name: str
    mode: str = "subagent"
    model: str | None = None
    description: str = ""
    permissions: dict[str, str] = Field(default_factory=dict)
