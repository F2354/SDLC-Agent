"""Project-local Agent profiles and tool permission policy.

The format is compatible with the common agent configuration shape used by
coding agents, while keeping execution inside this application's tool runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.llm_provider import LLMProvider
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


def get_agent_profile(project_id: int, agent_name: str) -> dict[str, Any] | None:
    """按名称取单个 agent 档案，未配置时返回 None。"""
    for profile in list_agent_profiles(project_id):
        if profile["name"] == agent_name:
            return profile
    return None


def _find_enabled_provider(db: Session, name: str) -> LLMProvider | None:
    """按名称查找已启用的 Provider（Provider 在单工作区内共享）。"""
    return db.scalar(
        select(LLMProvider)
        .where(
            LLMProvider.name == name,
            LLMProvider.enabled.is_(True),
        )
        .order_by(LLMProvider.id)
    )


def resolve_agent_model(
    db: Session,
    project_id: int,
    agent_code: str,
    default_provider: LLMProvider,
) -> tuple[LLMProvider, str]:
    """解析某个 agent 角色实际生效的 ``(Provider, 模型名)``。

    读取项目内 ``agents.json`` 的 ``model`` 字段，支持两种写法：

    - ``"model-name"``：沿用传入的 Provider，仅覆盖模型名。
    - ``"provider-name/model-name"``：切换到同一用户下同名的 Provider 并使用该模型；
      Provider 不存在或已停用时，退化为「沿用当前 Provider + 该模型名」。

    未配置 model、写法为空或无法解析时，回退到 Provider 的默认模型。
    """
    fallback: tuple[LLMProvider, str] = (default_provider, default_provider.default_model)

    profile = get_agent_profile(project_id, agent_code)
    if profile is None:
        return fallback

    raw = str(profile.get("model") or "").strip()
    if not raw:
        return fallback

    if "/" in raw:
        provider_name, _, model_name = raw.partition("/")
        provider_name = provider_name.strip()
        model_name = model_name.strip()
        if not model_name:
            return fallback
        candidate = _find_enabled_provider(db, provider_name)
        return (candidate or default_provider), model_name

    return default_provider, raw
