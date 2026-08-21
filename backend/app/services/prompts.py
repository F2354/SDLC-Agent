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
}

STAGE_STRUCTURE = {
    "requirements": [
        "项目概述",
        "用户角色",
        "功能需求（需求条目 RQ-001）",
        "非功能需求",
        "约束条件",
        "验收标准",
        "风险分析",
    ],
    "architecture": [
        "系统架构",
        "技术选型",
        "模块划分（模块 MOD-001）",
        "数据流设计",
        "部署视图",
    ],
    "detailed-design": [
        "类设计",
        "数据库设计",
        "接口定义",
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
        "测试用例（测试用例 TC-001）",
        "测试报告模板",
    ],
}


def build_stage_prompt(
    stage_code: str,
    stage_name: str,
    project_name: str,
    project_description: str,
    previous_artifacts: str,
) -> tuple[str, str]:
    role, instruction = STAGE_ROLE.get(
        stage_code, ("软件工程专家", "负责生成该阶段的专业工程文档。")
    )
    sections = STAGE_STRUCTURE.get(
        stage_code, ["概述", "详细设计", "补充说明"]
    )
    section_text = "\n".join(f"{index}. {section}" for index, section in enumerate(sections, start=1))

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
        "2. 实体使用规范编号，例如需求 RQ-001、模块 MOD-001、测试用例 TC-001。\n"
        "3. 内容必须与前置产物保持一致，不能凭空发明未出现的功能。"
    )
    return system, user
