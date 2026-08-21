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
