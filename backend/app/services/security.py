from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    """校验密码。空 hash 或畸形 hash 一律视为校验失败，避免 500。"""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


class TokenError(Exception):
    """token 缺失、过期或签名无效。"""


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenError("凭证无效或已过期") from exc
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("凭证无效或已过期") from exc
