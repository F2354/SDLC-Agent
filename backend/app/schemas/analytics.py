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


class TraceabilityLinkOut(BaseModel):
    from_type: str
    from_key: str
    to_type: str
    to_key: str
    relation: str


class TraceabilityCoverage(BaseModel):
    rq_total: int = 0
    rq_with_uc: int = 0
    rq_with_mod: int = 0
    rq_with_tc: int = 0
    mod_total: int = 0
    mod_with_tc: int = 0
    tc_total: int = 0
    unresolved: list[str] = []


class TraceabilityOut(BaseModel):
    rows: list[TraceabilityArtifactRow]
    entity_counts: dict[str, int]
    warnings: list[str]
    links: list[TraceabilityLinkOut] = []
    coverage: TraceabilityCoverage = TraceabilityCoverage()


class ProjectStatsOut(BaseModel):
    project_id: int
    stage_counts: dict[str, int]
    artifact_count: int
    total_chars: int
    entity_counts: dict[str, int]
