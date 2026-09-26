"""追溯与一致性。

从阶段产物中解析实体（需求 RQ、用例 UC、模块 MOD、测试用例 TC），
按"同一小节内共现"推断实体关联，落库到 traceability_links，
并据此计算覆盖率与未定义引用等一致性提示。
"""
from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.stage_run import Artifact, TraceabilityLink
from app.schemas.analytics import (
    EntityGroupOut,
    TraceabilityArtifactRow,
    TraceabilityCoverage,
    TraceabilityLinkOut,
    TraceabilityOut,
)

ENTITY_PATTERNS = {
    "RQ": re.compile(r"\bRQ[-_]?(\d+)\b", re.IGNORECASE),
    "UC": re.compile(r"\bUC[-_]?(\d+)\b", re.IGNORECASE),
    "MOD": re.compile(r"\bMOD[-_]?(\d+)\b", re.IGNORECASE),
    "TC": re.compile(r"\bTC[-_]?(\d+)\b", re.IGNORECASE),
}

# 实体的自然流转顺序：需求 → 用例 → 模块 → 测试用例。
ENTITY_ORDER = ["RQ", "UC", "MOD", "TC"]

# 有序类型对 → 关系名。
_RELATIONS = {
    ("RQ", "UC"): "derives",
    ("RQ", "MOD"): "realizes",
    ("UC", "MOD"): "realizes",
    ("RQ", "TC"): "verifies",
    ("UC", "TC"): "verifies",
    ("MOD", "TC"): "verifies",
}

# 单个小节内允许生成的最大关联数，避免异常文档导致组合爆炸。
_MAX_LINKS_PER_BLOCK = 200

# 各阶段必须产出的实体数量下限（实体类型 → 最少条数）。
#
# 这是让追溯矩阵真正有数据的关键：此前用例 UC 在 18 个真实产物中检出数恒为 0，
# 追溯覆盖率因此永远是 0。该常量同时被两处消费 ——
# 生成阶段写进提示词（prompts），校验阶段用来判定文档是否合规（stage_service），
# 从而复用 LangGraph 既有的重试回路去要求模型补齐。
STAGE_ENTITY_REQUIREMENTS: dict[str, dict[str, int]] = {
    "requirements": {"RQ": 3, "UC": 2},
    "architecture": {"MOD": 2},
    "detailed-design": {"MOD": 2},
    "testing": {"TC": 3},
    "unit-test": {"TC": 2},
    "integration-test": {"TC": 2},
    "system-test": {"TC": 2},
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


def _split_blocks(content: str) -> list[str]:
    """按 Markdown 标题切分小节，保持标题与其正文在同一块内。"""
    blocks: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        if line.lstrip().startswith("#") and current:
            blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _defined_keys(content: str) -> dict[str, set[str]]:
    """标题中出现的实体视为"定义"，仅正文出现视为"引用"。"""
    defined: dict[str, set[str]] = {entity_type: set() for entity_type in ENTITY_ORDER}
    for line in content.splitlines():
        if not line.lstrip().startswith("#"):
            continue
        for entity_type, keys in parse_entities(line).items():
            defined[entity_type].update(keys)
    return defined


def _build_adjacency(
    edges: set[tuple[str, str, str, str]],
) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """把关系边集合转成邻接表，键与值都是 (实体类型, 实体编号)。"""
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for from_type, from_key, to_type, to_key in edges:
        adjacency.setdefault((from_type, from_key), set()).add((to_type, to_key))
    return adjacency


def _reaches(
    adjacency: dict[tuple[str, str], set[tuple[str, str]]],
    start: tuple[str, str],
    target_type: str,
) -> bool:
    """从 start 沿关系图出发，能否到达任意 target_type 的实体（允许经中间实体）。

    需求到模块的覆盖通常是「RQ → UC → MOD」两跳，只看直接相邻会低估覆盖率，
    因此这里按可达性判断，更贴近"这条需求最终有没有落到设计上"的语义。
    """
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop()
        for neighbour in adjacency.get(current, ()):
            if neighbour[0] == target_type:
                return True
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return False


def _artifact_links(content: str) -> set[tuple[str, str, str, str, str]]:
    """同一小节内共现的不同类型实体建立关联。"""
    links: set[tuple[str, str, str, str, str]] = set()
    for block in _split_blocks(content):
        entities = parse_entities(block)
        present = [
            (entity_type, key)
            for entity_type in ENTITY_ORDER
            for key in entities[entity_type]
        ]
        for index, (from_type, from_key) in enumerate(present):
            for to_type, to_key in present[index + 1 :]:
                if from_type == to_type:
                    continue
                relation = _RELATIONS.get((from_type, to_type))
                if relation is None:
                    continue
                links.add((from_type, from_key, to_type, to_key, relation))
                if len(links) >= _MAX_LINKS_PER_BLOCK:
                    return links
    return links


def rebuild_traceability(db: Session, project_id: int) -> int:
    """按当前产物内容重建追溯关系，返回写入的关系数量。"""
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.id)
        )
    )
    db.execute(
        delete(TraceabilityLink).where(TraceabilityLink.project_id == project_id)
    )
    count = 0
    for artifact in artifacts:
        for from_type, from_key, to_type, to_key, relation in _artifact_links(
            artifact.content_md or ""
        ):
            db.add(
                TraceabilityLink(
                    project_id=project_id,
                    artifact_id=artifact.id,
                    from_type=from_type,
                    from_key=from_key,
                    to_type=to_type,
                    to_key=to_key,
                    relation=relation,
                )
            )
            count += 1
    db.commit()
    return count


def _load_links(db: Session, project_id: int) -> list[TraceabilityLink]:
    return list(
        db.scalars(
            select(TraceabilityLink)
            .where(TraceabilityLink.project_id == project_id)
            .order_by(TraceabilityLink.id)
        )
    )


def compute_traceability(db: Session, project_id: int) -> TraceabilityOut:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.id)
        )
    )
    rows: list[TraceabilityArtifactRow] = []
    all_entities = {entity_type: set() for entity_type in ENTITY_ORDER}
    defined: dict[str, set[str]] = {entity_type: set() for entity_type in ENTITY_ORDER}

    for artifact in artifacts:
        content = artifact.content_md or ""
        entities = parse_entities(content)
        for entity_type, keys in entities.items():
            all_entities[entity_type].update(keys)
        for entity_type, keys in _defined_keys(content).items():
            defined[entity_type].update(keys)
        rows.append(
            TraceabilityArtifactRow(
                artifact_id=artifact.id,
                title=artifact.title,
                stage_code=artifact.type,
                entities=EntityGroupOut(**entities),
            )
        )

    links = _load_links(db, project_id)
    if not links and artifacts:
        # 关系表为空但存在产物：可能是历史数据，补建一次。
        rebuild_traceability(db, project_id)
        links = _load_links(db, project_id)

    edge_set = {
        (link.from_type, link.from_key, link.to_type, link.to_key) for link in links
    }
    adjacency = _build_adjacency(edge_set)

    def covered(entity_type: str, key: str, target_type: str) -> bool:
        return _reaches(adjacency, (entity_type, key), target_type)

    rq_keys = sorted(all_entities["RQ"])
    mod_keys = sorted(all_entities["MOD"])
    tc_keys = sorted(all_entities["TC"])

    coverage = TraceabilityCoverage(
        rq_total=len(rq_keys),
        rq_with_uc=sum(1 for key in rq_keys if covered("RQ", key, "UC")),
        rq_with_mod=sum(1 for key in rq_keys if covered("RQ", key, "MOD")),
        rq_with_tc=sum(1 for key in rq_keys if covered("RQ", key, "TC")),
        mod_total=len(mod_keys),
        mod_with_tc=sum(1 for key in mod_keys if covered("MOD", key, "TC")),
        tc_total=len(tc_keys),
    )

    # 未定义引用：正文里出现、但没有任何标题定义过的实体编号。
    unresolved: list[str] = []
    for entity_type in ENTITY_ORDER:
        for key in sorted(all_entities[entity_type] - defined[entity_type]):
            unresolved.append(key)
    coverage.unresolved = unresolved

    warnings: list[str] = []
    if rq_keys and coverage.rq_with_uc < len(rq_keys):
        warnings.append(
            f"需求到用例：{coverage.rq_with_uc}/{len(rq_keys)} 条需求已关联 UC 用例"
            + ("" if coverage.rq_with_uc else "（用例缺失会让整条追溯链断裂）")
        )
    if rq_keys and coverage.rq_with_mod < len(rq_keys):
        warnings.append(
            f"需求到模块：{coverage.rq_with_mod}/{len(rq_keys)} 条需求已落到 MOD 设计模块"
        )
    if rq_keys and coverage.rq_with_tc < len(rq_keys):
        warnings.append(
            f"需求到测试：{coverage.rq_with_tc}/{len(rq_keys)} 条需求已被 TC 用例覆盖"
        )
    if mod_keys and coverage.mod_with_tc < len(mod_keys):
        warnings.append(
            f"模块到测试：{coverage.mod_with_tc}/{len(mod_keys)} 个模块已被 TC 用例覆盖"
        )
    if tc_keys and coverage.rq_with_tc == 0 and coverage.mod_with_tc == 0:
        warnings.append("测试用例未关联任何需求或模块")
    if unresolved:
        warnings.append(
            "存在未定义的实体引用：" + "、".join(unresolved[:10])
            + ("…" if len(unresolved) > 10 else "")
        )
    if not warnings and artifacts:
        warnings.append("追溯关系完整，未发现缺失覆盖")

    return TraceabilityOut(
        rows=rows,
        entity_counts={key: len(values) for key, values in all_entities.items()},
        warnings=warnings,
        links=[
            TraceabilityLinkOut(
                from_type=link.from_type,
                from_key=link.from_key,
                to_type=link.to_type,
                to_key=link.to_key,
                relation=link.relation,
            )
            for link in links
        ],
        coverage=coverage,
    )
