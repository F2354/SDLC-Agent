from pydantic import BaseModel, Field


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


class GitStatusOut(BaseModel):
    is_repo: bool
    branch: str
    clean: bool
    changed_files: int
    files: list[str] = []


class CodeFileUpdate(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)


class GitLogEntryOut(BaseModel):
    commit: str
    author: str
    date: str
    subject: str


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=200)


class GitCommitOut(BaseModel):
    created: bool
    commit: str
    message: str
