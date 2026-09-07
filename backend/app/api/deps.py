from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
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
