"""LLM 调用日志与用量统计。

`llm_call_logs` 表建了很久但一行没写 —— 界面上谈"模型用量/成本"却无据可依，
阶段运行失败时也看不到真实调用开销。本模块提供两个能力：

- ``record_llm_call``：把一次调用（模型、用途、token、耗时、状态）落库。
  写日志失败绝不影响主流程（业务优先，观测其次）。
- ``usage_summary``：按项目聚合调用次数、token 与耗时，并按模型/用途分组。

用途（purpose）取值：document_generate / document_retry / stage_review /
tool_loop / test_mapping / chat_confirm / provider_test。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.llm_provider import LLMCallLog

logger = __import__("logging").getLogger("uvicorn.error")


@dataclass
class UsageGroup:
    key: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: int = 0


@dataclass
class UsageSummary:
    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: int = 0
    max_latency_ms: int = 0
    total_latency_ms: int = 0
    by_model: list[UsageGroup] = field(default_factory=list)
    by_purpose: list[UsageGroup] = field(default_factory=list)


def extract_token_usage(completion: object) -> tuple[int, int]:
    """从 OpenAI 兼容响应里取 (prompt_tokens, completion_tokens)，缺失返回 (0, 0)。"""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if prompt is None and isinstance(usage, dict):
        prompt = usage.get("prompt_tokens")
    if completion_tokens is None and isinstance(usage, dict):
        completion_tokens = usage.get("completion_tokens")
    return int(prompt or 0), int(completion_tokens or 0)


def record_llm_call(
    db: Session | None,
    *,
    provider_id: int | None,
    model: str,
    purpose: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "success",
    error: str | None = None,
    project_id: int | None = None,
    stage_run_id: int | None = None,
    user_id: int | None = None,
) -> None:
    """写入一条调用日志。任何异常都只记日志，不向上抛。"""
    if db is None:
        return
    try:
        db.add(
            LLMCallLog(
                user_id=user_id,
                provider_id=provider_id,
                model=model or "",
                project_id=project_id,
                stage_run_id=stage_run_id,
                purpose=purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_ms=latency_ms,
                status=status,
                error=(error or None) and str(error)[:1000],
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 —— 观测失败不能拖垮业务
        logger.warning("写入 LLM 调用日志失败", exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def _grouped(db: Session, column, project_id: int) -> list[UsageGroup]:
    rows = db.execute(
        select(
            column,
            func.count(LLMCallLog.id),
            func.coalesce(func.sum(LLMCallLog.prompt_tokens), 0),
            func.coalesce(func.sum(LLMCallLog.completion_tokens), 0),
            func.coalesce(func.sum(LLMCallLog.total_tokens), 0),
            func.coalesce(func.avg(LLMCallLog.latency_ms), 0),
        )
        .where(LLMCallLog.project_id == project_id)
        .group_by(column)
        .order_by(func.coalesce(func.sum(LLMCallLog.total_tokens), 0).desc())
    ).all()
    return [
        UsageGroup(
            key=str(row[0] or "（未标注）"),
            calls=int(row[1]),
            prompt_tokens=int(row[2]),
            completion_tokens=int(row[3]),
            total_tokens=int(row[4]),
            avg_latency_ms=int(row[5] or 0),
        )
        for row in rows
    ]


def usage_summary(db: Session, project_id: int) -> UsageSummary:
    """按项目聚合调用用量；供前端"模型调用"面板与论文数据使用。"""
    row = db.execute(
        select(
            func.count(LLMCallLog.id),
            func.coalesce(func.sum(LLMCallLog.prompt_tokens), 0),
            func.coalesce(func.sum(LLMCallLog.completion_tokens), 0),
            func.coalesce(func.sum(LLMCallLog.total_tokens), 0),
            func.coalesce(func.avg(LLMCallLog.latency_ms), 0),
            func.coalesce(func.max(LLMCallLog.latency_ms), 0),
            func.coalesce(func.sum(LLMCallLog.latency_ms), 0),
        ).where(LLMCallLog.project_id == project_id)
    ).one()
    failed = db.scalar(
        select(func.count(LLMCallLog.id)).where(
            LLMCallLog.project_id == project_id, LLMCallLog.status != "success"
        )
    )
    return UsageSummary(
        calls=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        avg_latency_ms=int(row[4] or 0),
        max_latency_ms=int(row[5] or 0),
        total_latency_ms=int(row[6] or 0),
        failed_calls=int(failed or 0),
        by_model=_grouped(db, LLMCallLog.model, project_id),
        by_purpose=_grouped(db, LLMCallLog.purpose, project_id),
    )


def recent_calls(db: Session, project_id: int, limit: int = 20) -> list[LLMCallLog]:
    return list(
        db.scalars(
            select(LLMCallLog)
            .where(LLMCallLog.project_id == project_id)
            .order_by(LLMCallLog.id.desc())
            .limit(max(1, min(limit, 200)))
        )
    )
