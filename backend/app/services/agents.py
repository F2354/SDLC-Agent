"""Project-local Agent profiles and tool permission policy.

The format is compatible with the common agent configuration shape used by
coding agents, while keeping execution inside this application's tool runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.session import SessionLocal
from app.models.project import Project

_CONFIG_PATHS = (".sdlc/agents.json", ".opencode/agents.json", "agents.json")
_DEFAULT_PERMISSIONS = {"read": "allow", "edit": "ask", "bash": "ask", "git": "ask"}


def _root(project_id: int) -> Path:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
    if project is None or not project.folder:
        raise ValueError("项目工作区不存在")
    return Path(project.folder).resolve()


def _load(project_id: int) -> dict[str, Any]:
    root = _root(project_id)
    for relative in _CONFIG_PATHS:
        path = root / relative
        if not path.is_file() or path.stat().st_size > 128_000:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("agents"), dict):
            return payload["agents"]
        if isinstance(payload, dict):
            return payload
    return {}


def list_agent_profiles(project_id: int) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for name, raw in _load(project_id).items():
        if not isinstance(raw, dict):
            continue
        permissions = dict(_DEFAULT_PERMISSIONS)
        configured = raw.get("permissions", {})
        if isinstance(configured, dict):
            permissions.update({str(key): str(value) for key, value in configured.items()})
        profiles.append({
            "name": str(name),
            "mode": str(raw.get("mode", "subagent")),
            "model": str(raw["model"]) if raw.get("model") else None,
            "description": str(raw.get("description", "")),
            "permissions": permissions,
        })
    return profiles


def get_agent_permissions(project_id: int, agent_name: str) -> dict[str, str]:
    for profile in list_agent_profiles(project_id):
        if profile["name"] == agent_name:
            return profile["permissions"]
    return dict(_DEFAULT_PERMISSIONS)


def agent_context(project_id: int) -> str:
    return "\n\n".join(
        f"## Agent: {item['name']}\n{item['description']}\nPermissions: {json.dumps(item['permissions'], ensure_ascii=False)}"
        for item in list_agent_profiles(project_id)
    )
