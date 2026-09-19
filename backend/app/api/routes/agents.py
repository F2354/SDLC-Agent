from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.agent import AgentProfileOut
from app.services.agents import list_agent_profiles

router = APIRouter(prefix="/projects/{project_id}/agents", tags=["agents"])


@router.get("", response_model=list[AgentProfileOut])
def list_agents(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        return list_agent_profiles(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
