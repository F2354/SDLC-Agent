from datetime import datetime

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.llm_provider import LLMProvider
from app.models.process_model import ProcessModel, Stage
from app.models.project import Project
from app.models.stage_run import ActivityEvent, Artifact, Message, StageRun
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectFlowOut,
    ProjectFlowStage,
    ProjectOut,
    ProjectUpdate,
    StageOut,
)
from app.schemas.stage import (
    ActivityEventOut,
    ArtifactOut,
    StageRunOut,
    StageStartRequest,
)
from app.schemas.analytics import ProjectStatsOut, TraceabilityOut
from app.services.event_bus import publish
from app.services.stage_service import (
    STAGE_AGENT_CODE,
    build_stage_opening,
    is_code_stage,
    serialize_stage_run,
    start_stage_run_async,
)
from app.services.traceability import compute_traceability
from app.services.process_graph import get_stage_dependencies

router = APIRouter(prefix="/projects", tags=["projects"])


def get_owned_project(project_id: int, user: User, db: Session) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.owner_id == user.id)
        .options(selectinload(Project.process_model))
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(Project)
            .where(Project.owner_id == user.id)
            .options(selectinload(Project.process_model))
            .order_by(Project.created_at.desc())
        )
    )


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model = db.scalar(
        select(ProcessModel).where(
            ProcessModel.code == payload.process_model_code,
            ProcessModel.enabled,
        )
    )
    if model is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的过程模型")

    if not payload.folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请选择项目文件夹：代码与文档将生成在该文件夹内",
        )
    folder_path = Path(payload.folder)
    if not folder_path.is_absolute() or not folder_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目文件夹必须是本机上已存在的绝对路径",
        )
    folder = str(folder_path.resolve())

    project = Project(
        owner_id=user.id,
        process_model_id=model.id,
        name=payload.name,
        description=payload.description,
        folder=folder,
    )
    db.add(project)
    db.commit()

    project = db.scalar(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.process_model))
    )
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_owned_project(project_id, user, db)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.auto_advance is not None:
        project.auto_advance = payload.auto_advance
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    db.delete(project)
    db.commit()


@router.post(
    "/{project_id}/stages/{stage_code}/start",
    response_model=StageRunOut,
    status_code=status.HTTP_201_CREATED,
)
def start_stage(
    project_id: int,
    stage_code: str,
    payload: StageStartRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    stage = db.scalar(
        select(Stage).where(
            Stage.process_model_id == project.process_model_id,
            Stage.code == stage_code,
        )
    )
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="阶段不存在")

    running = db.scalar(
        select(StageRun).where(
            StageRun.project_id == project.id,
            StageRun.stage_id == stage.id,
            StageRun.status.in_(["pending", "collecting", "generating"]),
        )
    )
    if running is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该阶段正在执行")

    # Scheduling is dependency-graph based. Independent branches (for example
    # the three V-model verification lanes) can start in parallel.
    all_stages = list(
        db.scalars(
            select(Stage)
            .where(Stage.process_model_id == project.process_model_id)
            .order_by(Stage.seq)
        )
    )
    stage_codes = [item.code for item in all_stages]
    dependencies = get_stage_dependencies(project.process_model.code, stage.code, stage_codes)
    if dependencies:
        dependency_stages = {item.code: item for item in all_stages if item.code in dependencies}
        for dependency_code in dependencies:
            dependency_stage = dependency_stages.get(dependency_code)
            dependency_run = None
            if dependency_stage is not None:
                dependency_run = db.scalar(
                    select(StageRun)
                    .where(
                        StageRun.project_id == project.id,
                        StageRun.stage_id == dependency_stage.id,
                        StageRun.status.in_(["approved", "completed"]),
                    )
                    .order_by(StageRun.id.desc())
                )
            if dependency_run is None:
                dependency_name = dependency_stage.name if dependency_stage else dependency_code
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"请先完成并通过依赖阶段「{dependency_name}」",
                )

    provider = None
    if payload.provider_id is not None:
        provider = db.scalar(
            select(LLMProvider).where(
                LLMProvider.id == payload.provider_id,
                LLMProvider.user_id == user.id,
                LLMProvider.enabled,
            )
        )
        if provider is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")
    else:
        provider = db.scalar(
            select(LLMProvider)
            .where(LLMProvider.user_id == user.id, LLMProvider.enabled)
            .order_by(LLMProvider.created_at.desc())
        )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先配置可用的模型 Provider")

    if payload.mode == "chat" and is_code_stage(stage.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"「{stage.name}」需要生成并运行代码，请使用自动模式",
        )

    run = StageRun(
        project_id=project.id,
        stage_id=stage.id,
        provider_id=provider.id,
        status="pending",
        mode=payload.mode,
    )
    db.add(run)
    db.flush()
    if payload.mode == "chat":
        run.status = "collecting"
        run.started_at = datetime.now()
        opening = Message(
            project_id=project.id,
            stage_run_id=run.id,
            role="agent",
            agent_code=STAGE_AGENT_CODE.get(stage.code, "coordinator"),
            content=build_stage_opening(stage),
        )
        db.add(opening)
        db.commit()
        db.refresh(run)
        db.refresh(opening)
        publish(
            project.id,
            "stage_status",
            {"stage_run_id": run.id, "stage_code": stage.code, "status": "collecting"},
        )
        publish(
            project.id,
            "message",
            {
                "stage_run_id": run.id,
                "message_id": opening.id,
                "role": "agent",
                "content": opening.content,
            },
        )
    else:
        db.commit()
        db.refresh(run)
        publish(
            project.id,
            "stage_status",
            {"stage_run_id": run.id, "stage_code": stage.code, "status": "pending"},
        )
        start_stage_run_async(run.id)
    return serialize_stage_run(run, db)


@router.get("/{project_id}/artifacts", response_model=list[ArtifactOut])
def list_project_artifacts(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    return list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.id.desc())
        )
    )


@router.get("/{project_id}/activity-events", response_model=list[ActivityEventOut])
def list_activity_events(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    return list(
        db.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.project_id == project.id)
            .order_by(ActivityEvent.id.desc())
            .limit(100)
        )
    )


@router.get("/{project_id}/traceability", response_model=TraceabilityOut)
def project_traceability(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    return compute_traceability(db, project.id)


@router.get("/{project_id}/stats", response_model=ProjectStatsOut)
def project_stats(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    runs = list(
        db.scalars(
            select(StageRun).where(StageRun.project_id == project.id)
        )
    )
    stage_counts: dict[str, int] = {}
    for run in runs:
        stage_counts[run.status] = stage_counts.get(run.status, 0) + 1
    artifacts = list(
        db.scalars(
            select(Artifact).where(Artifact.project_id == project.id)
        )
    )
    traceability = compute_traceability(db, project.id)
    return ProjectStatsOut(
        project_id=project.id,
        stage_counts=stage_counts,
        artifact_count=len(artifacts),
        total_chars=sum(len(artifact.content_md) for artifact in artifacts),
        entity_counts=traceability.entity_counts,
    )


@router.get("/{project_id}/flow", response_model=ProjectFlowOut)
def project_flow(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(project_id, user, db)
    stages = list(
        db.scalars(
            select(Stage)
            .where(Stage.process_model_id == project.process_model_id)
            .order_by(Stage.seq)
        )
    )
    runs = list(
        db.scalars(
            select(StageRun)
            .where(StageRun.project_id == project.id)
            .order_by(StageRun.id.desc())
        )
    )
    latest_runs = {}
    for run in runs:
        if run.stage_id not in latest_runs:
            latest_runs[run.stage_id] = run
    return ProjectFlowOut(
        process_model=project.process_model,
        auto_advance=project.auto_advance,
        stages=[
            ProjectFlowStage(
                stage=StageOut.model_validate(stage),
                status=latest_runs[stage.id].status
                if stage.id in latest_runs
                else "pending",
                stage_run_id=latest_runs[stage.id].id if stage.id in latest_runs else None,
                dependencies=get_stage_dependencies(
                    project.process_model.code,
                    stage.code,
                    [item.code for item in stages],
                ),
            )
            for stage in stages
        ],
    )
