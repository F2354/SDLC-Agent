import threading
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.llm_provider import LLMProvider
from app.models.process_model import Stage
from app.models.project import Project
from app.models.stage_run import (
    ActivityEvent,
    Artifact,
    ArtifactVersion,
    Message,
    Review,
    StageRun,
)
from app.schemas.stage import ArtifactOut, MessageOut, StageRunOut
from app.services.llm_service import build_openai_client
from app.services.prompts import build_code_stage_prompt, build_stage_prompt
from app.services.code_service import (
    list_code_files,
    run_tests,
    run_verify,
    write_files,
)
from app.services.coding_agent import run_coding_harness


REQUIREMENTS_SYSTEM_PROMPT = (
    "你是一名需求分析师，负责通过对话收集软件需求。"
    "每次只问 1 到 2 个关键问题，逐步覆盖项目目标、用户角色、核心功能、"
    "非功能需求、约束与验收标准。信息足够时输出一份简短的需求确认清单。"
    "始终使用简体中文。"
)

INITIAL_INTERVIEW_MESSAGE = (
    "你好，我是需求分析师。请先介绍项目目标、主要使用者和要解决的核心问题。"
)


class AgentState(TypedDict):
    project_id: int
    stage_run_id: int
    stage_code: str
    stage_name: str
    project_name: str
    project_description: str
    previous_artifacts: str
    output: str


def build_stage_graph(provider: LLMProvider, db: Session, state: AgentState):
    def load_context_node(current: AgentState) -> dict:
        return current

    def generate_node(current: AgentState) -> dict:
        system, user = build_stage_prompt(
            stage_code=current["stage_code"],
            stage_name=current["stage_name"],
            project_name=current["project_name"],
            project_description=current["project_description"],
            previous_artifacts=current["previous_artifacts"],
        )
        client = build_openai_client(provider)
        completion = client.chat.completions.create(
            model=provider.default_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        content = completion.choices[0].message.content or ""
        return {"output": content}

    def save_node(current: AgentState) -> dict:
        run = db.get(StageRun, current["stage_run_id"])
        if run is None:
            raise ValueError("阶段运行记录不存在")
        artifact = Artifact(
            project_id=current["project_id"],
            stage_run_id=run.id,
            type=current["stage_code"],
            title=f"{current['stage_name']}文档",
            content_md=current["output"],
            status="awaiting_review",
        )
        db.add(artifact)
        db.flush()
        db.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version_no=1,
                content_md=current["output"],
            )
        )
        run.status = "awaiting_review"
        run.finished_at = datetime.now()
        db.add(
            ActivityEvent(
                project_id=current["project_id"],
                stage_run_id=run.id,
                event_type="artifact_saved",
                message=f"{current['stage_name']}产物已生成",
            )
        )
        db.commit()
        return current

    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context_node)
    graph.add_node("generate", generate_node)
    graph.add_node("save", save_node)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "generate")
    graph.add_edge("generate", "save")
    graph.add_edge("save", END)
    return graph.compile()


def _invoke_llm(
    provider: LLMProvider,
    system: str,
    user: str,
    max_tokens: int = 1500,
) -> str:
    client = build_openai_client(provider)
    completion = client.chat.completions.create(
        model=provider.default_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=max_tokens,
    )
    return completion.choices[0].message.content or ""


def execute_code_stage(
    stage: Stage,
    project: Project,
    run: StageRun,
    provider: LLMProvider,
    db: Session,
) -> None:
    if stage.code == "coding":
        execute_coding_harness_stage(stage, project, run, provider, db)
        return

    run.status = "generating"
    run.started_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=run.id,
            event_type="agent_started",
            message=f"{stage.name}已开始生成代码文件",
        )
    )
    db.commit()

    previous_rows = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.id)
        )
    )
    previous_artifacts = "\n\n".join(
        f"### {row.title}\n{row.content_md}" for row in previous_rows
    )

    max_attempts = 3 if stage.code == "coding" else 2
    error_info = ""
    content = ""
    result = None
    for attempt in range(1, max_attempts + 1):
        system, user = build_code_stage_prompt(
            stage_code=stage.code,
            stage_name=stage.name,
            project_name=project.name,
            project_description=project.description,
            previous_artifacts=previous_artifacts,
            error_info=error_info,
        )
        content = _invoke_llm(
            provider,
            system,
            user,
            max_tokens=5000 if stage.code == "coding" else 2500,
        )
        target = "code" if stage.code == "coding" else "tests"
        try:
            written = write_files(project.id, content, target)
        except ValueError as exc:
            error_info = str(exc)
            if attempt == max_attempts:
                raise
            continue
        result = run_verify(project.id) if stage.code == "coding" else run_tests(project.id)
        if result.ok:
            break
        error_info = result.output[:2000]

    artifact = Artifact(
        project_id=project.id,
        stage_run_id=run.id,
        type=stage.code,
        title=f"{stage.name}与验证结果",
        content_md=(
            f"# {stage.name}\n\n"
            f"{content}\n\n"
            f"## 验证结果\n\n{result.model_dump_json(indent=2) if result else '未生成验证结果'}"
        ),
        status="awaiting_review",
    )
    db.add(artifact)
    db.flush()
    db.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_no=1,
            content_md=artifact.content_md,
        )
    )
    run.status = "awaiting_review"
    run.finished_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=run.id,
            event_type="artifact_saved",
            message=f"{stage.name}产物与运行验证结果已生成",
        )
    )
    db.commit()


def execute_coding_harness_stage(
    stage: Stage,
    project: Project,
    run: StageRun,
    provider: LLMProvider,
    db: Session,
) -> None:
    run.status = "generating"
    run.started_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=run.id,
            event_type="agent_started",
            message=f"{stage.name}已开始工具化编码",
        )
    )
    db.commit()

    previous_rows = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.id)
        )
    )
    previous_artifacts = "\n\n".join(
        f"### {row.title}\n{row.content_md}" for row in previous_rows
    )

    result = run_coding_harness(
        project_id=project.id,
        provider=provider,
        project_name=project.name,
        project_description=project.description,
        previous_artifacts=previous_artifacts,
        max_turns=8,
    )
    tree = list_code_files(project.id)
    files_md = "\n".join(f"- {item.path}" for item in tree.files)
    verify_md = result.verify.output if result.verify else "无运行结果"
    tests_md = result.tests.output if result.tests else "无测试结果"
    content_md = (
        f"# 编码产物\n\n"
        f"生成文件：\n{files_md or '（无）'}\n\n"
        f"## 运行验证\n\n{verify_md}\n\n"
        f"## 测试结果\n\n{tests_md}\n\n"
        f"最终状态：{'通过' if result.ok else '未完全通过'}，共 {result.turn_count} 轮工具调用。"
    )

    artifact = Artifact(
        project_id=project.id,
        stage_run_id=run.id,
        type=stage.code,
        title=f"{stage.name}与验证结果",
        content_md=content_md,
        status="awaiting_review",
    )
    db.add(artifact)
    db.flush()
    db.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_no=1,
            content_md=content_md,
        )
    )
    run.status = "awaiting_review"
    run.finished_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=run.id,
            event_type="artifact_saved",
            message=f"{stage.name}工具化编码与验证结果已生成",
        )
    )
    db.commit()


def execute_stage_run(stage_run_id: int) -> None:
    with SessionLocal() as db:
        run = db.get(StageRun, stage_run_id)
        if run is None:
            return
        try:
            stage = db.get(Stage, run.stage_id)
            project = db.get(Project, run.project_id)
            provider = db.get(LLMProvider, run.provider_id)
            if stage is None or project is None:
                raise ValueError("阶段或项目不存在")
            if provider is None or not provider.enabled:
                raise ValueError("请先配置可用的模型 Provider")

            if stage.code in ("coding", "testing"):
                execute_code_stage(stage, project, run, provider, db)
                return

            run.status = "generating"
            run.started_at = datetime.now()
            db.add(
                ActivityEvent(
                    project_id=project.id,
                    stage_run_id=run.id,
                    event_type="agent_started",
                    message=f"{stage.name}阶段已开始",
                )
            )
            db.commit()

            previous_rows = list(
                db.scalars(
                    select(Artifact)
                    .where(Artifact.project_id == project.id)
                    .order_by(Artifact.id)
                )
            )
            previous_artifacts = "\n\n".join(
                f"### {row.title}\n{row.content_md}" for row in previous_rows
            )

            state: AgentState = {
                "project_id": project.id,
                "stage_run_id": run.id,
                "stage_code": stage.code,
                "stage_name": stage.name,
                "project_name": project.name,
                "project_description": project.description,
                "previous_artifacts": previous_artifacts,
                "output": "",
            }
            graph = build_stage_graph(provider, db, state)
            graph.invoke(state)
        except Exception as exc:
            run = db.get(StageRun, stage_run_id)
            run.status = "failed"
            run.error = str(exc)[:2000]
            run.finished_at = datetime.now()
            db.add(
                ActivityEvent(
                    project_id=run.project_id,
                    stage_run_id=run.id,
                    event_type="agent_failed",
                    message=str(exc)[:500],
                )
            )
            db.commit()


def start_stage_run_async(
    stage_run_id: int,
) -> None:
    threading.Thread(
        target=execute_stage_run,
        args=(stage_run_id,),
        daemon=True,
    ).start()


def serialize_stage_run(run: StageRun, db: Session) -> StageRunOut:
    stage = db.get(Stage, run.stage_id)
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.stage_run_id == run.id)
            .order_by(Artifact.id)
        )
    )
    return StageRunOut(
        id=run.id,
        project_id=run.project_id,
        stage_id=run.stage_id,
        stage_code=stage.code if stage else "",
        stage_name=stage.name if stage else "",
        provider_id=run.provider_id,
        status=run.status,
        mode=run.mode,
        error=run.error,
        artifacts=[ArtifactOut.model_validate(artifact) for artifact in artifacts],
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _get_runnable_provider(run: StageRun, db: Session) -> LLMProvider:
    provider = db.get(LLMProvider, run.provider_id)
    if provider is None or not provider.enabled:
        raise ValueError("请先配置可用的模型 Provider")
    return provider


def _build_interview_messages(
    db: Session,
    run: StageRun,
    system_prompt: str = REQUIREMENTS_SYSTEM_PROMPT,
) -> list[dict[str, str]]:
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.stage_run_id == run.id)
            .order_by(Message.id)
        )
    )
    messages = [{"role": "system", "content": system_prompt}]
    for row in rows:
        role = "user" if row.role == "user" else "assistant"
        messages.append({"role": role, "content": row.content})
    return messages


def send_interview_reply(run: StageRun, db: Session) -> Message:
    if run.status != "collecting":
        raise ValueError("当前阶段不在访谈状态")
    provider = _get_runnable_provider(run, db)
    client = build_openai_client(provider)
    completion = client.chat.completions.create(
        model=provider.default_model,
        messages=_build_interview_messages(db, run),
        temperature=0.4,
        max_tokens=900,
    )
    reply = completion.choices[0].message.content or "请继续补充项目信息。"
    message = Message(
        project_id=run.project_id,
        stage_run_id=run.id,
        role="agent",
        agent_code="requirements_analyst",
        content=reply,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def confirm_requirements(run: StageRun, db: Session) -> StageRun:
    if run.status != "collecting":
        raise ValueError("当前阶段不在访谈状态")
    project = db.get(Project, run.project_id)
    provider = _get_runnable_provider(run, db)

    transcript_rows = list(
        db.scalars(
            select(Message)
            .where(Message.stage_run_id == run.id)
            .order_by(Message.id)
        )
    )
    transcript = "\n".join(
        f"{'用户' if row.role == 'user' else '需求分析师'}: {row.content}"
        for row in transcript_rows
    )
    user_prompt = (
        f"项目名称：{project.name}\n"
        f"项目描述：{project.description}\n\n"
        f"以下是与用户的需求访谈记录：\n{transcript}\n\n"
        "请生成《软件需求规格说明书》Markdown 文档，必须包含："
        "项目概述、用户角色、需求确认清单、功能需求（RQ-001 等编号）、"
        "非功能需求、约束条件、验收标准、风险分析。"
        "内容只能来自访谈记录和项目信息，不能凭空增加功能。"
    )
    client = build_openai_client(provider)
    completion = client.chat.completions.create(
        model=provider.default_model,
        messages=[
            {
                "role": "system",
                "content": "你是一名需求分析师，负责把访谈内容整理成规范的需求规格说明书。",
            },
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    content = completion.choices[0].message.content or ""

    run.status = "generating"
    db.commit()

    artifact = Artifact(
        project_id=run.project_id,
        stage_run_id=run.id,
        type="requirements",
        title="软件需求规格说明书",
        content_md=content,
        status="awaiting_review",
    )
    db.add(artifact)
    db.flush()
    db.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_no=1,
            content_md=content,
        )
    )
    run.status = "awaiting_review"
    run.finished_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=run.project_id,
            stage_run_id=run.id,
            event_type="artifact_saved",
            message="需求确认完成，需求规格说明书已生成",
        )
    )
    db.commit()
    return run


def review_stage_run(
    run: StageRun,
    db: Session,
    result: str,
    comment: str = "",
) -> StageRun:
    if run.status != "awaiting_review":
        raise ValueError("当前阶段不在待评审状态")
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.stage_run_id == run.id)
            .order_by(Artifact.id)
        )
    )
    for artifact in artifacts:
        artifact.status = result
    db.add(
        Review(
            stage_run_id=run.id,
            artifact_id=artifacts[0].id if artifacts else None,
            reviewer_type="user",
            result=result,
            comment=comment,
        )
    )
    run.status = result
    run.finished_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=run.project_id,
            stage_run_id=run.id,
            event_type=f"review_{result}",
            message=f"阶段评审{('通过' if result == 'approved' else '打回')}",
        )
    )
    db.commit()
    return run


def serialize_message(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)
