"""M10：编排升级、评审 Agent、追溯关系与双模式阶段。"""
import uuid

from app.db.session import SessionLocal
from app.models.stage_run import Artifact, Review, StageRun

TRACEABILITY_DOC = (
    "### 需求条目 RQ-001\n实现用户登录\n\n"
    "### 用例 UC-001\n登录用例，来源 RQ-001\n\n"
    "### 模块 MOD-001\n登录模块，实现 RQ-001 与 UC-001\n\n"
    "### 测试用例 TC-001\n验证 RQ-001 与 MOD-001\n"
)


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register(client, prefix: str) -> dict:
    username = unique_name(prefix)
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _create_project(client, headers: dict, folder: str, model: str = "waterfall") -> int:
    created = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": unique_name("编排"),
            "process_model_code": model,
            "folder": folder,
        },
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_provider(client, headers: dict) -> None:
    response = client.post(
        "/api/providers",
        headers=headers,
        json={
            "name": unique_name("provider"),
            "type": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "sk-test",
            "default_model": "demo-model",
        },
    )
    assert response.status_code == 201


def test_traceability_links_and_coverage(client, project_folder):
    headers = _register(client, "trace")
    project_id = _create_project(client, headers, project_folder)
    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers)
    stage_id = flow.json()["stages"][0]["stage"]["id"]

    with SessionLocal() as db:
        run = StageRun(
            project_id=project_id,
            stage_id=stage_id,
            status="awaiting_review",
            mode="auto",
        )
        db.add(run)
        db.flush()
        artifact = Artifact(
            project_id=project_id,
            stage_run_id=run.id,
            type="requirements",
            title="需求文档",
            content_md="占位",
            current_version=1,
            status="awaiting_review",
        )
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id

    updated = client.patch(
        f"/api/artifacts/{artifact_id}",
        headers=headers,
        json={"content_md": TRACEABILITY_DOC},
    )
    assert updated.status_code == 200

    trace = client.get(f"/api/projects/{project_id}/traceability", headers=headers)
    assert trace.status_code == 200
    body = trace.json()

    relations = {
        (link["from_key"], link["to_type"], link["to_key"]) for link in body["links"]
    }
    assert ("RQ-001", "UC", "UC-001") in relations
    assert ("RQ-001", "MOD", "MOD-001") in relations
    assert ("UC-001", "MOD", "MOD-001") in relations
    assert ("RQ-001", "TC", "TC-001") in relations
    assert ("MOD-001", "TC", "TC-001") in relations

    coverage = body["coverage"]
    assert coverage["rq_total"] == 1
    assert coverage["rq_with_uc"] == 1
    assert coverage["rq_with_mod"] == 1
    assert coverage["rq_with_tc"] == 1
    assert coverage["mod_with_tc"] == 1
    assert coverage["unresolved"] == []
    assert body["entity_counts"]["RQ"] == 1
    assert body["entity_counts"]["TC"] == 1


def test_traceability_reports_unresolved_reference(client, project_folder):
    headers = _register(client, "unresolved")
    project_id = _create_project(client, headers, project_folder)
    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers)
    stage_id = flow.json()["stages"][0]["stage"]["id"]

    with SessionLocal() as db:
        run = StageRun(
            project_id=project_id, stage_id=stage_id, status="awaiting_review", mode="auto"
        )
        db.add(run)
        db.flush()
        artifact = Artifact(
            project_id=project_id,
            stage_run_id=run.id,
            type="architecture",
            title="设计文档",
            content_md="占位",
            current_version=1,
            status="awaiting_review",
        )
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id

    client.patch(
        f"/api/artifacts/{artifact_id}",
        headers=headers,
        json={
            "content_md": (
                "### 模块 MOD-001\n实现登录，对应需求 RQ-404（原文未定义）\n"
            )
        },
    )

    trace = client.get(f"/api/projects/{project_id}/traceability", headers=headers)
    body = trace.json()
    assert "RQ-404" in body["coverage"]["unresolved"]
    assert any("未定义" in warning for warning in body["warnings"])


def test_review_endpoint_exposes_agent_suggestion(client, project_folder):
    headers = _register(client, "review")
    project_id = _create_project(client, headers, project_folder)
    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers)
    stage_id = flow.json()["stages"][0]["stage"]["id"]

    with SessionLocal() as db:
        run = StageRun(
            project_id=project_id, stage_id=stage_id, status="awaiting_review", mode="auto"
        )
        db.add(run)
        db.flush()
        db.add(
            Review(
                stage_run_id=run.id,
                reviewer_type="agent",
                result="suggested",
                comment="检查清单：需求编号缺失，建议补充 RQ-002。",
            )
        )
        db.commit()
        run_id = run.id

    response = client.get(f"/api/stage-runs/{run_id}/review", headers=headers)
    assert response.status_code == 200
    reviews = response.json()
    assert len(reviews) == 1
    assert reviews[0]["reviewer_type"] == "agent"
    assert "需求编号缺失" in reviews[0]["comment"]


def test_auto_advance_toggle_persists(client, project_folder):
    headers = _register(client, "advance")
    project_id = _create_project(client, headers, project_folder)

    response = client.patch(
        f"/api/projects/{project_id}",
        headers=headers,
        json={"auto_advance": True},
    )
    assert response.status_code == 200
    assert response.json()["auto_advance"] is True

    fetched = client.get(f"/api/projects/{project_id}", headers=headers)
    assert fetched.json()["auto_advance"] is True


def test_chat_mode_available_for_non_requirements_stage(client, project_folder):
    headers = _register(client, "chatstage")
    project_id = _create_project(client, headers, project_folder)
    _add_provider(client, headers)

    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers)
    stages = flow.json()["stages"]
    requirements_stage_id = stages[0]["stage"]["id"]

    # 直接落库一条已通过的需求阶段运行，绕过 LLM 依赖。
    with SessionLocal() as db:
        db.add(
            StageRun(
                project_id=project_id,
                stage_id=requirements_stage_id,
                status="approved",
                mode="auto",
            )
        )
        db.commit()

    started = client.post(
        f"/api/projects/{project_id}/stages/architecture/start",
        headers=headers,
        json={"mode": "chat"},
    )
    assert started.status_code == 201
    body = started.json()
    assert body["status"] == "collecting"
    assert body["stage_code"] == "architecture"

    messages = client.get(f"/api/stage-runs/{body['id']}/messages", headers=headers)
    assert messages.status_code == 200
    assert len(messages.json()) == 1
    assert "架构师" in messages.json()[0]["content"]


def test_event_bus_delivers_across_threads():
    """阶段运行在线程池中发布事件，订阅端运行在事件循环中，必须能收到。"""
    import asyncio

    from app.services import event_bus

    project_id = 987_654

    async def scenario() -> dict:
        previous = event_bus.current_event_loop()
        event_bus.set_event_loop(asyncio.get_running_loop())
        queue = event_bus.subscribe(project_id)
        try:
            await asyncio.to_thread(
                event_bus.publish, project_id, "stage_status", {"status": "generating"}
            )
            payload = await asyncio.wait_for(queue.get(), timeout=5)
        finally:
            event_bus.unsubscribe(project_id, queue)
            event_bus.set_event_loop(previous)
        return payload

    payload = asyncio.run(scenario())
    assert payload["event"] == "stage_status"
    assert payload["data"]["status"] == "generating"
    assert event_bus.subscriber_count(project_id) == 0


def test_code_stage_rejects_chat_mode(client, project_folder):
    headers = _register(client, "codemode")
    project_id = _create_project(client, headers, project_folder)
    _add_provider(client, headers)

    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers)
    stages = flow.json()["stages"]
    coding_index = next(
        index for index, item in enumerate(stages) if item["stage"]["code"] == "coding"
    )
    # 通过顺序校验需要前置阶段均已完成。
    with SessionLocal() as db:
        for item in stages[:coding_index]:
            db.add(
                StageRun(
                    project_id=project_id,
                    stage_id=item["stage"]["id"],
                    status="approved",
                    mode="auto",
                )
            )
        db.commit()

    response = client.post(
        f"/api/projects/{project_id}/stages/coding/start",
        headers=headers,
        json={"mode": "chat"},
    )
    assert response.status_code == 400
    assert "自动模式" in response.json()["detail"]
