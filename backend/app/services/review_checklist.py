"""结构化评审清单。

此前清单只存在于**评审 Agent 的提示词**里（一串自然语言条目），人工评审
界面只有自由文本 —— 两边的"检查项"根本不是同一份东西，也无法沉淀结论。
本模块把清单收敛成单一事实来源：

- ``items_for``：某阶段的检查项（带稳定 id，便于存结论与横向对比）；
- ``build_checklist_instruction``：给评审 Agent 的结构化输出约定；
- ``parse_verdicts``：把 Agent 输出解析成 ``{item_id: (verdict, note)}``，
  用于在人工界面预填"Agent 建议"。

verdict 取值：passed（通过）/ failed（不通过）/ na（不适用）。
清单不落库 —— 与阶段契约同样的取舍：配置写在代码里，避免"建了表却没人写"
（stage_agent_bindings、review_checklist_items 都曾如此）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERDICT_LABELS = {"passed": "通过", "failed": "不通过", "na": "不适用"}


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    text: str
    hint: str = ""


def _items(prefix: str, rows: list[tuple[str, str, str]]) -> list[ChecklistItem]:
    return [ChecklistItem(id=f"{prefix}-{key}", text=text, hint=hint) for key, text, hint in rows]


CHECKLISTS: dict[str, list[ChecklistItem]] = {
    "requirements": _items(
        "req",
        [
            ("scope", "是否覆盖项目目标、用户角色、功能与非功能需求、约束与验收标准", "缺章节直接不通过"),
            ("numbering", "需求条目是否使用 RQ-001 连续编号且描述可验证", "一条需求只描述一件事，可判定真假"),
            ("trace", "每个需求是否至少关联一个用例 UC-00X", "追溯矩阵里 RQ→UC 应无缺口"),
            ("honest", "是否存在与项目描述冲突或凭空新增的功能", "不得发明需求之外的能力"),
        ],
    ),
    "architecture": _items(
        "arch",
        [
            ("layers", "是否给出系统架构、技术选型、模块划分与部署视图", ""),
            ("modules", "模块是否使用 MOD-001 编号并说明其实现的需求或用例", "标注「实现：RQ-xxx」"),
            ("coverage", "是否覆盖全部需求，无遗漏关键模块", ""),
            ("constraint", "技术选型是否与约束条件一致", "如数据库/部署环境约束"),
        ],
    ),
    "detailed-design": _items(
        "design",
        [
            ("classes", "是否包含类设计、数据库设计、接口定义与关键流程", ""),
            ("trace", "接口与数据表是否可追溯到模块", "标注所属 MOD-xxx"),
            ("fields", "字段、类型与约束是否明确", "不得出现「等」「若干」这类含糊描述"),
            ("consistency", "是否与概要设计保持一致", "模块划分不应临时改动"),
        ],
    ),
    "coding": _items(
        "code",
        [
            ("runnable", "代码是否可运行并通过验证", "运行验证需真实执行"),
            ("tests", "是否包含自动化测试且测试通过", "至少覆盖核心模块"),
            ("structure", "目录结构是否符合阶段的默认工作区约定", ""),
        ],
    ),
    "testing": _items(
        "test",
        [
            ("plan", "是否包含测试策略、测试计划、测试用例与报告模板", ""),
            ("numbering", "测试用例是否使用 TC-001 编号并标注验证的需求或模块", "标注「验证：RQ-xxx / MOD-xxx」"),
            ("coverage", "需求是否被测试用例覆盖，是否存在无对应需求的用例", ""),
            ("edge", "是否包含边界与异常场景", ""),
        ],
    ),
    "unit-test": _items(
        "unit",
        [
            ("paired", "测试是否对照《详细设计》的类与接口定义设计", "验证依据是配对设计产物"),
            ("numbering", "用例是否标注其验证的模块（验证：MOD-xxx）", ""),
            ("assert", "断言是否针对接口行为，而不是泛泛的端到端流程", ""),
            ("run", "测试是否真实执行且通过", ""),
        ],
    ),
    "integration-test": _items(
        "int",
        [
            ("paired", "测试是否覆盖《详细设计》中的模块间接口与数据流转", ""),
            ("numbering", "用例是否标注其验证的模块间接口（验证：MOD-xxx）", ""),
            ("run", "测试是否真实执行且通过", ""),
        ],
    ),
    "system-test": _items(
        "sys",
        [
            ("paired", "测试是否对照《需求分析》的验收标准做端到端验证", ""),
            ("numbering", "用例是否标注其验证的需求（验证：RQ-xxx）", ""),
            ("coverage", "核心需求是否至少被一个用例覆盖", ""),
            ("run", "测试是否真实执行且通过", ""),
        ],
    ),
    "risk-analysis": _items(
        "risk",
        [
            ("identify", "是否识别技术、资源与进度风险", "每条风险独立编号 RSK-xxx"),
            ("level", "是否为风险标注等级（高/中/低）与量化评估", ""),
            ("mitigation", "是否给出缓解策略与风险监控计划", ""),
        ],
    ),
    "evaluation": _items(
        "eval",
        [
            ("criteria", "是否对照验收标准逐项评估", ""),
            ("risks", "是否汇总风险关闭情况（引用 RSK-xxx）", ""),
            ("next", "是否给出进入下一轮或交付的明确结论", ""),
        ],
    ),
    "iteration-review": _items(
        "iter",
        [
            ("goal", "是否回顾迭代目标并核对验收标准", ""),
            ("next", "是否产出下一迭代的改进需求（新 RQ 编号）", ""),
        ],
    ),
    "prototype": _items(
        "proto",
        [
            ("flow", "原型是否覆盖核心交互流程", ""),
            ("demo", "是否说明技术实现方案与演示方式", ""),
        ],
    ),
    "user-feedback": _items(
        "fb",
        [
            ("organize", "是否分类整理用户反馈并给出优先级", ""),
            ("traceable", "反馈是否指向原型中的具体交互", ""),
        ],
    ),
    "refinement": _items(
        "refine",
        [
            ("origin", "是否标注哪些条目因反馈被修改或新增", "保持编号可追溯"),
            ("complete", "精化后的需求是否仍完整覆盖项目目标", ""),
        ],
    ),
    "backlog": _items(
        "backlog",
        [
            ("story", "是否按用户故事组织并标注优先级", "使用 RQ-xxx 编号"),
            ("estimate", "是否给出工作量估算", ""),
        ],
    ),
    "sprint-planning": _items(
        "plan",
        [
            ("selection", "是否明确本 Sprint 选取了哪些条目（RQ-xxx）", ""),
            ("tasks", "是否把条目拆分为可执行任务", ""),
        ],
    ),
    "sprint-dev": _items(
        "dev",
        [
            ("runnable", "代码是否可运行并通过验证", ""),
            ("trace", "提交说明是否对应 Sprint 计划中的条目", ""),
        ],
    ),
    "sprint-review": _items(
        "review",
        [
            ("status", "是否对照 Sprint 计划逐项给出完成状态", ""),
            ("feedback", "是否记录利益相关者反馈", ""),
        ],
    ),
    "sprint-retrospective": _items(
        "retro",
        [
            ("improve", "是否识别改进点并给出可执行的改进计划", ""),
        ],
    ),
}

DEFAULT_CHECKLIST = _items(
    "generic",
    [
        ("complete", "产物章节是否完整覆盖本阶段职责", ""),
        ("consistent", "内容是否与前置产物一致，未凭空发明", ""),
        ("reviewable", "是否具备可评审的具体结论，而非泛泛而谈", ""),
    ],
)


def items_for(stage_code: str) -> list[ChecklistItem]:
    return CHECKLISTS.get(stage_code, DEFAULT_CHECKLIST)


def item_ids(stage_code: str) -> list[str]:
    return [item.id for item in items_for(stage_code)]


def build_checklist_instruction(stage_code: str) -> str:
    """给评审 Agent 的结构化输出约定（id 用于回填人工界面）。"""
    lines = [
        f"- [{item.id}] {item.text}" + (f"（{item.hint}）" if item.hint else "")
        for item in items_for(stage_code)
    ]
    return (
        "检查清单（逐项给出判定，格式必须严格为 "
        "`- [检查项 id] 通过/不通过/不适用 —— 原因`，不要增删 id）：\n"
        + "\n".join(lines)
    )


_VERDICT_LINE = re.compile(
    r"^\s*[-*]\s*\[?([a-z0-9_-]+)\]?\s*[:：]?\s*(通过|不通过|不适用|passed|failed|na)\s*(?:[—\-–:：]+)?\s*(.*)$",
    re.IGNORECASE,
)
_LABEL_TO_KEY = {
    "通过": "passed",
    "不通过": "failed",
    "不适用": "na",
    "passed": "passed",
    "failed": "failed",
    "na": "na",
}


def parse_verdicts(stage_code: str, text: str) -> dict[str, dict[str, str]]:
    """从评审文本里解析逐项判定，只保留属于该阶段清单的 id。"""
    known = set(item_ids(stage_code))
    found: dict[str, dict[str, str]] = {}
    for raw_line in (text or "").splitlines():
        match = _VERDICT_LINE.match(raw_line.strip())
        if not match:
            continue
        item_id, label, note = match.group(1).lower(), match.group(2).lower(), match.group(3)
        if item_id not in known:
            continue
        found[item_id] = {
            "verdict": _LABEL_TO_KEY.get(label, "passed"),
            "note": note.strip()[:500],
        }
    return found


def verdict_summary(verdicts: dict[str, dict[str, str]]) -> str:
    """一句话概括（写进活动日志）。"""
    if not verdicts:
        return "清单未逐项判定"
    passed = sum(1 for item in verdicts.values() if item.get("verdict") == "passed")
    failed = sum(1 for item in verdicts.values() if item.get("verdict") == "failed")
    na = sum(1 for item in verdicts.values() if item.get("verdict") == "na")
    parts = [f"通过 {passed}"]
    if failed:
        parts.append(f"不通过 {failed}")
    if na:
        parts.append(f"不适用 {na}")
    return "清单核对：" + " · ".join(parts)
