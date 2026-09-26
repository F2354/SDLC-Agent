"""Agent 级模型解析（多模型切换）的接线验证。

覆盖的是一条真实的执行链：
    项目内 agents.json → resolve_agent_model → 生效的 (Provider, 模型名)

而不是只验证"接口存在"。
"""

import json
import os
import uuid

from app.db.session import SessionLocal
from app.models.llm_provider import LLMProvider
from app.services.agents import resolve_agent_model
from app.services.stage_service import stage_agent_code


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _write_agents_config(folder: str, payload: dict) -> None:
    target = os.path.join(folder, ".sdlc")
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, "agents.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _make_provider(db, user_id: int, name: str, default_model: str) -> LLMProvider:
    provider = LLMProvider(
        user_id=user_id,
        name=name,
        type="openai_compatible",
        base_url="https://example.com/v1",
        default_model=default_model,
        enabled=True,
    )
    db.add(provider)
    db.flush()
    return provider


def _setup_project(client, project_folder: str, agents_config: dict | None = None):
    """注册用户 + 创建项目，可选写入 agents.json。返回 (user_id, project_id)。"""
    username = unique_name("model_owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "模型解析测试",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    ).json()
    if agents_config is not None:
        _write_agents_config(project_folder, agents_config)
    return user_id, project["id"]


def test_stage_agent_code_maps_stages_to_roles():
    assert stage_agent_code("requirements") == "requirements_analyst"
    assert stage_agent_code("coding") == "developer"
    assert stage_agent_code("unit-test") == "tester"
    assert stage_agent_code("sprint-review") == "coordinator"
    # 未知阶段回退到统筹角色，避免 KeyError。
    assert stage_agent_code("unknown-stage") == "coordinator"


def test_resolve_agent_model_falls_back_without_config(client, project_folder):
    """未配置 agents.json 时，沿用 Provider 默认模型。"""
    user_id, project_id = _setup_project(client, project_folder)

    with SessionLocal() as db:
        provider = _make_provider(db, user_id, "main", "base-model")
        db.commit()
        resolved_provider, model = resolve_agent_model(
            db, project_id, "developer", provider
        )

    assert resolved_provider.id == provider.id
    assert model == "base-model"


def test_resolve_agent_model_overrides_model_name(client, project_folder):
    """配置 "model-name" 时，沿用 Provider 但覆盖模型名。"""
    user_id, project_id = _setup_project(
        client,
        project_folder,
        {"agents": {"developer": {"model": "code-model"}}},
    )

    with SessionLocal() as db:
        provider = _make_provider(db, user_id, "main", "base-model")
        db.commit()
        resolved_provider, model = resolve_agent_model(
            db, project_id, "developer", provider
        )

    assert resolved_provider.id == provider.id
    assert model == "code-model"


def test_resolve_agent_model_switches_provider(client, project_folder):
    """配置 "provider/model" 时，切换到同用户下同名的 Provider。"""
    user_id, project_id = _setup_project(
        client,
        project_folder,
        {"agents": {"reviewer": {"model": "review/reasoning-model"}}},
    )

    with SessionLocal() as db:
        main = _make_provider(db, user_id, "main", "base-model")
        review = _make_provider(db, user_id, "review", "review-default")
        db.commit()
        main_id = main.id
        review_id = review.id
        resolved_provider, model = resolve_agent_model(db, project_id, "reviewer", main)

    assert resolved_provider.id == review_id
    assert resolved_provider.id != main_id
    assert model == "reasoning-model"


def test_resolve_agent_model_unknown_provider_keeps_model(client, project_folder):
    """Provider 名不存在时，不静默丢弃模型名，退化为「当前 Provider + 该模型名」。"""
    user_id, project_id = _setup_project(
        client,
        project_folder,
        {"agents": {"developer": {"model": "ghost/model-x"}}},
    )

    with SessionLocal() as db:
        provider = _make_provider(db, user_id, "main", "base-model")
        db.commit()
        resolved_provider, model = resolve_agent_model(
            db, project_id, "developer", provider
        )

    assert resolved_provider.id == provider.id
    assert model == "model-x"


def test_resolve_agent_model_isolates_roles(client, project_folder):
    """只覆盖被配置的角色，其它角色仍走默认模型。"""
    user_id, project_id = _setup_project(
        client,
        project_folder,
        {"agents": {"architect": {"model": "arch-model"}}},
    )

    with SessionLocal() as db:
        provider = _make_provider(db, user_id, "main", "base-model")
        db.commit()
        _, architect_model = resolve_agent_model(db, project_id, "architect", provider)
        _, developer_model = resolve_agent_model(db, project_id, "developer", provider)

    assert architect_model == "arch-model"
    assert developer_model == "base-model"


def test_disabled_provider_is_not_selected(client, project_folder):
    """停用的 Provider 不应被切换选中，避免阶段跑到不可用的服务上。"""
    user_id, project_id = _setup_project(
        client,
        project_folder,
        {"agents": {"developer": {"model": "retired/model-y"}}},
    )

    with SessionLocal() as db:
        main = _make_provider(db, user_id, "main", "base-model")
        retired = _make_provider(db, user_id, "retired", "retired-default")
        retired.enabled = False
        db.commit()
        retired_id = retired.id
        main_id = main.id
        resolved_provider, model = resolve_agent_model(db, project_id, "developer", main)

    assert resolved_provider.id == main_id
    assert resolved_provider.id != retired_id
    assert model == "model-y"
