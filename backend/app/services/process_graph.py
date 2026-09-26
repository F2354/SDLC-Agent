"""Process-model dependency graphs used by the scheduler and API.

The stage sequence remains useful for display, but scheduling decisions are made
from dependencies so independent work can run in parallel.
"""

from collections.abc import Iterable


_MODEL_DEPENDENCIES: dict[str, dict[str, tuple[str, ...]]] = {
    "waterfall": {
        "requirements": (),
        "architecture": ("requirements",),
        "detailed-design": ("architecture",),
        "coding": ("detailed-design",),
        "testing": ("coding",),
    },
    "v-model": {
        "requirements": (),
        "architecture": ("requirements",),
        "detailed-design": ("architecture",),
        "coding": ("detailed-design",),
        # The three verification lanes can be scheduled together after coding.
        "unit-test": ("coding",),
        "integration-test": ("coding",),
        "system-test": ("coding",),
    },
    "iterative": {
        "requirements": (),
        "architecture": ("requirements",),
        "detailed-design": ("architecture",),
        "coding": ("detailed-design",),
        "testing": ("coding",),
        "iteration-review": ("testing",),
    },
    "spiral": {
        "requirements": (),
        "risk-analysis": ("requirements",),
        "architecture": ("risk-analysis",),
        "coding": ("architecture",),
        "testing": ("coding",),
        "evaluation": ("testing",),
    },
    "prototype": {
        "requirements": (),
        "prototype": ("requirements",),
        "user-feedback": ("prototype",),
        "refinement": ("user-feedback",),
        "coding": ("refinement",),
        "testing": ("coding",),
    },
    "scrum": {
        "backlog": (),
        "sprint-planning": ("backlog",),
        "sprint-dev": ("sprint-planning",),
        "sprint-review": ("sprint-dev",),
        "sprint-retrospective": ("sprint-review",),
    },
}


def get_stage_dependencies(model_code: str, stage_code: str, ordered_codes: Iterable[str]) -> list[str]:
    """Return dependency codes, falling back to the displayed sequence."""
    graph = _MODEL_DEPENDENCIES.get(model_code)
    if graph is not None and stage_code in graph:
        return list(graph[stage_code])
    codes = list(ordered_codes)
    try:
        index = codes.index(stage_code)
    except ValueError:
        return []
    return codes[index - 1:index] if index > 0 else []


def group_by_parallel_batch(
    model_code: str,
    stage_codes: Iterable[str],
    ordered_codes: Iterable[str],
) -> list[list[str]]:
    """把阶段按「依赖集合完全相同」分组，同组即同一并行批次。

    例如 V 模型的单元测试 / 集成测试 / 系统测试都只依赖 coding，
    因此归为同一批次（三条可并行的验证通道）；瀑布模型每个阶段的依赖
    各不相同，因此每个批次只会有一个阶段。
    """
    all_codes = list(ordered_codes)
    groups: dict[tuple[str, ...], list[str]] = {}
    for code in stage_codes:
        key = tuple(get_stage_dependencies(model_code, code, all_codes))
        groups.setdefault(key, []).append(code)
    return list(groups.values())


def get_parallel_siblings(
    model_code: str,
    stage_code: str,
    ordered_codes: Iterable[str],
) -> list[str]:
    """返回与给定阶段属于同一并行批次的其它阶段。"""
    all_codes = list(ordered_codes)
    own = tuple(get_stage_dependencies(model_code, stage_code, all_codes))
    return [
        code
        for code in all_codes
        if code != stage_code
        and tuple(get_stage_dependencies(model_code, code, all_codes)) == own
    ]
