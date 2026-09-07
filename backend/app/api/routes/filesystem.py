import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/filesystem", tags=["filesystem"])

# 需要隐藏的敏感目录名（大小写不敏感）。
_HIDDEN_NAMES = {".git", ".ssh", ".aws", ".venv", "node_modules", "__pycache__"}


class FsEntry(BaseModel):
    name: str
    path: str


class FsBrowseOut(BaseModel):
    path: str
    parent: str | None
    entries: list[FsEntry]


def _browse_root() -> Path | None:
    root = (settings.fs_browse_root or "").strip()
    if not root:
        return None
    return Path(root).resolve()


def _resolve_target(path: str) -> Path:
    """解析浏览目标，并限制在配置的根目录内（若已配置）。"""
    root = _browse_root()

    if not path.strip():
        if root is not None:
            return root
        if os.name == "nt":
            return None  # 无限制时展示盘符列表
        return Path("/")

    target = Path(path).resolve()
    if root is not None and root not in target.parents and target != root:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"只允许浏览 {root} 下的目录",
        )
    return target


def _list_dir(target: Path) -> list[FsEntry]:
    entries: list[FsEntry] = []
    try:
        children = [
            child
            for child in target.iterdir()
            if child.is_dir() and child.name.lower() not in _HIDDEN_NAMES
        ]
    except OSError:
        return entries
    children.sort(key=lambda child: child.name.lower())
    return [FsEntry(name=child.name, path=str(child)) for child in children]


@router.get("", response_model=FsBrowseOut)
def browse(
    path: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _resolve_target(path)

    if target is None:
        drives = [
            f"{letter}:\\"
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if Path(f"{letter}:\\").exists()
        ]
        return FsBrowseOut(
            path="",
            parent=None,
            entries=[FsEntry(name=drive, path=drive) for drive in drives],
        )

    parent = str(target.parent) if target.parent != target else None
    root = _browse_root()
    if root is not None and (parent is None or Path(parent).resolve() == target):
        parent = None
    return FsBrowseOut(
        path=str(target),
        parent=parent,
        entries=_list_dir(target),
    )
