from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_project_or_404
from app.db.session import get_db
from app.models.user import User
from app.schemas.agent import AgentProfileOut
from app.services.agents import list_agent_profiles

router = APIRouter(prefix="/projects/{project_id}/agents", tags=["agents"])


@router.get("", response_model=list[AgentProfileOut])
def list_agents(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    try:
        return list_agent_profiles(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
