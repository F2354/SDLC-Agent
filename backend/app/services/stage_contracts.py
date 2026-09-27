"""阶段契约（Stage Contract）：让过程模型从「调度差异」变成「行为差异」。

此前 6 种过程模型的差别只有阶段名与依赖顺序，agent 的行为完全一样：
所有阶段都读"全部前置产物"，提示词按 stage.code 选择，与过程模型无关。
V 模型描述里写的「开发↔验证对应关系」只存在于一句 description 文本。

契约让每个阶段声明三件事：

- ``inputs``     本阶段消费哪些前置阶段的产物（``None`` = 全部，向后兼容）；
- ``outputs``    本阶段必须产出的实体配额（进入提示词，并被文档校验消费）；
- ``pair_stage`` 配对验证目标 —— V 模型的灵魂：验证阶段读取配对设计产物，
  测试用例必须标注其验证的 MOD-xxx / RQ-xxx。

契约按 ``(model_code, stage_code)`` 解析：模型专属契约优先，缺省回落到
通用契约。数据不落库 —— 单一事实来源在本模块，避免"配置写了、执行没接上"。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageContract:
    """单个阶段的行为契约。"""

    # 本阶段消费的前置阶段编码；None 表示不裁剪（读全部前置产物）。
    inputs: tuple[str, ...] | None = None
    # 必须产出的实体配额，如 {"RQ": 3, "UC": 2}。
    outputs: dict[str, int] = field(default_factory=dict)
    # 配对验证目标阶段（V 模型验证通道专有）。
    pair_stage: str | None = None
    # 给提示词的补充指令。
    note: str = ""


# 通用契约：所有过程模型共享的默认行为，按阶段编码索引。
DEFAULT_CONTRACTS: dict[str, StageContract] = {
    "requirements": StageContract(
        inputs=(),
        outputs={"RQ": 3, "UC": 2},
        note="你是流程起点，不要引用不存在的上游产物；用例必须标注来源需求（来源：RQ-xxx）。",
    ),
    "architecture": StageContract(
        inputs=("requirements",),
        outputs={"MOD": 2},
        note="模块必须标注实现的需求或用例（实现：RQ-xxx、UC-xxx）。",
    ),
    "detailed-design": StageContract(
        inputs=("requirements", "architecture"),
        outputs={"MOD": 2},
        note="接口与类定义必须标注所属模块（MOD-xxx），供集成测试与单元测试对照。",
    ),
    "coding": StageContract(
        inputs=None,
        outputs={},
        note="代码必须实现详细设计中的接口定义与模块划分。",
    ),
    "testing": StageContract(
        inputs=None,
        outputs={"TC": 3},
        note="测试用例必须标注验证的需求或模块（验证：RQ-xxx / MOD-xxx）。",
    ),
    "prototype": StageContract(
        inputs=("requirements",),
        outputs={},
        note="原型聚焦核心交互流程，不必追求功能完备。",
    ),
    "user-feedback": StageContract(
        inputs=("prototype",),
        outputs={},
        note="反馈必须指向原型中的具体交互，整理成可执行的改进项。",
    ),
    "refinement": StageContract(
        inputs=("requirements", "user-feedback"),
        outputs={"RQ": 2, "UC": 2},
        note="在原需求文档基础上精化：标注哪些条目被反馈修改或新增，保持编号可追溯。",
    ),
    "risk-analysis": StageContract(
        inputs=("requirements",),
        outputs={},
        note="每条风险给出等级（高/中/低）与缓解策略，高风险条目要影响后续设计决策。",
    ),
    "backlog": StageContract(
        inputs=(),
        outputs={"RQ": 2},
        note="用户故事按优先级排列并编号（RQ-xxx），作为后续 Sprint 的选取来源。",
    ),
    "sprint-planning": StageContract(
        inputs=("backlog",),
        outputs={},
        note="明确本 Sprint 选取了哪些 RQ-xxx 条目作为目标，未选取的说明理由。",
    ),
    "sprint-dev": StageContract(
        inputs=None,
        outputs={},
        note="实现 Sprint 计划中选取的条目，并在提交说明中对应 RQ-xxx。",
    ),
}

# V 模型专属契约：三层配对是 V 模型区别于其它模型的本质。
#   需求分析   ↔ 系统测试   （系统测试对照需求的验收标准做端到端验证）
#   概要设计   ↔ 集成测试   （集成测试验证模块间接口协同）
#   详细设计   ↔ 单元测试   （单元测试对照类与接口定义验证核心模块）
# 验证阶段的 inputs 同时纳入配对设计产物与编码产物：前者是验证依据，
# 后者是被测对象。
_V_MODEL_CONTRACTS: dict[str, StageContract] = {
    "unit-test": StageContract(
        inputs=("coding", "detailed-design"),
        outputs={"TC": 2},
        pair_stage="detailed-design",
        note=(
            "单元测试的验证依据是《详细设计》中的类结构与接口定义（MOD-xxx）："
            "每个测试用例必须标注其验证的模块（验证：MOD-xxx），"
            "并针对该模块的接口行为设计断言，而不是泛泛地测端到端功能。"
        ),
    ),
    "integration-test": StageContract(
        inputs=("coding", "detailed-design"),
        outputs={"TC": 2},
        pair_stage="detailed-design",
        note=(
            "集成测试的验证依据是《详细设计》中的接口定义与模块边界（MOD-xxx）："
            "每个测试用例必须标注其验证的模块间接口（验证：MOD-xxx），"
            "重点覆盖模块协同与数据流转，而非单个模块内部逻辑。"
        ),
    ),
    "system-test": StageContract(
        inputs=("coding", "requirements"),
        outputs={"TC": 2},
        pair_stage="requirements",
        note=(
            "系统测试的验证依据是《需求分析》中的需求条目与验收标准（RQ-xxx）："
            "每个测试用例必须标注其验证的需求（验证：RQ-xxx），"
            "按端到端用户视角设计，确保每条核心需求至少被一个用例覆盖。"
        ),
    ),
}

# 其余模型的专属差异（当前从简，未列出的回落通用契约）。
_MODEL_CONTRACTS: dict[str, dict[str, StageContract]] = {
    "v-model": _V_MODEL_CONTRACTS,
}


def stage_contract(model_code: str | None, stage_code: str) -> StageContract:
    """解析某过程模型下某阶段的契约；未声明时回落通用契约。"""
    overrides = _MODEL_CONTRACTS.get(model_code or "", {})
    return overrides.get(stage_code) or DEFAULT_CONTRACTS.get(stage_code, StageContract())


def contract_context_text(contract: StageContract) -> str:
    """把契约渲染成提示词条目（输入约束 + 配对验证指令）。"""
    parts: list[str] = []
    if contract.inputs is not None:
        if contract.inputs:
            parts.append("输入契约：只依据以下前置阶段的产物工作，不得凭空引入它们之外的功能——" + "、".join(contract.inputs) + "。")
        else:
            parts.append("输入契约：本阶段没有前置产物，作为流程起点工作。")
    if contract.pair_stage:
        parts.append(
            f"配对验证：本阶段与「{contract.pair_stage}」阶段互为验证关系，"
            "先阅读该阶段产物中的实体定义，再据此设计测试。"
        )
    if contract.note:
        parts.append(contract.note)
    return "\n".join(parts)
