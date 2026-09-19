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
