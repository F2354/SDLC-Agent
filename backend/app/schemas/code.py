from pydantic import BaseModel


class CodeFileOut(BaseModel):
    path: str
    size: int


class CodeTreeOut(BaseModel):
    exists: bool
    files: list[CodeFileOut]


class CodeRunOut(BaseModel):
    ok: bool
    phase: str
    output: str
