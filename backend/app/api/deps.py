from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models.llm_provider import LLMProvider
from app.models.project import Project
from app.models.stage_run import Artifact, StageRun
from app.models.user import User
from app.services.security import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is not None:
        try:
            user_id = decode_access_token(credentials.credentials)
        except TokenError:
            user_id = None
        if user_id is not None:
            user = db.get(User, user_id)
            if user is not None:
                return user

    if not settings.allow_local_user_fallback:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证或凭证无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 本地单机模式（仅开发环境）：未携带有效 token 时使用内置本地用户。
    user = db.scalar(select(User).where(User.username == "local"))
    if user is None:
        # 不可登录的占位 hash，避免空 hash 触发 bcrypt 异常。
        user = User(username="local", display_name="本地用户", password_hash="!")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 资源读取：本应用是「单工作区 + 登录门禁」。
#
# 登录只用来回答"谁在操作"，不用来隔离数据 —— 与常见的本地 coding agent
# 一致。所有登录用户共享同一批项目与 Provider，因此这里只做存在性校验，
# 不再比对 owner_id。owner_id / user_id 字段保留，仅作为创建者记录。
# ---------------------------------------------------------------------------


def get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.process_model))
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


def get_artifact_or_404(artifact_id: int, db: Session) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    return artifact


def get_stage_run_or_404(run_id: int, db: Session) -> StageRun:
    run = db.get(StageRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="阶段运行记录不存在"
        )
    return run


def get_provider_or_404(provider_id: int, db: Session) -> LLMProvider:
    provider = db.scalar(
        select(LLMProvider)
        .where(LLMProvider.id == provider_id)
        .options(selectinload(LLMProvider.models))
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在"
        )
    return provider
