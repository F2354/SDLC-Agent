"""上下文预算与结构化裁剪。

前置产物此前是"全文拼接"注入提示词：项目越往后走、文档越长，注入量线性增长
（实测 V 模型详细设计一次调用输入就 3,278 token，其中大头是前置文档）。
后果有二：一是成本与延迟随阶段递增；二是长上下文会让模型"淹没"，
实测出现过 agent 在编码阶段反复读文件、写不出东西的读取循环。

本模块提供三件事：

- ``BUDGETS``：按阶段给出的上下文字符预算（可覆盖）；
- ``allocate``：按优先级把预算分配给多份文档（水位法，短文档的余额回流）；
- ``trim_document``：超预算时的**结构化**裁剪 —— 保留章节骨架与带编号的实体
  小节，截断冗长正文与代码块，并显式标注截断位置（让模型知道自己看到的
  是节选，而不是完整的上一阶段产物）。

调用侧只消费 ``compose_context`` 一个入口，保证"文档阶段"与"工具循环"
拿到的是同一份裁剪结果。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 单份文档的保留区间：少于 floor 不给（信息量太低），多于 cap 不给（会压死别人）。
_MIN_QUOTA = 1200
_MAX_QUOTA = 6000

# 阶段默认预算（字符）。原则：越靠后的阶段需要越多前置信息；
# 验证类阶段只读配对设计与被测代码，无需全量。
BUDGETS: dict[str, int] = {
    "requirements": 6000,
    "architecture": 10000,
    "detailed-design": 14000,
    "coding": 16000,
    "testing": 14000,
    "unit-test": 12000,
    "integration-test": 12000,
    "system-test": 14000,
    "risk-analysis": 9000,
    "evaluation": 12000,
    "iteration-review": 12000,
    "prototype": 8000,
    "user-feedback": 8000,
    "refinement": 12000,
    "backlog": 6000,
    "sprint-planning": 8000,
    "sprint-dev": 16000,
    "sprint-review": 12000,
    "sprint-retrospective": 10000,
}
DEFAULT_BUDGET = 10000

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_ENTITY = re.compile(r"\b(RQ|UC|MOD|TC|RSK)[-_]?\d+\b", re.IGNORECASE)


def budget_for(stage_code: str) -> int:
    return BUDGETS.get(stage_code, DEFAULT_BUDGET)


def allocate(sizes: list[int], budget: int) -> list[int]:
    """按水位法把预算分给多份文档：短文档用不完的额度回流给长文档。"""
    if not sizes:
        return []
    count = len(sizes)
    quotas = [min(_MAX_QUOTA, max(_MIN_QUOTA, budget // count)) for _ in sizes]
    for _ in range(4):
        used = sum(min(quota, size) for quota, size in zip(quotas, sizes))
        leftover = budget - used
        needy = [i for i, size in enumerate(sizes) if size > quotas[i]]
        if leftover <= 0 or not needy:
            break
        bonus = leftover // len(needy)
        if bonus <= 0:
            break
        for index in needy:
            quotas[index] = min(_MAX_QUOTA, quotas[index] + bonus)
    return quotas


def _split_blocks(content: str) -> list[tuple[str, str]]:
    """按 Markdown 标题切块，返回 (标题行, 正文)。无标题时整体作为一块。"""
    blocks: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in content.splitlines():
        if _HEADING.match(line) and (heading or body):
            blocks.append((heading, "\n".join(body).strip()))
            heading = line
            body = []
        elif _HEADING.match(line):
            heading = line
        else:
            body.append(line)
    if heading or body:
        blocks.append((heading, "\n".join(body).strip()))
    return [(h, b) for h, b in blocks if h or b]


def trim_document(content: str, max_chars: int) -> tuple[str, bool]:
    """结构化裁剪：保留章节骨架与实体小节，截断冗长正文。

    返回 (裁剪后的文本, 是否发生截断)。
    """
    text = content or ""
    if len(text) <= max_chars:
        return text, False

    blocks = _split_blocks(text)
    if not blocks:
        return text[:max_chars], True

    # 带实体编号的小节权重更高（它们是追溯与下游消费的关键信息）
    weights = [
        3.0 if (_ENTITY.search(head) or _ENTITY.search(body[:200])) else 1.0
        for head, body in blocks
    ]
    pieces: list[str] = []
    remaining = max(200, max_chars - 200)  # 预留截断提示的位置
    for index, (head, body) in enumerate(blocks):
        rest_weight = sum(weights[index:]) or 1.0
        share = int(remaining * weights[index] / rest_weight)
        piece = f"{head}\n{body}".strip()
        if len(piece) <= share:
            pieces.append(piece)
            remaining -= len(piece)
            continue
        keep = max(80, share)
        pieces.append(piece[:keep].rstrip() + "\n…（本小节超出单份文档配额，已截断）")
        remaining -= len(pieces[-1])
    marker = (
        f"\n\n> 注：以上内容按上下文预算（本阶段共 {max_chars} 字符）做了结构化裁剪，"
        "保留了章节骨架与主要实体小节；如需完整原文，请查阅对应阶段产物。"
    )
    return "\n\n".join(pieces) + marker, True


@dataclass
class ContextEntry:
    """一份前置产物在上下文中的实际占用。"""

    stage_code: str
    title: str
    original_chars: int
    used_chars: int
    trimmed: bool


@dataclass
class ContextStats:
    budget: int = 0
    total_chars: int = 0
    trimmed_documents: int = 0
    entries: list[ContextEntry] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "budget": self.budget,
            "total_chars": self.total_chars,
            "trimmed_documents": self.trimmed_documents,
            "entries": [
                {
                    "stage": entry.stage_code,
                    "chars": entry.used_chars,
                    "original_chars": entry.original_chars,
                    "trimmed": entry.trimmed,
                }
                for entry in self.entries
            ],
        }

    def note(self) -> str:
        """给活动日志用的一句话。"""
        detail = f"上下文 {self.total_chars} 字符 / 预算 {self.budget}"
        if self.trimmed_documents:
            detail += f"；已结构化裁剪 {self.trimmed_documents} 份文档"
        return detail


def compose_context(
    documents: list[tuple[str, str, str]],
    *,
    stage_code: str,
    priority: list[str] | None,
    budget: int | None = None,
) -> tuple[str, ContextStats]:
    """把多份前置产物拼成上下文。

    documents: [(stage_code, title, content)]
    priority:  阶段编码优先级（靠前者多分预算，通常是配对阶段与紧邻前驱）
    """
    limit = budget if budget is not None else budget_for(stage_code)
    stats = ContextStats(budget=limit)
    if not documents:
        return "", stats

    order = {code: index for index, code in enumerate(priority or [])}
    ranked = sorted(
        enumerate(documents),
        key=lambda item: (order.get(item[1][0], len(order) + item[0]), item[0]),
    )
    sizes = [len(doc[2] or "") for _, doc in ranked]
    quotas = allocate(sizes, limit)

    chunks: list[str] = []
    for (_, (stage_code_, title, content)), quota in zip(ranked, quotas):
        text, trimmed = trim_document(content or "", quota)
        stats.entries.append(
            ContextEntry(
                stage_code=stage_code_,
                title=title,
                original_chars=len(content or ""),
                used_chars=len(text),
                trimmed=trimmed,
            )
        )
        if trimmed:
            stats.trimmed_documents += 1
        chunks.append(f"### {title}\n{text}")
    stats.total_chars = sum(entry.used_chars for entry in stats.entries)
    return "\n\n".join(chunks), stats
