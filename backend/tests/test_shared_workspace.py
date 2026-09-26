"""单工作区语义验证。

登录只回答"谁在操作"，不用来隔离数据：所有登录用户共享同一批项目与
Provider，与常见的本地 coding agent 一致。

这里验证跨用户可见、可操作，以及免登录的 local 用户能看到全部项目 ——
后者直接决定"打开界面能不能看到完整案例"。
"""

import uuid

from app.db.session import SessionLocal
from app.models.stage_run import Artifact, StageRun


def _register(client, prefix: str) -> dict:
    reg = client.post(
        "/api/auth/register",
        json={"username": f"{prefix}_{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _create_project(client, headers: dict, folder: str, name: str) -> dict:
    response = client.post(
        "/api/projects",
        headers=headers,
        json={"name": name, "process_model_code": "waterfall", "folder": folder},
    )
    assert response.status_code == 201
    return response.json()


def _create_provider(client, headers: dict, name: str) -> dict:
    response = client.post(
        "/api/providers",
        headers=headers,
        json={
            "name": name,
            "type": "openai_compatible",
            "base_url": "https://example.com/v1",
            "api_key": "sk-test-key-000",
            "default_model": "demo-model",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_project_created_by_one_user_is_visible_to_another(client, project_folder):
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    project = _create_project(client, alice, project_folder, "Alice 的项目")

    listed = client.get("/api/projects", headers=bob)
    assert listed.status_code == 200
    assert project["id"] in {item["id"] for item in listed.json()}

    detail = client.get(f"/api/projects/{project['id']}", headers=bob)
    assert detail.status_code == 200
    assert detail.json()["name"] == "Alice 的项目"


def test_another_user_can_update_project_and_read_flow(client, project_folder):
    alice = _register(client, "alice2")
    bob = _register(client, "bob2")
    project = _create_project(client, alice, project_folder, "共享项目")

    patched = client.patch(
        f"/api/projects/{project['id']}", headers=bob, json={"auto_advance": True}
    )
    assert patched.status_code == 200
    assert patched.json()["auto_advance"] is True

    flow = client.get(f"/api/projects/{project['id']}/flow", headers=bob)
    assert flow.status_code == 200
    assert len(flow.json()["stages"]) == 5


def test_creator_is_still_recorded_even_though_it_does_not_gate_access(
    client, project_folder
):
    """owner_id 保留为创建者记录，但不再参与鉴权。"""
    alice = _register(client, "alice3")
    project = _create_project(client, alice, project_folder, "记录创建者")

    me = client.get("/api/auth/me", headers=alice).json()
    assert project["owner_id"] == me["id"]


def test_providers_are_shared_across_users(client):
    alice = _register(client, "alice_p")
    bob = _register(client, "bob_p")
    provider = _create_provider(client, alice, f"alice_{uuid.uuid4().hex[:6]}")

    visible = client.get("/api/providers", headers=bob)
    assert visible.status_code == 200
    assert provider["id"] in {item["id"] for item in visible.json()}

    updated = client.patch(
        f"/api/providers/{provider['id']}", headers=bob, json={"name": "改名了"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名了"


def test_artifacts_and_stage_runs_are_shared(client, project_folder):
    alice = _register(client, "alice_art")
    bob = _register(client, "bob_art")
    project = _create_project(client, alice, project_folder, "共享产物")
    flow = client.get(f"/api/projects/{project['id']}/flow", headers=alice).json()
    stage_id = flow["stages"][0]["stage"]["id"]

    with SessionLocal() as db:
        run = StageRun(
            project_id=project["id"],
            stage_id=stage_id,
            status="awaiting_review",
            mode="auto",
        )
        db.add(run)
        db.flush()
        artifact = Artifact(
            project_id=project["id"],
            stage_run_id=run.id,
            type="requirements",
            title="需求分析文档",
            content_md="内容",
            current_version=1,
            status="awaiting_review",
        )
        db.add(artifact)
        db.commit()
        run_id, artifact_id = run.id, artifact.id

    assert client.get(f"/api/stage-runs/{run_id}", headers=bob).status_code == 200

    edited = client.patch(
        f"/api/artifacts/{artifact_id}", headers=bob, json={"content_md": "Bob 改的"}
    )
    assert edited.status_code == 200
    assert edited.json()["current_version"] == 2
    assert edited.json()["content_md"] == "Bob 改的"


def test_local_fallback_user_sees_projects_of_everyone(client, project_folder):
    """免登录的 local 用户应能看到他人创建的项目。

    这是"打开界面几乎没东西可看"那个问题的直接修复：
    此前项目按 owner 隔离，演示数据散落在 4 个用户下。
    """
    alice = _register(client, "alice_local")
    project = _create_project(client, alice, project_folder, "完整案例")

    # 不带 Authorization 头：开发环境降级为内置 local 用户。
    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert project["id"] in {item["id"] for item in listed.json()}

    detail = client.get(f"/api/projects/{project['id']}")
    assert detail.status_code == 200

    providers = client.get("/api/providers")
    assert providers.status_code == 200
