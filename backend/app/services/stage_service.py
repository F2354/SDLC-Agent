import atexit
import json
import logging
import threading
import time
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
from app.services.llm_log import extract_token_usage, record_llm_call
from app.services.prompts import (
    build_chat_opening,
    build_chat_system_prompt,
    build_code_stage_prompt,
    build_confirm_prompt,
    build_review_prompt,
    build_stage_prompt,
)
from app.services.code_service import (
    commit_project_changes,
    list_code_files,
    read_code_file,
    run_stage_tests,
    run_verify,
    write_files,
)
from app.services.agent_roles import get_role_spec
from app.services.agents import resolve_agent_model
from app.services.coding_agent import run_coding_harness
from app.services.artifact_file import write_artifact_file
from app.services.traceability import (
    STAGE_ENTITY_REQUIREMENTS,
    parse_entities,
    rebuild_traceability,
)
from app.services.stage_contracts import contract_context_text, stage_contract
from app.services.process_graph import get_stage_dependencies, group_by_parallel_batch

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


# 每个项目一把自动推进锁。
# 并行通道（如 V 模型的三条验证通道）会在不同线程里各自触发自动推进，
# 若不加锁，"检查下游是否已启动 → 创建 run" 这段会在多个线程中交错执行，
# 导致同一个下游阶段被重复启动。锁内先结束旧事务，确保读到其它通道刚提交的数据。
_advance_locks: dict[int, threading.Lock] = {}
_advance_locks_guard = threading.Lock()


def _project_advance_lock(project_id: int) -> threading.Lock:
    with _advance_locks_guard:
        return _advance_locks.setdefault(project_id, threading.Lock())


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


# 需要真实写盘并运行验证，且应当走「Agent 工具循环」的阶段 → 绑定的执行角色。
# 在此之前只有 coding 一个阶段真的走了工具循环，其余 6 个（含 V 模型三条验证通道）
# 都退化成了单次文档生成 —— 与 README 的承诺不符。这里按角色重新绑定：
# 开发类阶段由开发工程师完成，验证类阶段由测试工程师完成。
TOOL_LOOP_ROLES: dict[str, str] = {
    "coding": "developer",
    "prototype": "developer",
    "sprint-dev": "developer",
    "testing": "tester",
    "unit-test": "tester",
    "integration-test": "tester",
    "system-test": "tester",
}


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

# 评审节点固定使用 reviewer 角色的模型配置，与生成节点解耦。
REVIEWER_AGENT_CODE = "reviewer"

# 未知阶段回退到统筹角色。
DEFAULT_AGENT_CODE = "coordinator"


def stage_agent_code(stage_code: str) -> str:
    """阶段 → 负责该阶段的 agent 角色编码。"""
    return STAGE_AGENT_CODE.get(stage_code, DEFAULT_AGENT_CODE)


def resolve_stage_agent(
    provider: LLMProvider,
    stage_code: str,
    project_id: int,
    db: Session,
) -> tuple[LLMProvider, str]:
    """解析阶段所用角色实际生效的 (Provider, 模型名)。"""
    return resolve_agent_model(db, project_id, stage_agent_code(stage_code), provider)


def resolve_reviewer_agent(
    provider: LLMProvider,
    project_id: int,
    db: Session,
) -> tuple[LLMProvider, str]:
    """解析评审 Agent 实际生效的 (Provider, 模型名)。

    评审与生成使用不同角色，因此可以配置不同模型（例如用更强的模型做审查）。
    """
    return resolve_agent_model(db, project_id, REVIEWER_AGENT_CODE, provider)


def commit_stage_progress(
    db: Session,
    project_id: int,
    stage_code: str,
    action: str,
) -> None:
    """把阶段产物落盘后的项目状态提交为一次 Git 提交。

    提交信息形如 ``[waterfall 3/5] 详细设计 · 文档已生成``，使 ``git log``
    直接呈现过程模型的执行轨迹，而不是一堆无语义的快照。

    Git 失败只记录日志，绝不影响阶段执行本身。
    """
    try:
        project = db.get(Project, project_id)
        if project is None:
            return
        model_code = project.process_model.code if project.process_model else ""

        stages: list[Stage] = []
        if project.process_model_id is not None:
            stages = list(
                db.scalars(
                    select(Stage)
                    .where(Stage.process_model_id == project.process_model_id)
                    .order_by(Stage.seq)
                )
            )
        position = next(
            (index for index, item in enumerate(stages, start=1) if item.code == stage_code),
            0,
        )
        stage_name = stages[position - 1].name if position else stage_code

        progress = f"{position}/{len(stages)}" if position else ""
        scope = " ".join(part for part in (model_code, progress) if part)
        message = f"[{scope}] {stage_name} · {action}"

        result = commit_project_changes(project_id, message)
    except Exception:  # noqa: BLE001
        logger.exception(
            "阶段进度 Git 提交失败: project=%s stage=%s", project_id, stage_code
        )
        return

    if not result.get("created"):
        return
    logger.info("阶段进度已提交: %s (%s)", message, result.get("commit"))
    publish(
        project_id,
        "git_committed",
        {
            "stage_code": stage_code,
            "commit": result.get("commit"),
            "message": message,
        },
    )


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
    contract_text: str
    model_name: str
    output: str
    error_info: str
    attempts: int
    max_attempts: int
    needs_retry: bool
    should_review: bool
    artifact_id: int
    traceability_summary: str


def _previous_artifacts_text(
    db: Session,
    project: Project,
    stage: Stage,
    exclude_run_id: int | None = None,
) -> str:
    """按阶段契约裁剪前置产物上下文。

    契约未声明 inputs 时保持旧行为（全量拼接）；声明了 inputs 时只纳入
    指定阶段的产物（经 stage_run → stage 关联判断），若一个都匹配不到
    则回退全量 —— 防御首轮缺产物的场景。
    """
    rows = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.id)
        )
    )
    if exclude_run_id is not None:
        rows = [row for row in rows if row.stage_run_id != exclude_run_id]

    contract = stage_contract(
        project.process_model.code if project.process_model else None, stage.code
    )
    if contract.inputs is not None and rows:
        allowed = set(contract.inputs)
        filtered = [
            row
            for row in rows
            if row.stage_run is not None
            and row.stage_run.stage is not None
            and row.stage_run.stage.code in allowed
        ]
        if filtered:
            rows = filtered
    return "\n\n".join(f"### {row.title}\n{row.content_md}" for row in rows)


def _entity_gap(stage_code: str, text: str) -> str:
    """检查阶段必需的规范编号实体是否齐备，返回不合格原因（空串表示通过）。

    这是让追溯矩阵有数据的关键一环：提示词写明了编号约定，但模型并不总会遵守
    （实测 18 个产物中 UC 检出恒为 0）。把实体要求放进文档校验，
    就能复用 LangGraph 的重试回路要求模型补齐，而不是事后在报表上打补丁。
    """
    requirements = STAGE_ENTITY_REQUIREMENTS.get(stage_code)
    if not requirements:
        return ""
    found = parse_entities(text)
    problems = [
        f"{entity_type} 至少 {minimum} 条（当前 {len(found.get(entity_type, ()))} 条）"
        for entity_type, minimum in requirements.items()
        if len(found.get(entity_type, ())) < minimum
    ]
    if not problems:
        return ""
    return (
        "文档缺少规范编号的实体：" + "、".join(problems) + "。"
        "请为每个条目使用独立三级标题并标注编号，例如 `### 需求条目 RQ-001`、"
        "`### 用例 UC-001`；用例须在正文标注来源需求（如「来源：RQ-001」），"
        "模块须标注实现的需求或用例，测试用例须标注验证的需求或模块。"
    )


def validate_document(stage_code: str, content: str) -> str:
    """校验生成文档的完整性。返回空字符串表示通过，否则返回不合格原因。"""
    text = (content or "").strip()
    if len(text) < _MIN_DOC_CHARS:
        return f"文档内容过短（仅 {len(text)} 字符），请补全全部章节后重新输出完整文档。"
    missing = [hint for hint in _STAGE_REQUIRED_HINTS.get(stage_code, ()) if hint not in text]
    if missing:
        return "文档缺少关键内容：" + "、".join(missing) + "。请补齐后重新输出完整文档。"
    return _entity_gap(stage_code, text)


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
            contract_text=current.get("contract_text", ""),
        )
        if current.get("error_info"):
            user += (
                f"\n\n上次输出未通过校验：\n{current['error_info']}\n"
                "请修正后完整重新输出全部章节。"
            )
        content = _invoke_llm(
            provider,
            system,
            user,
            max_tokens=2000,
            model_name=current.get("model_name"),
            db=db,
            purpose="document_generate" if attempt == 1 else "document_retry",
            project_id=current["project_id"],
            stage_run_id=current["stage_run_id"],
        )
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
        commit_stage_progress(
            db, current["project_id"], current["stage_code"], "文档已生成"
        )
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
        review_provider, review_model = resolve_reviewer_agent(
            provider, current["project_id"], db
        )
        try:
            suggestion = _invoke_llm(
                review_provider,
                system,
                user,
                max_tokens=1200,
                model_name=review_model,
                db=db,
                purpose="stage_review",
                project_id=current["project_id"],
                stage_run_id=current["stage_run_id"],
            )
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
    model_name: str | None = None,
    *,
    db: Session | None = None,
    purpose: str = "document_generate",
    project_id: int | None = None,
    stage_run_id: int | None = None,
) -> str:
    """一次性调用 LLM，并把调用明细落进 llm_call_logs。

    db 为空时退化为纯调用（如无会话上下文的工具场景），不影响主流程。
    """
    resolved_model = model_name or provider.default_model
    client = build_openai_client(provider)
    started = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        record_llm_call(
            db,
            provider_id=provider.id,
            model=resolved_model,
            purpose=purpose,
            latency_ms=int((time.perf_counter() - started) * 1000),
            status="failed",
            error=exc,
            project_id=project_id,
            stage_run_id=stage_run_id,
        )
        raise
    prompt_tokens, completion_tokens = extract_token_usage(completion)
    record_llm_call(
        db,
        provider_id=provider.id,
        model=resolved_model,
        purpose=purpose,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
        project_id=project_id,
        stage_run_id=stage_run_id,
    )
    return completion.choices[0].message.content or ""


def _stream_llm(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    on_delta,
    temperature: float = 0.4,
    max_tokens: int = 900,
    model_name: str | None = None,
    *,
    db: Session | None = None,
    purpose: str = "chat_stream",
    project_id: int | None = None,
    stage_run_id: int | None = None,
) -> str:
    """流式调用 LLM；通过 on_delta 回调逐段推送，返回完整文本。

    若 Provider 不支持流式，则回退到一次性调用，保证功能可用。
    两条路径的耗时与用量都会记进 llm_call_logs。
    """
    resolved_model = model_name or provider.default_model
    client = build_openai_client(provider)
    chunks: list[str] = []
    started = time.perf_counter()
    try:
        stream = client.chat.completions.create(
            model=resolved_model,
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
        record_llm_call(
            db,
            provider_id=provider.id,
            model=resolved_model,
            purpose=purpose,
            latency_ms=int((time.perf_counter() - started) * 1000),
            project_id=project_id,
            stage_run_id=stage_run_id,
        )
        return "".join(chunks)
    except Exception:  # noqa: BLE001
        logger.warning("流式调用失败，回退为非流式", exc_info=True)
    fallback_started = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        record_llm_call(
            db,
            provider_id=provider.id,
            model=resolved_model,
            purpose=f"{purpose}_fallback",
            latency_ms=int((time.perf_counter() - fallback_started) * 1000),
            status="failed",
            error=exc,
            project_id=project_id,
            stage_run_id=stage_run_id,
        )
        raise
    prompt_tokens, completion_tokens = extract_token_usage(completion)
    record_llm_call(
        db,
        provider_id=provider.id,
        model=resolved_model,
        purpose=f"{purpose}_fallback",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=int((time.perf_counter() - fallback_started) * 1000),
        project_id=project_id,
        stage_run_id=stage_run_id,
    )
    return completion.choices[0].message.content or ""


def execute_code_stage(
    stage: Stage,
    project: Project,
    run: StageRun,
    provider: LLMProvider,
    db: Session,
    model_name: str | None = None,
) -> None:
    tool_loop_role = TOOL_LOOP_ROLES.get(stage.code)
    if tool_loop_role is not None:
        execute_coding_harness_stage(
            stage, project, run, provider, db, model_name, tool_loop_role
        )
        return

    # 兜底：出现在 CODE_STAGE_CODES 但未绑定角色的阶段，仍走单次生成路径。
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

    previous_artifacts = _previous_artifacts_text(db, project, stage)

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
            model_name=model_name,
            db=db,
            purpose="code_fallback" if attempt == 1 else "code_fallback_retry",
            project_id=project.id,
            stage_run_id=run.id,
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
    commit_stage_progress(db, project.id, stage.code, "产物与验证结果已生成")
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


def _paired_stage_entities(
    db: Session, project: Project, pair_stage_code: str
) -> dict[str, list[str]]:
    """读取配对阶段最新产物中定义的实体编号，供测试用例映射参照。"""
    row = db.scalar(
        select(Artifact)
        .join(StageRun, Artifact.stage_run_id == StageRun.id)
        .join(Stage, StageRun.stage_id == Stage.id)
        .where(Artifact.project_id == project.id, Stage.code == pair_stage_code)
        .order_by(Artifact.id.desc())
    )
    if row is None:
        return {}
    return {k: v for k, v in parse_entities(row.content_md or "").items() if v}


def _tests_dir_snapshot(project_id: int, max_chars: int = 5000) -> str:
    """汇总 tests/ 下的测试源码，供生成用例映射时参照。"""
    chunks: list[str] = []
    used = 0
    try:
        tree = list_code_files(project_id, "tests")
    except Exception:  # noqa: BLE001
        return ""
    for item in tree.files:
        if used >= max_chars:
            break
        try:
            content = read_code_file(project_id, item.path, "tests")
        except Exception:  # noqa: BLE001
            continue
        piece = f"--- {item.path} ---\n{content}"
        chunks.append(piece[: max_chars - used])
        used += len(piece)
    return "\n\n".join(chunks)


def _test_case_mapping_md(
    db: Session,
    project: Project,
    stage: Stage,
    contract,  # StageContract
    provider: LLMProvider,
    model_name: str | None,
    stage_run_id: int | None = None,
) -> str:
    """为工具循环产出的真实测试生成「TC 用例映射」章节。

    工具循环阶段的产物是机器拼装的（文件清单 + 验证输出），天然不含
    TC-xxx 实体，追溯链会在「模块→测试」一跳断掉。这里让 LLM 对照
    配对设计阶段的实体编号，把已落盘的 pytest 测试映射为规范的
    `### 测试用例 TC-xxx`（正文标注 `验证：MOD-xxx / RQ-xxx`），
    使追溯覆盖率能真实反映三条验证通道的产出。
    """
    snapshot = _tests_dir_snapshot(project.id)
    if not snapshot.strip():
        return ""

    paired = (
        _paired_stage_entities(db, project, contract.pair_stage)
        if contract.pair_stage
        else {}
    )
    reference_lines = [
        f"{label}：{'、'.join(keys)}"
        for label, keys in (
            ("模块编号 MOD", paired.get("MOD")),
            ("需求编号 RQ", paired.get("RQ")),
        )
        if keys
    ]
    reference_text = "\n".join(reference_lines) or "（配对产物中未解析到实体编号）"

    minimum = contract.outputs.get("TC", 2)
    system = (
        "你是测试工程师。你的任务是把已写好的 pytest 测试整理为规范的测试用例映射清单，"
        "供自动追溯矩阵使用。只输出 Markdown 片段，不要输出任何解释。"
    )
    user = (
        f"配对阶段可引用的实体编号：\n{reference_text}\n\n"
        f"tests/ 目录下的测试源码：\n{snapshot}\n\n"
        "请为每个测试函数生成一个条目，格式严格如下：\n\n"
        "### 测试用例 TC-001\n"
        "验证：MOD-001\n"
        "覆盖 xxx 行为的说明（一两句）。\n\n"
        f"要求：编号从 TC-001 连续递增，至少 {minimum} 条；"
        "「验证：」必须引用上面列出的真实编号（不得编造）；"
        "一条用例只验证一个关注点。"
    )

    for attempt in range(2):
        content = _invoke_llm(
            provider,
            system,
            user,
            max_tokens=1600,
            model_name=model_name,
            db=db,
            purpose="test_mapping" if attempt == 1 else "test_mapping_retry",
            project_id=project.id,
            stage_run_id=stage_run_id,
        ).strip()
        found = parse_entities(content).get("TC", [])
        if len(found) >= minimum and "验证：" in content:
            return content
        user += (
            f"\n\n上次输出不合格：TC 实体 {len(found)} 条（要求 ≥{minimum}）或缺少"
            "「验证：」标注。请严格按格式重新输出完整清单。"
        )
    return ""


def execute_coding_harness_stage(
    stage: Stage,
    project: Project,
    run: StageRun,
    provider: LLMProvider,
    db: Session,
    model_name: str | None = None,
    agent_code: str = "developer",
) -> None:
    role = get_role_spec(agent_code)
    run.status = "generating"
    run.started_at = datetime.now()
    db.add(
        ActivityEvent(
            project_id=project.id,
            stage_run_id=run.id,
            event_type="agent_started",
            message=f"{stage.name}已开始（{role.name} · 工具循环）",
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
        {
            "stage_run_id": run.id,
            "agent_code": stage.code,
            "agent_role": agent_code,
            "model": model_name,
            "message": stage.name,
        },
    )

    previous_artifacts = _previous_artifacts_text(db, project, stage)
    contract = stage_contract(
        project.process_model.code if project.process_model else None, stage.code
    )

    result = run_coding_harness(
        project_id=project.id,
        provider=provider,
        project_name=project.name,
        project_description=project.description,
        previous_artifacts=previous_artifacts,
        max_turns=10,
        model_name=model_name,
        agent_code=agent_code,
        stage_run_id=run.id,
        contract_text=contract_context_text(contract),
        db=db,
    )
    if result.tool_usage:
        run.tool_usage_json = json.dumps(result.tool_usage, ensure_ascii=False)
    target = role.write_target or "code"
    tree = list_code_files(project.id, target)
    files_md = "\n".join(f"- {item.path}" for item in tree.files)
    verify_md = result.verify.output if result.verify else "无运行结果"
    tests_md = result.tests.output if result.tests else "无测试结果"
    usage_md = (
        "、".join(f"{tool}×{count}" for tool, count in sorted(result.tool_usage.items()))
        or "（无）"
    )
    log_md = (
        "\n".join(f"{index}. {line}" for index, line in enumerate(result.tool_log, start=1))
        or "（无）"
    )
    content_md = (
        f"# {stage.name}产物\n\n"
        f"执行角色：{role.name}（{agent_code}）\n"
        f"使用模型：{model_name or '（Provider 默认）'}\n\n"
        f"生成文件（{target}/）：\n{files_md or '（无）'}\n\n"
        f"## 工具调用（共 {sum(result.tool_usage.values())} 次）\n\n"
        f"统计：{usage_md}\n\n"
        f"轨迹：\n{log_md}\n\n"
        f"## 运行验证\n\n{verify_md}\n\n"
        f"## 测试结果\n\n{tests_md}\n\n"
        f"最终状态：{'通过' if result.ok else '未完全通过'}，共 {result.turn_count} 轮。"
    )

    # 契约要求产出 TC 实体的阶段（V 模型三条验证通道）：把已落盘的
    # pytest 测试映射为规范的 TC-xxx 用例，接通「模块→测试」追溯跳。
    if contract.outputs.get("TC"):
        try:
            mapping_md = _test_case_mapping_md(
                db, project, stage, contract, provider, model_name, run.id
            )
        except Exception:  # noqa: BLE001
            logger.exception("测试用例映射生成失败: stage=%s", stage.code)
            mapping_md = ""
        if mapping_md:
            content_md += "\n\n## 测试用例映射\n\n" + mapping_md

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
            message=f"{stage.name}（{role.name}）工具循环与验证结果已生成" if result.ok else f"{stage.name}验证未通过",
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
    commit_stage_progress(db, project.id, stage.code, f"{role.name}工具循环与验证结果已生成")
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
            # provider_id 可能为空（如测试数据或历史记录），显式判空避免
            # SQLAlchemy 对 NULL 主键发起查询并告警。
            provider = (
                db.get(LLMProvider, run.provider_id) if run.provider_id else None
            )
            if stage is None or project is None:
                raise ValueError("阶段或项目不存在")
            if provider is None or not provider.enabled:
                raise ValueError("请先配置可用的模型 Provider")

            # 按「阶段 → 角色 → agents.json」解析生效模型，未配置时回退默认模型。
            agent_code = stage_agent_code(stage.code)
            provider, model_name = resolve_stage_agent(
                provider, stage.code, project.id, db
            )
            # 记录到运行上，供过程模型视图展示"谁用哪个模型在干活"。
            run.agent_code = agent_code
            run.model_name = model_name
            logger.info(
                "阶段执行使用模型: stage=%s agent=%s model=%s",
                stage.code,
                agent_code,
                model_name,
            )

            if is_code_stage(stage.code):
                execute_code_stage(stage, project, run, provider, db, model_name)
                return

            run.status = "generating"
            run.started_at = datetime.now()
            db.add(
                ActivityEvent(
                    project_id=project.id,
                    stage_run_id=run.id,
                    event_type="agent_started",
                    message=f"{stage.name}阶段已开始（{agent_code} · {model_name}）",
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
                {
                    "stage_run_id": run.id,
                    "agent_code": stage.code,
                    "agent_role": agent_code,
                    "model": model_name,
                    "message": stage.name,
                },
            )

            previous_artifacts = _previous_artifacts_text(db, project, stage)
            contract = stage_contract(
                project.process_model.code if project.process_model else None,
                stage.code,
            )

            state: AgentState = {
                "project_id": project.id,
                "stage_run_id": run.id,
                "stage_code": stage.code,
                "stage_name": stage.name,
                "project_name": project.name,
                "project_description": project.description,
                "previous_artifacts": previous_artifacts,
                "contract_text": contract_context_text(contract),
                "model_name": model_name or provider.default_model,
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
    provider = db.get(LLMProvider, run.provider_id) if run.provider_id else None
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

    _, chat_model = resolve_stage_agent(provider, stage_code, run.project_id, db)
    reply = (
        _stream_llm(
            provider,
            messages,
            on_delta,
            model_name=chat_model,
            db=db,
            purpose="chat_stream",
            project_id=run.project_id,
            stage_run_id=run.id,
        )
        or "请继续补充本阶段信息。"
    )
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
    previous_artifacts = _previous_artifacts_text(
        db, project, stage, exclude_run_id=run.id
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
    _, confirm_model = resolve_stage_agent(provider, stage.code, run.project_id, db)
    for attempt in range(1, _MAX_DOC_ATTEMPTS + 1):
        prompt = user_prompt
        if reason:
            prompt += f"\n\n上次输出未通过校验：\n{reason}\n请修正后完整重新输出。"
        content = _invoke_llm(
            provider,
            system,
            prompt,
            max_tokens=2000,
            model_name=confirm_model,
            db=db,
            purpose="chat_confirm" if attempt == 1 else "chat_confirm_retry",
            project_id=run.project_id,
            stage_run_id=run.id,
        )
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
    commit_stage_progress(db, run.project_id, stage.code, "对话确认产物已生成")
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
        review_provider, review_model = resolve_reviewer_agent(
            provider, run.project_id, db
        )
        suggestion = _invoke_llm(
            review_provider,
            system,
            user,
            max_tokens=1200,
            model_name=review_model,
            db=db,
            purpose="stage_review",
            project_id=run.project_id,
            stage_run_id=run.id,
        ).strip()
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


def _ready_stage_codes(db: Session, project: Project) -> list[Stage]:
    """Return stages whose dependency runs are approved and which are not done.

    This is intentionally dependency based rather than ``seq - 1`` based. It
    lets a V-model project fan out into multiple verification agents while the
    waterfall model still remains a strict chain.
    """
    stages = list(
        db.scalars(
            select(Stage)
            .where(Stage.process_model_id == project.process_model_id)
            .order_by(Stage.seq)
        )
    )
    latest_runs: dict[int, StageRun] = {}
    for run in db.scalars(
        select(StageRun)
        .where(StageRun.project_id == project.id)
        .order_by(StageRun.id.desc())
    ):
        latest_runs.setdefault(run.stage_id, run)
    codes = [stage.code for stage in stages]
    ready: list[Stage] = []
    for stage in stages:
        latest = latest_runs.get(stage.id)
        if latest is not None:
            # A rejected/failed branch needs an explicit user retry; auto advance
            # must never silently overwrite that decision.
            continue
        dependencies = get_stage_dependencies(project.process_model.code, stage.code, codes)
        dependency_ids = {item.code: item.id for item in stages}
        if all(
            any(
                run.stage_id == dependency_ids[dependency_code]
                and run.status in {"approved", "completed"}
                for run in latest_runs.values()
            )
            for dependency_code in dependencies
            if dependency_code in dependency_ids
        ):
            ready.append(stage)
    return ready


def _all_stages_finished(db: Session, project: Project) -> bool:
    """所有阶段都已有最新运行且均已通过/完成。"""
    stages = list(
        db.scalars(
            select(Stage).where(Stage.process_model_id == project.process_model_id)
        )
    )
    if not stages:
        return False
    latest: dict[int, StageRun] = {}
    for row in db.scalars(
        select(StageRun)
        .where(StageRun.project_id == project.id)
        .order_by(StageRun.id.desc())
    ):
        latest.setdefault(row.stage_id, row)
    return len(latest) == len(stages) and all(
        row.status in {"approved", "completed"} for row in latest.values()
    )


def _maybe_auto_advance(run: StageRun, db: Session) -> list[StageRun]:
    """启动所有新解锁的阶段；同一并行批次会一起启动并广播批次事件。

    并行通道会在不同线程里各自触发本函数，因此整个过程持有项目级锁：
    锁内先结束旧事务，确保读到其它通道刚刚提交的状态，
    避免同一个下游阶段被重复启动。
    """
    project_id = run.project_id
    provider_id = run.provider_id

    with _project_advance_lock(project_id):
        # 先结束可能残留的旧事务，否则会读到其它并行通道提交之前的快照。
        db.rollback()
        project = db.get(Project, project_id)
        if project is None or not project.auto_advance:
            return []

        ready = _ready_stage_codes(db, project)
        if not ready:
            if _all_stages_finished(db, project):
                publish(project.id, "stage_completed", {"message": "全部阶段已完成"})
            return []

        all_stages = list(
            db.scalars(
                select(Stage)
                .where(Stage.process_model_id == project.process_model_id)
                .order_by(Stage.seq)
            )
        )
        ordered_codes = [item.code for item in all_stages]
        batches = group_by_parallel_batch(
            project.process_model.code,
            [item.code for item in ready],
            ordered_codes,
        )
        batch_of: dict[str, list[str]] = {
            code: batch for batch in batches for code in batch
        }

        started: list[StageRun] = []
        run_by_stage: dict[str, StageRun] = {}
        for stage in ready:
            new_run = StageRun(
                project_id=project.id,
                stage_id=stage.id,
                provider_id=provider_id,
                status="pending",
                mode="auto",
            )
            db.add(new_run)
            db.flush()
            started.append(new_run)
            run_by_stage[stage.code] = new_run
            db.add(
                ActivityEvent(
                    project_id=project.id,
                    stage_run_id=new_run.id,
                    event_type="coordinator",
                    message=f"统筹 Agent 自动启动阶段「{stage.name}」",
                )
            )
        # 先落库再广播：这样其它并行通道的自动推进能看到这些 run，不会重复创建。
        db.commit()

        for batch in batches:
            if len(batch) < 2:
                continue
            names = [
                item.name for item in ready if item.code in set(batch)
            ]
            summary = "、".join(names)
            publish(
                project.id,
                "parallel_batch",
                {
                    "stage_codes": batch,
                    "stage_run_ids": [
                        run_by_stage[code].id
                        for code in batch
                        if code in run_by_stage
                    ],
                    "lane_count": len(batch),
                    "message": f"并行启动 {len(batch)} 条通道：{summary}",
                },
            )
            db.add(
                ActivityEvent(
                    project_id=project.id,
                    event_type="parallel_batch",
                    message=f"统筹 Agent 并行启动 {len(batch)} 条通道：{summary}",
                )
            )
        db.commit()

        for new_run in started:
            stage = db.get(Stage, new_run.stage_id)
            publish(
                project.id,
                "stage_status",
                {
                    "stage_run_id": new_run.id,
                    "stage_code": stage.code if stage else "",
                    "status": "pending",
                },
            )
            start_stage_run_async(new_run.id)
        return started


def serialize_message(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)
