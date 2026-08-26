from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is not None:
        try:
            user = db.get(User, decode_access_token(credentials.credentials))
            if user is not None:
                return user
        except Exception:
            pass

    # 本地单机模式：未携带 token 时自动使用内置本地用户。
    user = db.scalar(select(User).where(User.username == "local"))
    if user is None:
        user = User(username="local", display_name="本地用户", password_hash="")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
