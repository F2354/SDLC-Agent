import uuid

from app.db.session import SessionLocal
from app.models.stage_run import ActivityEvent, Artifact, StageRun


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_artifact_edit_and_activity(client):
    username = unique_name("artifact_owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "产物修订测试", "process_model_code": "waterfall"},
    )
    project_id = project.json()["id"]
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
            content_md="v1 内容",
            current_version=1,
            status="awaiting_review",
        )
        db.add(artifact)
        db.add(
            ActivityEvent(
                project_id=project_id,
                stage_run_id=run.id,
                event_type="artifact_saved",
                message="需求文档已生成",
            )
        )
        db.commit()
        artifact_id = artifact.id

    events = client.get(f"/api/projects/{project_id}/activity-events", headers=headers)
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["event_type"] == "artifact_saved"

    updated = client.patch(
        f"/api/artifacts/{artifact_id}",
        headers=headers,
        json={
            "content_md": (
                "v2 修订内容\n"
                "### 需求条目 RQ-001\n"
                "### 用例 UC-001\n"
                "### 模块 MOD-001\n"
                "### 测试用例 TC-001"
            )
        },
    )
    assert updated.status_code == 200
    assert updated.json()["current_version"] == 2
    assert "RQ-001" in updated.json()["content_md"]

    trace = client.get(f"/api/projects/{project_id}/traceability", headers=headers)
    assert trace.status_code == 200
    assert trace.json()["entity_counts"]["RQ"] >= 1
    assert trace.json()["entity_counts"]["TC"] >= 1

    stats = client.get(f"/api/projects/{project_id}/stats", headers=headers)
    assert stats.status_code == 200
    assert stats.json()["artifact_count"] == 1
    assert stats.json()["total_chars"] > 10

    docx = client.get(f"/api/artifacts/{artifact_id}/export", headers=headers)
    assert docx.status_code == 200
    assert "wordprocessingml" in docx.headers["content-type"]

    pdf = client.get(
        f"/api/artifacts/{artifact_id}/export?format=pdf",
        headers=headers,
    )
    assert pdf.status_code == 200
    assert "application/pdf" in pdf.headers["content-type"]
