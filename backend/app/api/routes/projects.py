from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.llm_provider import LLMProvider
from app.models.process_model import ProcessModel, Stage
from app.models.project import Project
from app.models.stage_run import Artifact, Message, StageRun
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectFlowOut,
    ProjectFlowStage,
    ProjectOut,
    ProjectUpdate,
    StageOut,
)
from app.schemas.stage import ArtifactOut, StageRunOut, StageStartRequest
from app.services.stage_service import (
    INITIAL_INTERVIEW_MESSAGE,
    serialize_stage_run,
    start_stage_run_async,
)

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

    project = Project(
        owner_id=user.id,
        process_model_id=model.id,
        name=payload.name,
        description=payload.description,
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

    run = StageRun(
        project_id=project.id,
        stage_id=stage.id,
        provider_id=provider.id,
        status="pending",
        mode=payload.mode,
    )
    db.add(run)
    db.flush()
    if payload.mode == "chat" and stage.code == "requirements":
        run.status = "collecting"
        run.started_at = datetime.now()
        db.add(
            Message(
                project_id=project.id,
                stage_run_id=run.id,
                role="agent",
                agent_code="requirements_analyst",
                content=INITIAL_INTERVIEW_MESSAGE,
            )
        )
        db.commit()
        db.refresh(run)
    else:
        db.commit()
        db.refresh(run)
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
        stages=[
            ProjectFlowStage(
                stage=StageOut.model_validate(stage),
                status=latest_runs[stage.id].status
                if stage.id in latest_runs
                else "pending",
                stage_run_id=latest_runs[stage.id].id if stage.id in latest_runs else None,
            )
            for stage in stages
        ],
    )
