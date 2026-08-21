from pydantic import BaseModel


class EntityGroupOut(BaseModel):
    RQ: list[str] = []
    UC: list[str] = []
    MOD: list[str] = []
    TC: list[str] = []


class TraceabilityArtifactRow(BaseModel):
    artifact_id: int
    title: str
    stage_code: str
    entities: EntityGroupOut


class TraceabilityOut(BaseModel):
    rows: list[TraceabilityArtifactRow]
    entity_counts: dict[str, int]
    warnings: list[str]


class ProjectStatsOut(BaseModel):
    project_id: int
    stage_counts: dict[str, int]
    artifact_count: int
    total_chars: int
    entity_counts: dict[str, int]
