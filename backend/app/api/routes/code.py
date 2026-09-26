from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_project_or_404
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.code import CodeFileUpdate, CodeRunOut, CodeTreeOut, GitCommitOut, GitCommitRequest, GitLogEntryOut, GitStatusOut
from app.services.code_service import git_commit, git_diff, git_log, git_status, init_git_repo, list_code_files, read_code_file, run_tests, run_verify, write_code_file

router = APIRouter(prefix="/projects/{project_id}/code", tags=["code"])


@router.get("/git/status", response_model=GitStatusOut)
def get_git_status(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    return git_status(project_id)


@router.post("/git/init", response_model=GitStatusOut)
def initialize_git(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    try:
        return init_git_repo(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/git/log", response_model=list[GitLogEntryOut])
def get_git_log(
    project_id: int,
    limit: int = 12,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    return git_log(project_id, limit)


@router.post("/git/commit", response_model=GitCommitOut)
def create_git_commit(
    project_id: int,
    payload: GitCommitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    try:
        return git_commit(project_id, payload.message)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/git/diff")
def get_git_diff(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    try:
        return Response(content=git_diff(project_id), media_type="text/plain; charset=utf-8")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tree", response_model=CodeTreeOut)
def get_code_tree(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    return list_code_files(project_id)


@router.get("/file")
def get_code_file(
    project_id: int,
    path: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    try:
        content = read_code_file(project_id, path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    except ValueError:
        # _safe_path 拒绝工作区外的路径（路径穿越）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径不合法")
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.post("/file")
def save_code_file(
    project_id: int,
    payload: CodeFileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    try:
        path = write_code_file(project_id, payload.path, payload.content)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径不合法")
    return {"path": path, "saved": True}


@router.post("/run", response_model=CodeRunOut)
def verify_project_code(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    return run_verify(project_id)


@router.post("/test", response_model=CodeRunOut)
def run_project_tests(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    return run_tests(project_id)
