from app.services.review_checklist import build_checklist_instruction
from app.services.traceability import STAGE_ENTITY_REQUIREMENTS

# 实体类型的中文名，用于提示词与校验信息。
ENTITY_LABELS = {"RQ": "需求条目", "UC": "用例", "MOD": "模块", "TC": "测试用例", "RSK": "风险"}


def entity_requirement_text(stage_code: str) -> str:
    """把该阶段的实体配额写成提示词条目。

    与 ``stage_service`` 的文档校验共用 ``STAGE_ENTITY_REQUIREMENTS``，
    保证"提示词要求什么"与"校验检查什么"不会漂移。
    """
    requirements = STAGE_ENTITY_REQUIREMENTS.get(stage_code)
    if not requirements:
        return ""
    parts = [
        f"{ENTITY_LABELS.get(key, key)} {key}-xxx 至少 {count} 条"
        for key, count in requirements.items()
    ]
    return "本阶段必须产出规范编号的实体：" + "、".join(parts) + "。"


STAGE_ROLE = {
    "requirements": (
        "需求分析师",
        "负责访谈用户、整理功能与非功能需求，并编写需求规格说明书。",
    ),
    "architecture": (
        "架构师",
        "负责系统总体架构、模块划分、技术选型与部署设计。",
    ),
    "detailed-design": (
        "设计工程师",
        "负责类设计、数据库设计、接口定义与关键流程设计。",
    ),
    "coding": (
        "开发工程师",
        "负责代码目录结构、数据库 DDL 与核心模块代码骨架。",
    ),
    "testing": (
        "测试工程师",
        "负责测试策略、测试计划、测试用例与测试报告模板。",
    ),
    "risk-analysis": (
        "风险分析师",
        "负责识别项目技术风险、资源风险与进度风险，制定缓解策略。",
    ),
    "evaluation": (
        "评审专家",
        "负责评估当前阶段成果，判断是否满足验收标准并给出改进建议。",
    ),
    "iteration-review": (
        "评审专家",
        "负责评审本迭代产物，确认是否满足验收标准，规划下一迭代目标。",
    ),
    "prototype": (
        "原型工程师",
        "负责基于需求快速构建可交互的原型系统，验证核心交互流程。",
    ),
    "user-feedback": (
        "需求分析师",
        "负责收集用户对原型的反馈意见，整理改进需求。",
    ),
    "refinement": (
        "需求分析师",
        "负责根据用户反馈精化需求规格，更新需求文档。",
    ),
    "backlog": (
        "产品负责人",
        "负责梳理产品需求，按优先级排列用户故事，估算工作量。",
    ),
    "sprint-planning": (
        "Scrum Master",
        "负责组织 Sprint 计划会议，从产品待办列表中选取目标并拆分任务。",
    ),
    "sprint-dev": (
        "开发工程师",
        "负责按任务列表进行编码实现，生成可运行代码。",
    ),
    "sprint-review": (
        "Scrum Master",
        "负责组织 Sprint 评审会议，演示产出并收集利益相关者反馈。",
    ),
    "sprint-retrospective": (
        "Scrum Master",
        "负责组织 Sprint 回顾会议，回顾团队协作流程并识别改进点。",
    ),
}

STAGE_STRUCTURE = {
    "requirements": [
        "项目概述",
        "用户角色",
        "功能需求（需求条目 RQ-001）",
        "用例设计（用例 UC-001，须标注其来源需求 RQ-001）",
        "非功能需求",
        "约束条件",
        "验收标准",
        "风险分析",
    ],
    "architecture": [
        "系统架构",
        "技术选型",
        "模块划分（模块 MOD-001，须标注其实现的需求 RQ-001 或用例 UC-001）",
        "数据流设计",
        "部署视图",
    ],
    "detailed-design": [
        "类设计",
        "数据库设计",
        "接口定义（接口须关联模块 MOD-001）",
        "关键流程",
    ],
    "coding": [
        "目录结构",
        "数据库 DDL",
        "核心模块代码骨架",
        "构建与运行说明",
    ],
    "testing": [
        "测试策略",
        "测试计划",
        "测试用例（测试用例 TC-001，须标注其验证的需求 RQ-001 或模块 MOD-001）",
        "测试报告模板",
    ],
    "risk-analysis": [
        "风险识别",
        "风险评估矩阵",
        "缓解策略",
        "监控计划",
    ],
    "evaluation": [
        "成果评估",
        "验收标准检查",
        "风险复审",
        "下一阶段建议",
    ],
    "iteration-review": [
        "迭代目标回顾",
        "产物评审",
        "验收标准检查",
        "下一迭代规划",
    ],
    "prototype": [
        "原型设计",
        "交互流程",
        "技术实现方案",
        "原型演示说明",
    ],
    "user-feedback": [
        "反馈收集",
        "问题分类",
        "改进优先级",
        "用户满意度",
    ],
    "refinement": [
        "需求变更记录",
        "更新后的需求规格",
        "影响分析",
        "验收标准更新",
    ],
    "backlog": [
        "用户故事列表",
        "优先级排序",
        "工作量估算",
        "验收标准",
    ],
    "sprint-planning": [
        "Sprint 目标",
        "任务拆分",
        "工作量分配",
        "风险识别",
    ],
    "sprint-dev": [
        "编码实现",
        "单元测试",
        "代码评审",
        "集成说明",
    ],
    "sprint-review": [
        "演示内容",
        "利益相关者反馈",
        "问题记录",
        "改进建议",
    ],
    "sprint-retrospective": [
        "做得好的地方",
        "需要改进的地方",
        "改进计划",
        "团队行动项",
    ],
}


def build_stage_prompt(
    stage_code: str,
    stage_name: str,
    project_name: str,
    project_description: str,
    previous_artifacts: str,
    contract_text: str = "",
) -> tuple[str, str]:
    role, instruction = STAGE_ROLE.get(
        stage_code, ("软件工程专家", "负责生成该阶段的专业工程文档。")
    )
    sections = STAGE_STRUCTURE.get(
        stage_code, ["概述", "详细设计", "补充说明"]
    )
    section_text = "\n".join(f"{index}. {section}" for index, section in enumerate(sections, start=1))
    entity_text = entity_requirement_text(stage_code)

    system = (
        f"你是一名{role}。{instruction}\n"
        "请始终使用简体中文，并输出符合软件工程规范的 Markdown 文档。"
        "不要输出解释性文字，直接输出文档正文。"
    )
    user = (
        f"项目名称：{project_name}\n"
        f"项目描述：{project_description}\n"
        f"当前阶段：{stage_name}\n\n"
        f"前置阶段产物：\n{previous_artifacts or '（无）'}\n\n"
        f"请生成《{stage_name}文档》，至少包含以下章节：\n{section_text}\n\n"
        "要求：\n"
        "1. 文档使用 Markdown 格式。\n"
        "2. 实体使用规范编号，例如需求 RQ-001、用例 UC-001、模块 MOD-001、测试用例 TC-001。\n"
        "3. 每个实体使用三级标题单独成节，例如 `### 需求条目 RQ-001`。\n"
        "4. 建立实体关联：用例标注来源需求，模块标注实现的需求或用例，"
        "测试用例标注验证的需求或模块，便于自动生成追溯矩阵。\n"
        "5. 内容必须与前置产物保持一致，不能凭空发明未出现的功能。"
    )
    if entity_text:
        user += (
            "\n6. " + entity_text
            + "\n7. 关联必须写成可直接解析的形式：在实体小节正文中显式写出被引用编号，"
            "例如用例小节内写「来源：RQ-001」，模块小节内写「实现：RQ-001、UC-001」，"
            "测试用例小节内写「验证：RQ-001、MOD-001」。"
        )
    if contract_text:
        user += "\n\n本阶段契约：\n" + contract_text
    return system, user


def build_code_stage_prompt(
    stage_code: str,
    stage_name: str,
    project_name: str,
    project_description: str,
    previous_artifacts: str,
    error_info: str = "",
) -> tuple[str, str]:
    if stage_code == "coding":
        system = (
            "你是一名开发工程师，负责根据需求与设计文档生成一个可运行的 Python FastAPI 项目。"
            "代码必须能通过语法检查和启动验证。"
            "只输出代码文件，不要输出解释性文字。"
        )
        user = (
            f"项目名称：{project_name}\n"
            f"项目描述：{project_description}\n"
            f"当前阶段：{stage_name}\n\n"
            f"前置文档：\n{previous_artifacts or '（无）'}\n\n"
            "请生成一个完整的 FastAPI 项目，包含以下文件：\n"
            "[FILE] requirements.txt\n"
            "[FILE] app/main.py\n"
            "[FILE] app/models.py\n"
            "[FILE] README.md\n"
            "[FILE] tests/test_app.py\n\n"
            "要求：\n"
            "1. 每个文件必须使用 [FILE] 路径 开头，文件内容紧跟在下一行。\n"
            "2. app/main.py 使用 FastAPI 和 SQLite，必须暴露 /health 接口。\n"
            "3. main.py 可以直接运行：python app/main.py。\n"
            "4. tests/test_app.py 使用 pytest 和 TestClient 测试 /health。\n"
            "5. requirements.txt 至少包含 fastapi、uvicorn、pytest、httpx。\n"
            "6. 禁止使用 Markdown 代码围栏，文件内容直接写在 [FILE] 行之后，不要出现 ```。\n"
            "7. 禁止使用 passlib，密码处理使用 hashlib 或 PyJWT。\n"
            "8. requirements.txt 只写包名，不写任何版本号。\n"
            "9. 测试文件路径必须是 tests/test_app.py，不能嵌套成 tests/tests/test_app.py。\n"
            "10. app/main.py 必须使用 if __name__ == \"__main__\" 才启动 uvicorn。"
        )
    elif stage_code == "prototype":
        system = (
            "你是一名原型工程师，负责根据需求快速构建一个可交互的 Python FastAPI 原型项目。"
            "原型重点验证核心交互流程，代码必须能通过语法检查和启动验证。"
            "只输出代码文件，不要输出解释性文字。"
        )
        user = (
            f"项目名称：{project_name}\n"
            f"项目描述：{project_description}\n"
            f"当前阶段：{stage_name}\n\n"
            f"前置文档：\n{previous_artifacts or '（无）'}\n\n"
            "请生成一个可交互的 FastAPI 原型项目，包含以下文件：\n"
            "[FILE] requirements.txt\n"
            "[FILE] app/main.py\n"
            "[FILE] README.md\n\n"
            "要求：\n"
            "1. 每个文件必须使用 [FILE] 路径 开头，文件内容紧跟在下一行。\n"
            "2. app/main.py 使用 FastAPI，必须暴露核心业务接口和 /health。\n"
            "3. 原型使用内存数据或 SQLite，重点验证交互流程。\n"
            "4. 禁止使用 Markdown 代码围栏，文件内容直接写在 [FILE] 行之后。\n"
            "5. requirements.txt 只写包名，不写任何版本号。\n"
            "6. app/main.py 必须使用 if __name__ == \"__main__\" 才启动 uvicorn。"
        )
    elif stage_code == "sprint-dev":
        system = (
            "你是一名开发工程师，负责按 Sprint 任务列表实现功能，生成可运行的 Python FastAPI 项目。"
            "代码必须能通过语法检查和启动验证。"
            "只输出代码文件，不要输出解释性文字。"
        )
        user = (
            f"项目名称：{project_name}\n"
            f"项目描述：{project_description}\n"
            f"当前阶段：{stage_name}\n\n"
            f"前置文档：\n{previous_artifacts or '（无）'}\n\n"
            "请生成一个完整的 FastAPI 项目，包含以下文件：\n"
            "[FILE] requirements.txt\n"
            "[FILE] app/main.py\n"
            "[FILE] app/models.py\n"
            "[FILE] README.md\n"
            "[FILE] tests/test_app.py\n\n"
            "要求：\n"
            "1. 每个文件必须使用 [FILE] 路径 开头，文件内容紧跟在下一行。\n"
            "2. app/main.py 使用 FastAPI 和 SQLite，必须暴露 /health 接口。\n"
            "3. main.py 可以直接运行：python app/main.py。\n"
            "4. tests/test_app.py 使用 pytest 和 TestClient 测试 /health。\n"
            "5. requirements.txt 至少包含 fastapi、uvicorn、pytest、httpx。\n"
            "6. 禁止使用 Markdown 代码围栏，文件内容直接写在 [FILE] 行之后，不要出现 ```。\n"
            "7. 禁止使用 passlib，密码处理使用 hashlib 或 PyJWT。\n"
            "8. requirements.txt 只写包名，不写任何版本号。\n"
            "9. 测试文件路径必须是 tests/test_app.py，不能嵌套成 tests/tests/test_app.py。\n"
            "10. app/main.py 必须使用 if __name__ == \"__main__\" 才启动 uvicorn。"
        )
    else:
        if stage_code == "unit-test":
            system = (
                "你是一名测试工程师，负责为已生成的 FastAPI 项目编写核心单元测试。"
                "只输出测试文件，不要输出解释性文字。"
            )
            file_hint = "[FILE] tests/test_core.py"
        elif stage_code == "integration-test":
            system = (
                "你是一名测试工程师，负责编写集成测试，验证模块间接口协同。"
                "只输出测试文件，不要输出解释性文字。"
            )
            file_hint = "[FILE] tests/test_integration.py"
        elif stage_code == "system-test":
            system = (
                "你是一名测试工程师，负责编写系统端到端测试，按需求验证完整业务链路。"
                "只输出测试文件，不要输出解释性文字。"
            )
            file_hint = "[FILE] tests/test_system.py"
        else:
            system = (
                "你是一名测试工程师，负责为已生成的 FastAPI 项目编写 pytest 测试。"
                "只输出测试文件，不要输出解释性文字。"
            )
            file_hint = "[FILE] tests/test_app.py"
        user = (
            f"项目名称：{project_name}\n"
            f"项目描述：{project_description}\n\n"
            f"前置文档与代码提示：\n{previous_artifacts or '（无）'}\n\n"
            "请生成测试文件：\n"
            f"{file_hint}\n"
            "[FILE] tests/conftest.py\n\n"
            "要求：\n"
            "1. 每个文件必须使用 [FILE] 路径 开头。\n"
            "2. 使用 pytest 和 fastapi.testclient.TestClient。\n"
            "3. 至少覆盖 /health 接口和项目核心接口。\n"
            "4. 禁止使用 Markdown 代码围栏，文件内容直接写在 [FILE] 行之后。\n"
            "5. 测试路径不能嵌套成 tests/tests/。\n"
            "6. 不要生成 requirements.txt 版本号，也不要修改代码目录中的源码文件。"
        )
    if error_info:
        user += f"\n\n上次验证失败信息：\n{error_info}\n请修复后完整重新输出全部文件。"
    return system, user


# ---------------------------------------------------------------------------
# 阶段直接沟通（chat 模式）：任意阶段都可与对应角色 agent 对话
# ---------------------------------------------------------------------------


def build_chat_system_prompt(stage_code: str) -> str:
    """按阶段角色生成对话系统提示词。"""
    role, instruction = STAGE_ROLE.get(
        stage_code, ("软件工程专家", "负责推进当前阶段的工程活动。")
    )
    return (
        f"你是一名{role}。{instruction}\n"
        "你正在与项目发起人逐轮沟通以确定本阶段的具体内容。"
        "每次只问 1 到 2 个关键问题，逐步收敛结论；信息足够时给出本阶段结论摘要。"
        "始终使用简体中文，不要输出 Markdown 代码围栏。"
    )


def build_chat_opening(stage_code: str, stage_name: str) -> str:
    """阶段进入 chat 模式时 agent 的开场白。"""
    role, _ = STAGE_ROLE.get(stage_code, ("软件工程专家", ""))
    return (
        f"你好，我是本项目的{role}，负责「{stage_name}」阶段。"
        "请说明本阶段你期望达成的目标与关键约束，我会据此逐步与你确认。"
    )


def build_confirm_prompt(
    stage_code: str,
    stage_name: str,
    project_name: str,
    project_description: str,
    previous_artifacts: str,
    transcript: str,
) -> tuple[str, str]:
    """把某个阶段的对话记录整理成该阶段的正式文档。"""
    role, instruction = STAGE_ROLE.get(
        stage_code, ("软件工程专家", "负责生成该阶段的专业工程文档。")
    )
    sections = STAGE_STRUCTURE.get(stage_code, ["概述", "详细设计", "补充说明"])
    section_text = "\n".join(
        f"{index}. {section}" for index, section in enumerate(sections, start=1)
    )
    system = (
        f"你是一名{role}。{instruction}\n"
        "请把与用户的沟通结论整理成规范 Markdown 文档，"
        "始终使用简体中文，直接输出文档正文，不要输出解释性文字。"
    )
    user = (
        f"项目名称：{project_name}\n"
        f"项目描述：{project_description}\n"
        f"当前阶段：{stage_name}\n\n"
        f"前置阶段产物：\n{previous_artifacts or '（无）'}\n\n"
        f"与用户的沟通记录：\n{transcript or '（无）'}\n\n"
        f"请生成《{stage_name}文档》，至少包含以下章节：\n{section_text}\n\n"
        "要求：\n"
        "1. 内容只能来自沟通记录、前置产物与项目信息，不能凭空发明。\n"
        "2. 实体使用规范编号：需求 RQ-001、用例 UC-001、模块 MOD-001、测试用例 TC-001。\n"
        "3. 每个实体使用三级标题单独成节，例如 `### 需求条目 RQ-001`。\n"
        "4. 明确标注实体关联关系，便于自动生成追溯矩阵。"
    )
    return system, user


# ---------------------------------------------------------------------------
# 评审 Agent：对阶段产物做检查清单与一致性审查
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = (
    "你是一名评审 Agent，负责对阶段产物进行质量与一致性审查。"
    "请严格依据检查清单逐项核对，指出缺失、含糊或与前置产物冲突之处。"
    "始终使用简体中文，输出简洁的 Markdown 清单，不要输出代码围栏。"
)

# 各阶段评审检查清单（评审 Agent 的自检依据）。
REVIEW_CHECKLISTS: dict[str, list[str]] = {
    "requirements": [
        "是否覆盖项目目标、用户角色、功能与非功能需求、约束与验收标准",
        "需求条目是否使用 RQ-001 连续编号且描述可验证",
        "每个需求是否至少关联一个用例 UC-00X",
        "是否存在与项目描述冲突或凭空新增的功能",
    ],
    "architecture": [
        "是否给出系统架构、技术选型、模块划分与部署视图",
        "模块是否使用 MOD-001 编号并说明其实现的需求或用例",
        "是否覆盖全部需求，无遗漏关键模块",
        "技术选型是否与约束条件一致",
    ],
    "detailed-design": [
        "是否包含类设计、数据库设计、接口定义与关键流程",
        "接口与数据表是否可追溯到模块",
        "字段、类型与约束是否明确",
        "是否与概要设计保持一致",
    ],
    "testing": [
        "是否包含测试策略、测试计划、测试用例与报告模板",
        "测试用例是否使用 TC-001 编号并标注验证的需求或模块",
        "需求是否被测试用例覆盖，是否存在无对应需求的用例",
        "是否包含边界与异常场景",
    ],
    "risk-analysis": [
        "是否识别技术、资源与进度风险",
        "是否给出量化评估与缓解策略",
        "是否有风险监控计划",
    ],
    "evaluation": [
        "是否对照验收标准逐项评估",
        "是否给出下一步建议",
    ],
    "iteration-review": [
        "是否回顾迭代目标并核对验收标准",
        "是否给出下一迭代规划",
    ],
    "prototype": [
        "原型是否覆盖核心交互流程",
        "是否说明技术实现方案与演示方式",
    ],
    "user-feedback": [
        "是否分类整理用户反馈并给出优先级",
    ],
    "refinement": [
        "是否记录需求变更并分析影响",
        "验收标准是否同步更新",
    ],
    "backlog": [
        "用户故事是否按优先级排序并估算工作量",
    ],
    "sprint-planning": [
        "Sprint 目标是否明确，任务是否拆分到可执行粒度",
    ],
    "sprint-review": [
        "是否记录演示内容与利益相关者反馈",
    ],
    "sprint-retrospective": [
        "是否给出改进计划与团队行动项",
    ],
}

_DEFAULT_CHECKLIST = ["结构是否完整", "内容是否与前置产物一致", "是否存在含糊或缺失章节"]


def build_review_prompt(
    stage_code: str,
    stage_name: str,
    content: str,
    traceability_summary: str = "",
) -> tuple[str, str]:
    checklist_text = build_checklist_instruction(stage_code)
    user = (
        f"阶段：{stage_name}\n\n"
        f"待评审产物（Markdown）：\n{content or '（空）'}\n\n"
        f"追溯矩阵摘要：{traceability_summary or '（暂无）'}\n\n"
        f"检查清单：\n{checklist_text}\n\n"
        "请按以下结构输出（不要输出代码围栏）：\n"
        "## 评审结论\n"
        "通过 / 需修改\n\n"
        "## 检查清单核对\n"
        "逐项列出，格式严格为：- [检查项 id] 通过/不通过/不适用 —— 原因\n\n"
        "## 修改建议\n"
        "列出具体可执行的修改点；若无需修改则写“无”。"
    )
    return REVIEW_SYSTEM_PROMPT, user
