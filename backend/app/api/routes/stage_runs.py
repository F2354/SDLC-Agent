from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.stage_run import Artifact, Message, StageRun
from app.models.user import User
from app.schemas.stage import (
    ArtifactOut,
    ChatRequest,
    MessageOut,
    ReviewRequest,
    StageRunOut,
)
from app.services.stage_service import (
    confirm_requirements,
    review_stage_run,
    send_interview_reply,
    serialize_message,
    serialize_stage_run,
)

router = APIRouter(prefix="/stage-runs", tags=["stage-runs"])


def get_owned_stage_run(run_id: int, user: User, db: Session) -> StageRun:
    run = db.get(StageRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="阶段运行记录不存在")
    project = db.get(Project, run.project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="阶段运行记录不存在")
    return run


@router.get("/{run_id}", response_model=StageRunOut)
def get_stage_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_stage_run(get_owned_stage_run(run_id, user, db), db)


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_stage_run_artifacts(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned_stage_run(run_id, user, db)
    return list(
        db.scalars(
            select(Artifact)
            .where(Artifact.stage_run_id == run.id)
            .order_by(Artifact.id)
        )
    )


@router.get("/{run_id}/messages", response_model=list[MessageOut])
def list_stage_run_messages(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned_stage_run(run_id, user, db)
    messages = db.scalars(
        select(Message)
        .where(Message.stage_run_id == run.id)
        .order_by(Message.id)
    )
    return [serialize_message(message) for message in messages]


@router.post("/{run_id}/chat", response_model=MessageOut)
def send_chat_message(
    run_id: int,
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned_stage_run(run_id, user, db)
    if run.mode != "chat" or run.status != "collecting":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前阶段不支持对话")
    user_message = Message(
        project_id=run.project_id,
        stage_run_id=run.id,
        role="user",
        content=payload.content,
    )
    db.add(user_message)
    db.commit()
    try:
        reply = send_interview_reply(run, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return serialize_message(reply)


@router.post("/{run_id}/confirm-requirements", response_model=StageRunOut)
def confirm_requirements_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned_stage_run(run_id, user, db)
    try:
        run = confirm_requirements(run, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return serialize_stage_run(run, db)


@router.post("/{run_id}/approve", response_model=StageRunOut)
def approve_stage_run(
    run_id: int,
    payload: ReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned_stage_run(run_id, user, db)
    try:
        run = review_stage_run(run, db, "approved", payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return serialize_stage_run(run, db)


@router.post("/{run_id}/reject", response_model=StageRunOut)
def reject_stage_run(
    run_id: int,
    payload: ReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned_stage_run(run_id, user, db)
    try:
        run = review_stage_run(run, db, "rejected", payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return serialize_stage_run(run, db)
