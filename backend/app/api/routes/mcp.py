from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.mcp import McpServerSummary
from app.services.mcp import discover_mcp_tools, list_mcp_servers

router = APIRouter(prefix="/projects/{project_id}/mcp", tags=["mcp"])


def get_owned_project(project_id: int, user: User, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.get("", response_model=list[McpServerSummary])
def list_servers(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    try:
        return list_mcp_servers(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{server_name}/discover", response_model=McpServerSummary)
def discover_tools(
    project_id: int,
    server_name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    try:
        return discover_mcp_tools(project_id, server_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP Server 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
