from pydantic import BaseModel, Field


class McpServerSummary(BaseModel):
    name: str
    type: str
    enabled: bool = True
    command: list[str] = []
    url: str | None = None
    env_keys: list[str] = Field(default_factory=list)
    tools: list[dict] = Field(default_factory=list)
    error: str | None = None


class McpToolOut(BaseModel):
    name: str
    description: str = ""
    inputSchema: dict = Field(default_factory=dict)
