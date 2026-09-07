from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.code import CodeRunOut, CodeTreeOut
from app.services.code_service import list_code_files, read_code_file, run_tests, run_verify

router = APIRouter(prefix="/projects/{project_id}/code", tags=["code"])


def get_owned_project(project_id: int, user: User, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.get("/tree", response_model=CodeTreeOut)
def get_code_tree(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    return list_code_files(project_id)


@router.get("/file")
def get_code_file(
    project_id: int,
    path: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    try:
        content = read_code_file(project_id, path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    except ValueError:
        # _safe_path 拒绝工作区外的路径（路径穿越）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径不合法")
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.post("/run", response_model=CodeRunOut)
def verify_project_code(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    return run_verify(project_id)


@router.post("/test", response_model=CodeRunOut)
def run_project_tests(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(project_id, user, db)
    return run_tests(project_id)
