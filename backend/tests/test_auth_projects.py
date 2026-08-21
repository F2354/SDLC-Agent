import uuid


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


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


def test_create_project_and_flow(client):
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

    started = client.post(
        f"/api/projects/{project_id}/stages/requirements/start",
        headers=headers,
        json={"mode": "auto"},
    )
    assert started.status_code == 400

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
