import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.llm_provider import LLMProvider


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _set_all_providers_enabled(enabled: bool) -> None:
    with SessionLocal() as db:
        for provider in db.scalars(select(LLMProvider)):
            provider.enabled = enabled
        db.commit()


def test_register_login_and_me(client):
    username = unique_name("user")
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "display_name": "测试用户",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == username

    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert login.status_code == 200


def test_create_project_and_flow(client, project_folder):
    username = unique_name("owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "图书管理系统",
            "description": "毕业设计案例",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers)
    assert flow.status_code == 200
    body = flow.json()
    assert len(body["stages"]) == 5
    assert body["stages"][0]["stage"]["code"] == "requirements"
    assert body["stages"][0]["status"] == "pending"

    # 单工作区下 Provider 是共享的，"无可用 Provider" 取决于整个工作区的状态，
    # 因此这里在数据库层面临时停用全部 Provider 来验证该守卫。
    _set_all_providers_enabled(False)
    try:
        started = client.post(
            f"/api/projects/{project_id}/stages/requirements/start",
            headers=headers,
            json={"mode": "auto"},
        )
        assert started.status_code == 400
        assert "Provider" in started.json()["detail"]
    finally:
        _set_all_providers_enabled(True)

    artifacts = client.get(f"/api/projects/{project_id}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    assert artifacts.json() == []

    provider = client.post(
        "/api/providers",
        headers=headers,
        json={
            "name": "测试 Provider",
            "type": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "sk-test",
            "default_model": "mimo-v2.5",
        },
    )
    assert provider.status_code == 201

    chat_run = client.post(
        f"/api/projects/{project_id}/stages/requirements/start",
        headers=headers,
        json={"mode": "chat"},
    )
    assert chat_run.status_code == 201
    assert chat_run.json()["status"] == "collecting"

    messages = client.get(
        f"/api/stage-runs/{chat_run.json()['id']}/messages",
        headers=headers,
    )
    assert messages.status_code == 200
    assert len(messages.json()) == 1
    assert messages.json()[0]["role"] == "agent"

    approve = client.post(
        f"/api/stage-runs/{chat_run.json()['id']}/approve",
        headers=headers,
        json={"comment": ""},
    )
    assert approve.status_code == 400


def test_process_models_include_v_model(client):
    response = client.get("/api/process-models")
    assert response.status_code == 200
    models = response.json()
    codes = [model["code"] for model in models]
    assert "waterfall" in codes
    assert "v-model" in codes
    v_model = next(model for model in models if model["code"] == "v-model")
    assert len(v_model["stages"]) == 7


def test_process_models_include_all_models(client):
    response = client.get("/api/process-models")
    assert response.status_code == 200
    models = response.json()
    codes = [model["code"] for model in models]
    expected = ["waterfall", "v-model", "iterative", "spiral", "prototype", "scrum"]
    for code in expected:
        assert code in codes, f"Missing model: {code}"
    expected_stages = {
        "waterfall": 5,
        "v-model": 7,
        "iterative": 6,
        "spiral": 6,
        "prototype": 6,
        "scrum": 5,
    }
    for model in models:
        if model["code"] in expected_stages:
            assert len(model["stages"]) == expected_stages[model["code"]], (
                f"{model['code']} has {len(model['stages'])} stages, expected {expected_stages[model['code']]}"
            )


def test_create_project_with_new_models(client, project_folder):
    """Test creating projects with each new model."""
    for model_code in ["iterative", "spiral", "prototype", "scrum"]:
        response = client.post(
            "/api/projects",
            json={
                "name": f"测试{model_code}",
                "process_model_code": model_code,
                "folder": project_folder,
            },
        )
        assert response.status_code == 201, f"Failed to create project with {model_code}"
        project = response.json()
        assert project["process_model"]["code"] == model_code

        # Verify flow has correct stages
        flow_response = client.get(f"/api/projects/{project['id']}/flow")
        assert flow_response.status_code == 200
        flow = flow_response.json()
        assert len(flow["stages"]) > 0, f"No stages for {model_code}"
        assert all(s["status"] == "pending" for s in flow["stages"])


def test_stage_sequence_enforcement(client, project_folder):
    """Test that stages must be completed in order."""
    # Create project with iterative model
    response = client.post(
        "/api/projects",
        json={
            "name": "顺序测试项目",
            "process_model_code": "iterative",
            "folder": project_folder,
        },
    )
    project_id = response.json()["id"]

    # Try to start second stage without completing first
    stages_response = client.get(f"/api/projects/{project_id}/flow")
    stages = stages_response.json()["stages"]
    second_stage_code = stages[1]["stage"]["code"]

    start_response = client.post(
        f"/api/projects/{project_id}/stages/{second_stage_code}/start",
        json={"mode": "auto"},
    )
    assert start_response.status_code == 400
    assert "请先完成" in start_response.json()["detail"]
