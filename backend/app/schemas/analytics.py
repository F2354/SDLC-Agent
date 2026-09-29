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


class LLMUsageGroupOut(BaseModel):
    """按模型或用途聚合的用量分组。"""

    key: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: int = 0


class LLMCallOut(BaseModel):
    id: int
    model: str = ""
    purpose: str | None = None
    stage_run_id: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    status: str = "success"
    error: str | None = None
    created_at: str | None = None


class LLMUsageOut(BaseModel):
    """项目级模型调用用量：总量 + 按模型/用途分组 + 最近调用。"""

    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: int = 0
    max_latency_ms: int = 0
    total_latency_ms: int = 0
    by_model: list[LLMUsageGroupOut] = []
    by_purpose: list[LLMUsageGroupOut] = []
    recent: list[LLMCallOut] = []
