import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/filesystem", tags=["filesystem"])


class FsEntry(BaseModel):
    name: str
    path: str


class FsBrowseOut(BaseModel):
    path: str
    parent: str | None
    entries: list[FsEntry]


def _list_dir(target: Path) -> list[FsEntry]:
    entries: list[FsEntry] = []
    try:
        children = [child for child in target.iterdir() if child.is_dir()]
    except OSError:
        return entries
    children.sort(key=lambda child: child.name.lower())
    return [FsEntry(name=child.name, path=str(child)) for child in children]


@router.get("", response_model=FsBrowseOut)
def browse(path: str = ""):
    if not path.strip():
        if os.name == "nt":
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
        target = Path("/")
    else:
        target = Path(path)

    parent = str(target.parent) if target.parent != target else None
    return FsBrowseOut(
        path=str(target),
        parent=parent,
        entries=_list_dir(target),
    )
