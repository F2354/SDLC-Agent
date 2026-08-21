import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stage_run import Artifact
from app.schemas.analytics import (
    EntityGroupOut,
    TraceabilityArtifactRow,
    TraceabilityOut,
)

ENTITY_PATTERNS = {
    "RQ": re.compile(r"\bRQ[-_]?(\d+)\b", re.IGNORECASE),
    "UC": re.compile(r"\bUC[-_]?(\d+)\b", re.IGNORECASE),
    "MOD": re.compile(r"\bMOD[-_]?(\d+)\b", re.IGNORECASE),
    "TC": re.compile(r"\bTC[-_]?(\d+)\b", re.IGNORECASE),
}


def parse_entities(content: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entity_type, pattern in ENTITY_PATTERNS.items():
        keys = sorted(
            {
                f"{entity_type}-{match.group(1)}"
                for match in pattern.finditer(content)
            }
        )
        result[entity_type] = keys
    return result


def compute_traceability(db: Session, project_id: int) -> TraceabilityOut:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.id)
        )
    )
    rows: list[TraceabilityArtifactRow] = []
    all_entities = {entity_type: set() for entity_type in ENTITY_PATTERNS}

    for artifact in artifacts:
        entities = parse_entities(artifact.content_md)
        for entity_type, keys in entities.items():
            all_entities[entity_type].update(keys)
        rows.append(
            TraceabilityArtifactRow(
                artifact_id=artifact.id,
                title=artifact.title,
                stage_code=artifact.type,
                entities=EntityGroupOut(**entities),
            )
        )

    warnings: list[str] = []
    if not all_entities["RQ"]:
        warnings.append("需求阶段未发现 RQ 需求条目")
    elif not all_entities["UC"]:
        warnings.append("需求条目尚未关联 UC 用例")
    if all_entities["RQ"] and not all_entities["MOD"]:
        warnings.append("需求条目尚未对应 MOD 设计模块")
    if all_entities["MOD"] and not all_entities["TC"]:
        warnings.append("设计模块尚未覆盖 TC 测试用例")

    return TraceabilityOut(
        rows=rows,
        entity_counts={key: len(values) for key, values in all_entities.items()},
        warnings=warnings,
    )
