from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.skill import SkillOut, SkillSummaryOut
from app.services.skills import get_project_skill, list_project_skills

router = APIRouter(prefix="/projects/{project_id}/skills", tags=["skills"])


def get_owned_project(project_id: int, user: User, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.get("", response_model=list[SkillSummaryOut])
def list_skills(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    try:
        return [skill.summary() for skill in list_project_skills(project_id)]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{skill_name}", response_model=SkillOut)
def get_skill(
    project_id: int,
    skill_name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    try:
        skill = get_project_skill(project_id, skill_name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    return {**skill.summary(), "content": skill.content}
