"""Project-local Skills loader inspired by SKILL.md conventions.

Skills are intentionally filesystem based: teams can add or review them in Git,
and the loader never executes skill scripts automatically. Only the Markdown
instructions and front-matter metadata are exposed to the Agent runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.session import SessionLocal
from app.models.project import Project

_MAX_SKILL_BYTES = 256_000
_SKILL_ROOT_RELATIVE_PATHS = (".sdlc/skills", ".opencode/skills", "skills")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: str
    source: str
    content: str
    metadata: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "source": self.source,
            "metadata": self.metadata,
        }


def _project_root(project_id: int) -> Path:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
    if project is None or not project.folder:
        raise ValueError("项目工作区不存在")
    return Path(project.folder).resolve()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(item) for item in value[1:-1].split(",") if item.strip()]
    return value


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}, text
    metadata: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_scalar(value)
    body = "\n".join(lines[end + 1:]).strip()
    return metadata, body


def _skill_files(root: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for relative in _SKILL_ROOT_RELATIVE_PATHS:
        skill_root = root / relative
        if not skill_root.is_dir():
            continue
        for path in sorted(skill_root.rglob("SKILL.md")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                path.relative_to(root)
            except ValueError:
                continue
            files.append((path, relative))
    return files


def _load_skill(path: Path, source: str, root: Path) -> Skill | None:
    if path.stat().st_size > _MAX_SKILL_BYTES:
        return None
    raw = path.read_text(encoding="utf-8")
    metadata, body = _front_matter(raw)
    fallback_name = path.parent.name
    name = str(metadata.get("name") or fallback_name).strip()
    description = str(metadata.get("description") or "").strip()
    if not _NAME_RE.match(name) or not description or not body:
        return None
    return Skill(
        name=name,
        description=description,
        path=path.relative_to(root).as_posix(),
        source=source,
        content=body,
        metadata=metadata,
    )


def list_project_skills(project_id: int) -> list[Skill]:
    root = _project_root(project_id)
    skills: list[Skill] = []
    seen_names: set[str] = set()
    for path, source in _skill_files(root):
        skill = _load_skill(path, source, root)
        if skill is None or skill.name in seen_names:
            continue
        seen_names.add(skill.name)
        skills.append(skill)
    return skills


def get_project_skill(project_id: int, name: str) -> Skill:
    for skill in list_project_skills(project_id):
        if skill.name == name:
            return skill
    raise FileNotFoundError(name)


def skill_context(project_id: int, query: str | None = None, limit: int = 4) -> str:
    """Return compact instructions for matching skills; full content is opt-in."""
    skills = list_project_skills(project_id)
    if query:
        terms = {term.lower() for term in re.findall(r"[\w-]+", query) if len(term) > 2}
        skills.sort(
            key=lambda skill: sum(
                term in f"{skill.name} {skill.description}".lower() for term in terms
            ),
            reverse=True,
        )
    selected = skills[: max(0, min(limit, 10))]
    return "\n\n".join(
        f"## Skill: {skill.name}\n{skill.description}\n\n{skill.content}" for skill in selected
    )
