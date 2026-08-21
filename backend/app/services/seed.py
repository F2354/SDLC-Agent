from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_role import AgentRole
from app.models.process_model import ProcessModel, Stage

WATERFALL_STAGES = [
    (
        "requirements",
        "需求分析",
        "与用户访谈收集需求，输出需求确认清单与需求规格说明书。",
    ),
    ("architecture", "概要设计", "设计系统架构、模块划分与接口边界。"),
    ("detailed-design", "详细设计", "设计类结构、数据库表结构与接口定义。"),
    ("coding", "编码骨架", "生成代码目录骨架、核心模块示例与数据库 DDL。"),
    ("testing", "测试计划与用例", "输出测试计划、测试用例与测试报告模板。"),
]

AGENT_ROLES = [
    ("coordinator", "统筹协调", "自动模式下调度阶段 agent 并汇总上下文。"),
    ("requirements_analyst", "需求分析师", "访谈用户并整理需求文档。"),
    ("architect", "架构师", "负责概要设计与系统架构。"),
    ("designer", "设计工程师", "负责详细设计与数据库设计。"),
    ("developer", "开发工程师", "负责代码骨架与 DDL 生成。"),
    ("tester", "测试工程师", "负责测试计划与测试用例。"),
    ("reviewer", "评审", "检查制品完整性与一致性。"),
]


def seed_waterfall(db: Session) -> ProcessModel:
    model = db.scalar(select(ProcessModel).where(ProcessModel.code == "waterfall"))
    if model is not None:
        return model

    model = ProcessModel(
        code="waterfall",
        name="瀑布模型",
        description="按需求、概要设计、详细设计、编码、测试顺序串行执行的过程模型。",
        version="1.0",
        enabled=True,
    )
    db.add(model)
    db.flush()

    for seq, (code, name, description) in enumerate(WATERFALL_STAGES, start=1):
        db.add(
            Stage(
                process_model_id=model.id,
                seq=seq,
                code=code,
                name=name,
                description=description,
            )
        )

    db.commit()
    db.refresh(model)
    return model


def seed_agent_roles(db: Session) -> None:
    for code, name, description in AGENT_ROLES:
        if db.scalar(select(AgentRole).where(AgentRole.code == code)) is None:
            db.add(AgentRole(code=code, name=name, description=description))
    db.commit()


def seed_all(db: Session) -> None:
    seed_agent_roles(db)
    seed_waterfall(db)
