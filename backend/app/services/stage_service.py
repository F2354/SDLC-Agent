import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
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
from app.services.event_bus import publish
from app.services.llm_service import build_openai_client
from app.services.prompts import (
    build_chat_opening,
    build_chat_system_prompt,
    build_code_stage_prompt,
    build_confirm_prompt,
    build_review_prompt,
    build_stage_prompt,
)
from app.services.code_service import (
    list_code_files,
    run_stage_tests,
    run_verify,
    write_files,
)
from app.services.coding_agent import run_coding_harness
from app.services.artifact_file import write_artifact_file
from app.services.traceability import rebuild_traceability

logger = logging.getLogger("uvicorn.error")

# 有界线程池：避免每个阶段启动一个裸线程导致资源无上限增长。
_MAX_CONCURRENT_STAGE_RUNS = 4
_stage_executor = ThreadPoolExecutor(
    max_workers=_MAX_CONCURRENT_STAGE_RUNS, thread_name_prefix="stage-run"
)
_executor_closed = False


def shutdown_stage_executor(wait: bool = False) -> None:
    """关闭阶段运行线程池（应用退出时调用）。"""
    global _executor_closed
    if _executor_closed:
        return
    _executor_closed = True
    _stage_executor.shutdown(wait=wait, cancel_futures=False)


atexit.register(shutdown_stage_executor)


# 需求阶段对话系统提示词（供聊天接口默认使用）。
REQUIREMENTS_SYSTEM_PROMPT = build_chat_system_prompt("requirements")

INITIAL_INTERVIEW_MESSAGE = (
    "你好，我是需求分析师。请先介绍项目目标、主要使用者和要解决的核心问题。"
)

# 需要真实写盘并运行验证的阶段：这些阶段固定走自动工具循环。
CODE_STAGE_CODES = frozenset(
    {
        "coding",
        "testing",
        "unit-test",
        "integration-test",
        "system-test",
        "prototype",
        "sprint-dev",
    }
)


def is_code_stage(stage_code: str) -> bool:
    return stage_code in CODE_STAGE_CODES


# 阶段 → 对话使用的 agent 角色编码（与 seed.AGENT_ROLES 对应）。
STAGE_AGENT_CODE: dict[str, str] = {
    "requirements": "requirements_analyst",
    "architecture": "architect",
    "detailed-design": "designer",
    "coding": "developer",
    "testing": "tester",
    "unit-test": "tester",
    "integration-test": "tester",
    "system-test": "tester",
    "risk-analysis": "architect",
    "evaluation": "reviewer",
    "iteration-review": "reviewer",
    "prototype": "developer",
    "user-feedback": "requirements_analyst",
    "refinement": "requirements_analyst",
    "backlog": "coordinator",
    "sprint-planning": "coordinator",
    "sprint-dev": "developer",
    "sprint-review": "coordinator",
    "sprint-retrospective": "coordinator",
}

# 文档保存前的必需内容关键词（与 prompts.STAGE_STRUCTURE 呼应）。
_STAGE_REQUIRED_HINTS: dict[str, tuple[str, ...]] = {
    "requirements": ("需求", "验收"),
    "architecture": ("架构", "模块"),
    "detailed-design": ("设计", "接口"),
    "risk-analysis": ("风险",),
    "evaluation": ("评估", "验收"),
    "iteration-review": ("迭代", "验收"),
    "user-feedback": ("反馈",),
    "refinement": ("需求",),
    "backlog": ("用户故事", "优先"),
    "sprint-planning": ("任务",),
    "sprint-review": ("演示", "反馈"),
    "sprint-retrospective": ("改进",),
}

# 文档最小长度：低于该值直接判定生成不达标并触发重试。
_MIN_DOC_CHARS = 300
_MAX_DOC_ATTEMPTS = 3


class AgentState(TypedDict):
    project_id: int
    stage_run_id: int
    stage_code: str
    stage_name: str
    project_name: str
    project_description: str
    previous_artifacts: str
    output: str
    error_info: str
    attempts: int
    max_attempts: int
    needs_retry: bool
    should_review: bool
    artifact_id: int
    traceability_summary: str


def validate_document(stage_code: str, content: str) -> str:
    """校验生成文档的完整性。返回空字符串表示通过，否则返回不合格原因。"""
    text = (content or "").strip()
    if len(text) < _MIN_DOC_CHARS:
        return f"文档内容过短（仅 {len(text)} 字符），请补全全部章节后重新输出完整文档。"
    missing = [hint for hint in _STAGE_REQUIRED_HINTS.get(stage_code, ()) if hint not in text]
    if missing:
        return "文档缺少关键内容：" + "、".join(missing) + "。请补齐后重新输出完整文档。"
    return ""


def build_stage_graph(provider: LLMProvider, db: Session, state: AgentState):  # noqa: ARG001
    """文档类阶段执行图（真正的条件分支）。

    load_context → generate → check_quality ─┬─(不达标)→ generate
                                             └─(达标)──→ save
    save →(是否评审)→ suggest_review → END
    """

    def load_context_node(current: AgentState) -> dict:
        return current

    def generate_node(current: AgentState) -> dict:
        attempt = current.get("attempts", 0) + 1
        system, user = build_stage_prompt(
            stage_code=current["stage_code"],
            stage_name=current["stage_name"],
            project_name=current["project_name"],
            project_description=current["project_description"],
            previous_artifacts=current["previous_artifacts"],
        )
        if current.get("error_info"):
            user += (
                f"\n\n上次输出未通过校验：\n{current['error_info']}\n"
                "请修正后完整重新输出全部章节。"
            )
        content = _invoke_llm(provider, system, user, max_tokens=2000)
        return {"output": content, "attempts": attempt}

    def check_quality_node(current: AgentState) -> dict:
        reason = validate_document(current["stage_code"], current.get("output", ""))
        can_retry = bool(reason) and current.get("attempts", 0) < current.get(
            "max_attempts", _MAX_DOC_ATTEMPTS
        )
        if reason and not can_retry:
            logger.warning(
                "阶段文档多次校验未通过，按当前内容保存: %s", current["stage_code"]
            )
        return {"needs_retry": can_retry, "error_info": reason}

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
        try:
            rebuild_traceability(db, current["project_id"])
        except Exception:  # noqa: BLE001
            logger.exception("重建追溯关系失败")
            db.rollback()
        try:
            write_artifact_file(current["project_id"], artifact)
        except Exception:  # noqa: BLE001
            logger.exception("文档产物写文件失败")
        publish(
            current["project_id"],
            "artifact_saved",
            {
                "stage_run_id": run.id,
                "artifact_id": artifact.id,
                "version": artifact.current_version,
                "title": artifact.title,
            },
        )
        return {"artifact_id": artifact.id}

    def suggest_review_node(current: AgentState) -> dict:
        """评审 Agent：对产物做检查清单与一致性审查，产出建议但不阻断人工评审。"""
        run = db.get(StageRun, current["stage_run_id"])
        if run is None:
            return {}
        system, user = build_review_prompt(
            stage_code=current["stage_code"],
            stage_name=current["stage_name"],
            content=current.get("output", ""),
            traceability_summary=current.get("traceability_summary", ""),
        )
        try:
            suggestion = _invoke_llm(provider, system, user, max_tokens=1200)
        except Exception as exc:  # noqa: BLE001
            logger.exception("评审 Agent 执行失败: stage_run_id=%s", run.id)
            suggestion = f"评审 Agent 执行失败：{exc}"
        if not suggestion.strip():
            suggestion = "评审 Agent 未返回内容。"
        db.add(
            Review(
                stage_run_id=run.id,
                artifact_id=current.get("artifact_id"),
                reviewer_type="agent",
                result="suggested",
                comment=suggestion,
            )
        )
        db.add(
            ActivityEvent(
                project_id=current["project_id"],
                stage_run_id=run.id,
                event_type="review_suggested",
                message=f"评审 Agent 已给出{current['stage_name']}审查建议",
            )
        )
        db.commit()
        publish(
            current["project_id"],
            "review_suggested",
            {"stage_run_id": run.id, "comment": suggestion[:2000]},
        )
        return {}

    def route_quality(current: AgentState) -> str:
        return "generate" if current.get("needs_retry") else "save"

    def route_review(current: AgentState) -> str:
        return "suggest_review" if current.get("should_review") else "end"

    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context_node)
    graph.add_node("generate", generate_node)
    graph.add_node("check_quality", check_quality_node)
    graph.add_node("save", save_node)
    graph.add_node("suggest_review", suggest_review_node)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "generate")
    graph.add_edge("generate", "check_quality")
    graph.add_conditional_edges(
        "check_quality",
        route_quality,
        {"generate": "generate", "save": "save"},
    )
    graph.add_conditional_edges(
        "save",
        route_review,
        {"suggest_review": "suggest_review", "end": END},
    )
    graph.add_edge("suggest_review", END)
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


def _stream_llm(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    on_delta,
    temperature: float = 0.4,
    max_tokens: int = 900,
) -> str:
    """流式调用 LLM；通过 on_delta 回调逐段推送，返回完整文本。

    若 Provider 不支持流式，则回退到一次性调用，保证功能可用。
    """
    client = build_openai_client(provider)
    chunks: list[str] = []
    try:
        stream = client.chat.completions.create(
            model=provider.default_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                chunks.append(piece)
                on_delta(piece)
        return "".join(chunks)
    except Exception:  # noqa: BLE001
        logger.warning("流式调用失败，回退为非流式", exc_info=True)
    completion = client.chat.completions.create(
        model=provider.default_model,
        messages=messages,
        temperature=temperature,
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
    publish(
        project.id,
        "stage_status",
        {"stage_run_id": run.id, "stage_code": stage.code, "status": "generating"},
    )
    publish(
        project.id,
        "agent_started",
        {"stage_run_id": run.id, "agent_code": stage.code, "message": stage.name},
    )

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
        result = run_verify(project.id) if stage.code == "coding" else run_stage_tests(project.id, stage_code=stage.code)
        if result.ok:
            break
        error_info = result.output[:2000]

    verified_ok = result is not None and result.ok
    artifact_status = "awaiting_review" if verified_ok else "verification_failed"
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
        status=artifact_status,
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
            event_type="artifact_saved" if verified_ok else "verification_failed",
            message=f"{stage.name}产物与运行验证结果已生成" if verified_ok else f"{stage.name}验证未通过",
        )
    )
    db.commit()
    try:
        rebuild_traceability(db, project.id)
    except Exception:  # noqa: BLE001
        logger.exception("重建追溯关系失败")
        db.rollback()
    try:
        write_artifact_file(project.id, artifact)
    except Exception:  # noqa: BLE001
        logger.exception("文档产物写文件失败")
    publish(
        project.id,
        "artifact_saved",
        {
            "stage_run_id": run.id,
            "artifact_id": artifact.id,
            "version": artifact.current_version,
            "title": artifact.title,
        },
    )
    publish(
        project.id,
        "stage_status",
        {"stage_run_id": run.id, "stage_code": stage.code, "status": "awaiting_review"},
    )


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
    publish(
        project.id,
        "stage_status",
        {"stage_run_id": run.id, "stage_code": stage.code, "status": "generating"},
    )
    publish(
        project.id,
        "agent_started",
        {"stage_run_id": run.id, "agent_code": stage.code, "message": stage.name},
    )

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
        status="awaiting_review" if result.ok else "verification_failed",
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
    run.status = "awaiting_review" if result.ok else "verification_failed"
    run.finished_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=run.id,
            event_type="artifact_saved" if result.ok else "verification_failed",
            message=f"{stage.name}工具化编码与验证结果已生成" if result.ok else f"{stage.name}验证未通过",
        )
    )
    db.commit()
    try:
        rebuild_traceability(db, project.id)
    except Exception:  # noqa: BLE001
        logger.exception("重建追溯关系失败")
        db.rollback()
    try:
        write_artifact_file(project.id, artifact)
    except Exception:  # noqa: BLE001
        logger.exception("文档产物写文件失败")
    publish(
        project.id,
        "artifact_saved",
        {
            "stage_run_id": run.id,
            "artifact_id": artifact.id,
            "version": artifact.current_version,
            "title": artifact.title,
        },
    )
    publish(
        project.id,
        "stage_status",
        {
            "stage_run_id": run.id,
            "stage_code": stage.code,
            "status": "awaiting_review" if result.ok else "verification_failed",
        },
    )


def _friendly_stage_error(exc: Exception, model_name: str | None) -> str:
    """把 LLM/执行异常翻译成用户可读的中文提示。"""
    raw = str(exc) or exc.__class__.__name__
    lowered = raw.lower()
    if "auth" in lowered or "api_key" in lowered or "401" in lowered:
        return f"API 认证失败，请检查 Provider 的 API Key 是否正确：{raw[:500]}"
    if "timeout" in lowered or "timed out" in lowered:
        return f"LLM 调用超时，请检查网络连接或稍后重试：{raw[:500]}"
    if "rate" in lowered or "429" in lowered:
        return f"请求频率超限，请稍后重试：{raw[:500]}"
    if "model" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return f"模型 {model_name or ''} 不存在或不可用，请检查 Provider 配置：{raw[:500]}"
    return raw[:2000]


def execute_stage_run(stage_run_id: int) -> None:
    with SessionLocal() as db:
        run = db.get(StageRun, stage_run_id)
        if run is None:
            return
        model_name: str | None = None
        try:
            stage = db.get(Stage, run.stage_id)
            project = db.get(Project, run.project_id)
            provider = db.get(LLMProvider, run.provider_id)
            model_name = provider.default_model if provider is not None else None
            if stage is None or project is None:
                raise ValueError("阶段或项目不存在")
            if provider is None or not provider.enabled:
                raise ValueError("请先配置可用的模型 Provider")

            if is_code_stage(stage.code):
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
            publish(
                project.id,
                "stage_status",
                {"stage_run_id": run.id, "stage_code": stage.code, "status": "generating"},
            )
            publish(
                project.id,
                "agent_started",
                {"stage_run_id": run.id, "agent_code": stage.code, "message": stage.name},
            )

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
                "error_info": "",
                "attempts": 0,
                "max_attempts": _MAX_DOC_ATTEMPTS,
                "needs_retry": False,
                "should_review": True,
                "artifact_id": 0,
                "traceability_summary": "",
            }
            graph = build_stage_graph(provider, db, state)
            graph.invoke(state)
            publish(
                project.id,
                "review_opened",
                {"stage_run_id": run.id, "stage_code": stage.code},
            )
        except Exception as exc:
            logger.exception("阶段运行失败: stage_run_id=%s", stage_run_id)
            # 先回滚，避免脏会话导致后续写入再次失败。
            db.rollback()
            try:
                failed_run = db.get(StageRun, stage_run_id)
                if failed_run is None:
                    return
                error_msg = _friendly_stage_error(exc, model_name)
                failed_run.status = "failed"
                failed_run.error = error_msg[:2000]
                failed_run.finished_at = datetime.now()
                db.add(
                    ActivityEvent(
                        project_id=failed_run.project_id,
                        stage_run_id=failed_run.id,
                        event_type="agent_failed",
                        message=error_msg[:500],
                    )
                )
                db.commit()
                publish(
                    failed_run.project_id,
                    "error",
                    {
                        "stage_run_id": failed_run.id,
                        "message": error_msg[:500],
                    },
                )
                publish(
                    failed_run.project_id,
                    "stage_status",
                    {"stage_run_id": failed_run.id, "status": "failed"},
                )
            except Exception:
                logger.exception(
                    "记录阶段失败状态时出错: stage_run_id=%s", stage_run_id
                )
                db.rollback()


def start_stage_run_async(stage_run_id: int) -> None:
    if _executor_closed:
        logger.warning("阶段运行线程池已关闭，忽略启动请求")
        return
    _stage_executor.submit(execute_stage_run, stage_run_id)


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
    """任意阶段的对话回复。逐段通过 SSE 推送 message_delta。"""
    if run.status != "collecting":
        raise ValueError("当前阶段不在对话状态")
    stage = db.get(Stage, run.stage_id)
    stage_code = stage.code if stage else "requirements"
    provider = _get_runnable_provider(run, db)
    messages = _build_interview_messages(
        db, run, system_prompt=build_chat_system_prompt(stage_code)
    )

    def on_delta(piece: str) -> None:
        publish(
            run.project_id,
            "message_delta",
            {"stage_run_id": run.id, "content": piece},
        )

    reply = _stream_llm(provider, messages, on_delta) or "请继续补充本阶段信息。"
    message = Message(
        project_id=run.project_id,
        stage_run_id=run.id,
        role="agent",
        agent_code=STAGE_AGENT_CODE.get(stage_code, "coordinator"),
        content=reply,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    publish(
        run.project_id,
        "message",
        {
            "stage_run_id": run.id,
            "message_id": message.id,
            "role": "agent",
            "content": reply,
        },
    )
    return message


def build_stage_opening(stage: Stage) -> str:
    """任意阶段进入对话模式时的开场白。"""
    if stage.code == "requirements":
        return INITIAL_INTERVIEW_MESSAGE
    return build_chat_opening(stage.code, stage.name)


def confirm_stage(run: StageRun, db: Session) -> StageRun:
    """把当前阶段的对话记录整理成该阶段正式文档，供人工评审。"""
    if run.status != "collecting":
        raise ValueError("当前阶段不在对话状态")
    project = db.get(Project, run.project_id)
    stage = db.get(Stage, run.stage_id)
    if project is None or stage is None:
        raise ValueError("阶段或项目不存在")
    provider = _get_runnable_provider(run, db)

    transcript_rows = list(
        db.scalars(
            select(Message)
            .where(Message.stage_run_id == run.id)
            .order_by(Message.id)
        )
    )
    transcript = "\n".join(
        f"{'用户' if row.role == 'user' else 'Agent'}: {row.content}"
        for row in transcript_rows
    )
    previous_rows = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.stage_run_id != run.id)
            .order_by(Artifact.id)
        )
    )
    previous_artifacts = "\n\n".join(
        f"### {row.title}\n{row.content_md}" for row in previous_rows
    )

    system, user_prompt = build_confirm_prompt(
        stage_code=stage.code,
        stage_name=stage.name,
        project_name=project.name,
        project_description=project.description,
        previous_artifacts=previous_artifacts,
        transcript=transcript,
    )

    run.status = "generating"
    db.commit()
    publish(
        run.project_id,
        "stage_status",
        {"stage_run_id": run.id, "stage_code": stage.code, "status": "generating"},
    )

    content = ""
    reason = ""
    for attempt in range(1, _MAX_DOC_ATTEMPTS + 1):
        prompt = user_prompt
        if reason:
            prompt += f"\n\n上次输出未通过校验：\n{reason}\n请修正后完整重新输出。"
        content = _invoke_llm(provider, system, prompt, max_tokens=2000)
        reason = validate_document(stage.code, content)
        if not reason:
            break

    title = "软件需求规格说明书" if stage.code == "requirements" else f"{stage.name}文档"
    artifact = Artifact(
        project_id=run.project_id,
        stage_run_id=run.id,
        type=stage.code,
        title=title,
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
            message=f"{stage.name}对话确认完成，{title}已生成",
        )
    )
    db.commit()
    try:
        rebuild_traceability(db, run.project_id)
    except Exception:  # noqa: BLE001
        logger.exception("重建追溯关系失败")
        db.rollback()
    try:
        write_artifact_file(run.project_id, artifact)
    except Exception:  # noqa: BLE001
        logger.exception("文档产物写文件失败")
    publish(
        run.project_id,
        "artifact_saved",
        {
            "stage_run_id": run.id,
            "artifact_id": artifact.id,
            "version": artifact.current_version,
            "title": artifact.title,
        },
    )
    publish(
        run.project_id,
        "review_opened",
        {"stage_run_id": run.id, "stage_code": stage.code},
    )
    _suggest_review_for_run(run, stage, artifact, provider, db)
    return run


def _suggest_review_for_run(
    run: StageRun,
    stage: Stage,
    artifact: Artifact,
    provider: LLMProvider,
    db: Session,
) -> None:
    """为一次已完成生成的阶段运行补充评审 Agent 建议。"""
    try:
        system, user = build_review_prompt(
            stage_code=stage.code,
            stage_name=stage.name,
            content=artifact.content_md,
        )
        suggestion = _invoke_llm(provider, system, user, max_tokens=1200).strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("评审 Agent 执行失败: stage_run_id=%s", run.id)
        suggestion = f"评审 Agent 执行失败：{exc}"
    if not suggestion:
        suggestion = "评审 Agent 未返回内容。"
    db.add(
        Review(
            stage_run_id=run.id,
            artifact_id=artifact.id,
            reviewer_type="agent",
            result="suggested",
            comment=suggestion,
        )
    )
    db.add(
        ActivityEvent(
            project_id=run.project_id,
            stage_run_id=run.id,
            event_type="review_suggested",
            message=f"评审 Agent 已给出{stage.name}审查建议",
        )
    )
    db.commit()
    publish(
        run.project_id,
        "review_suggested",
        {"stage_run_id": run.id, "comment": suggestion[:2000]},
    )


def confirm_requirements(run: StageRun, db: Session) -> StageRun:
    """兼容旧调用：等价于 confirm_stage。"""
    return confirm_stage(run, db)


def review_stage_run(
    run: StageRun,
    db: Session,
    result: str,
    comment: str = "",
) -> StageRun:
    if run.status not in ("awaiting_review", "verification_failed"):
        raise ValueError("当前阶段不在可评审状态")
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
    publish(
        run.project_id,
        "review_result",
        {"stage_run_id": run.id, "result": result, "comment": comment[:1000]},
    )
    publish(
        run.project_id,
        "stage_status",
        {"stage_run_id": run.id, "status": result},
    )
    if result == "approved":
        _maybe_auto_advance(run, db)
    return run


def _next_stage(db: Session, project: Project, stage_id: int) -> Stage | None:
    stages = list(
        db.scalars(
            select(Stage)
            .where(Stage.process_model_id == project.process_model_id)
            .order_by(Stage.seq)
        )
    )
    for index, stage in enumerate(stages):
        if stage.id == stage_id:
            return stages[index + 1] if index + 1 < len(stages) else None
    return None


def _maybe_auto_advance(run: StageRun, db: Session) -> StageRun | None:
    """统筹 Agent：项目开启自动推进时，评审通过后自动启动下一阶段。"""
    project = db.get(Project, run.project_id)
    if project is None or not project.auto_advance:
        return None
    next_stage = _next_stage(db, project, run.stage_id)
    if next_stage is None:
        publish(
            project.id,
            "stage_completed",
            {"stage_run_id": run.id, "message": "全部阶段已完成"},
        )
        return None
    existing = db.scalar(
        select(StageRun).where(
            StageRun.project_id == project.id,
            StageRun.stage_id == next_stage.id,
            StageRun.status.in_(
                ["pending", "collecting", "generating", "awaiting_review", "approved"]
            ),
        )
    )
    if existing is not None:
        return None
    new_run = StageRun(
        project_id=project.id,
        stage_id=next_stage.id,
        provider_id=run.provider_id,
        status="pending",
        mode="auto",
    )
    db.add(new_run)
    db.flush()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=new_run.id,
            event_type="coordinator",
            message=f"统筹 Agent 自动启动下一阶段「{next_stage.name}」",
        )
    )
    db.commit()
    publish(
        project.id,
        "stage_status",
        {"stage_run_id": new_run.id, "stage_code": next_stage.code, "status": "pending"},
    )
    start_stage_run_async(new_run.id)
    return new_run


def serialize_message(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)
