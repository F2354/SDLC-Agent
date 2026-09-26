import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.error")

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.stage_run import Artifact, ArtifactVersion
from app.models.user import User
from app.schemas.stage import ArtifactOut, ArtifactUpdate
from app.services.artifact_file import write_artifact_file
from app.services.export import artifact_to_docx, artifact_to_pdf
from app.services.stage_service import commit_stage_progress
from app.services.traceability import rebuild_traceability

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def get_owned_artifact(artifact_id: int, user: User, db: Session) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    project = db.get(Project, artifact.project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    return artifact


@router.patch("/{artifact_id}", response_model=ArtifactOut)
def update_artifact(
    artifact_id: int,
    payload: ArtifactUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artifact = get_owned_artifact(artifact_id, user, db)
    next_version = artifact.current_version + 1
    artifact.content_md = payload.content_md
    artifact.current_version = next_version
    db.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_no=next_version,
            content_md=payload.content_md,
            change_note="人工修订",
        )
    )
    db.commit()
    db.refresh(artifact)
    try:
        rebuild_traceability(db, artifact.project_id)
    except Exception:  # noqa: BLE001
        logger.exception("重建追溯关系失败")
        db.rollback()
    try:
        write_artifact_file(artifact.project_id, artifact)
    except Exception:  # noqa: BLE001
        logger.exception("文档产物写文件失败")
    # 人工修订同样进入 Git 轨迹，便于回溯"谁在什么时候改了什么"。
    commit_stage_progress(db, artifact.project_id, artifact.type, "人工修订已保存")
    return artifact


@router.get("/{artifact_id}/export")
def export_artifact(
    artifact_id: int,
    format: Literal["docx", "pdf"] = "docx",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artifact = get_owned_artifact(artifact_id, user, db)
    if format == "docx":
        content = artifact_to_docx(artifact.title, artifact.content_md)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        content = artifact_to_pdf(artifact.title, artifact.content_md)
        media_type = "application/pdf"
    filename = f"artifact-{artifact.id}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.{format}"'
        },
    )
