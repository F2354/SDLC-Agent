"""结构化评审清单测试。

此前清单只是评审 Agent 提示词里的一串自然语言，人工评审侧完全没有清单，
结论也无法沉淀。这里验证清单定义、Agent 判定解析、接口返回与审批门禁。
"""

import json
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.process_model import Stage
from app.models.project import Project
from app.models.stage_run import Artifact, Review, StageRun
from app.services.review_checklist import (
    CHECKLISTS,
    build_checklist_instruction,
    item_ids,
    items_for,
    parse_verdicts,
    verdict_summary,
)

ALL_STAGES = [
    "requirements", "architecture", "detailed-design", "coding", "testing",
    "unit-test", "integration-test", "system-test", "risk-analysis", "evaluation",
    "iteration-review", "prototype", "user-feedback", "refinement", "backlog",
    "sprint-planning", "sprint-dev", "sprint-review", "sprint-retrospective",
]


def test_every_stage_has_checklist():
    missing = [code for code in ALL_STAGES if code not in CHECKLISTS]
    assert not missing, f"缺少清单的阶段：{missing}"
    for code in ALL_STAGES:
        items = items_for(code)
        assert items, code
        ids = [item.id for item in items]
        assert len(ids) == len(set(ids)), f"{code} 的检查项 id 重复"


def test_instruction_lists_ids():
    text = build_checklist_instruction("unit-test")
    assert "[unit-paired]" in text
    assert "通过/不通过/不适用" in text


def test_parse_verdicts_accepts_cn_and_en_labels():
    text = (
        "## 检查清单核对\n"
        "- [req-scope] 通过 —— 章节齐全\n"
        "- [req-trace] 不通过 —— 有两项需求没有用例\n"
        "- [req-honest] 不适用 —— 无新增功能\n"
        "- [unknown-id] 通过 —— 应被忽略\n"
        "## 修改建议\n无\n"
    )
    found = parse_verdicts("requirements", text)
    assert found["req-scope"]["verdict"] == "passed"
    assert found["req-trace"]["verdict"] == "failed"
    assert "没有用例" in found["req-trace"]["note"]
    assert found["req-honest"]["verdict"] == "na"
    assert "unknown-id" not in found

    english = "- [req-scope] failed — missing scope"
    assert parse_verdicts("requirements", english)["req-scope"]["verdict"] == "failed"


def test_verdict_summary_counts():
    summary = verdict_summary(
        {
            "a": {"verdict": "passed"},
            "b": {"verdict": "failed"},
            "c": {"verdict": "na"},
        }
    )
    assert "通过 1" in summary and "不通过 1" in summary and "不适用 1" in summary
    assert verdict_summary({}) == "清单未逐项判定"


def _run_awaiting_review(client, folder: str, stage_code: str = "requirements") -> int:
    username = f"checklist_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project_id = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "清单门禁测试",
            "description": "示例",
            "process_model_code": "waterfall",
            "folder": folder,
        },
    ).json()["id"]
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stage = db.scalar(
            select(Stage).where(
                Stage.process_model_id == project.process_model_id,
                Stage.code == stage_code,
            )
        )
        run = StageRun(project_id=project_id, stage_id=stage.id, status="awaiting_review")
        db.add(run)
        db.flush()
        db.add(
            Artifact(
                project_id=project_id,
                stage_run_id=run.id,
                type=stage_code,
                title=f"{stage_code}产物",
                content_md="# 产物\n内容",
                status="awaiting_review",
            )
        )
        db.commit()
        return run.id


def test_checklist_endpoint_returns_items_and_agent_verdicts(client, project_folder):
    run_id = _run_awaiting_review(client, project_folder)
    with SessionLocal() as db:
        db.add(
            Review(
                stage_run_id=run_id,
                reviewer_type="agent",
                result="suggested",
                comment="评审建议",
                checklist_json=json.dumps(
                    {"req-scope": {"verdict": "passed", "note": "章节完整"}},
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()

    resp = client.get(f"/api/stage-runs/{run_id}/checklist")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["stage_code"] == "requirements"
    assert len(payload["items"]) == len(item_ids("requirements"))
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["req-scope"]["verdict"] == "passed"
    assert by_id["req-scope"]["note"] == "章节完整"
    assert by_id["req-trace"]["verdict"] is None  # Agent 未判定
    assert payload["agent"]["req-scope"]["verdict"] == "passed"


def test_approve_blocked_when_checklist_has_failed_item(client, project_folder):
    run_id = _run_awaiting_review(client, project_folder)
    payload = {
        "comment": "看起来还行",
        "checklist": {
            "req-scope": {"verdict": "passed", "note": ""},
            "req-trace": {"verdict": "failed", "note": "需求没有被用例覆盖"},
        },
    }
    resp = client.post(f"/api/stage-runs/{run_id}/approve", json=payload)
    assert resp.status_code == 400
    assert "未通过项" in resp.json()["detail"]

    # 打回不受门禁限制，且清单结论落库
    rejected = client.post(f"/api/stage-runs/{run_id}/reject", json=payload)
    assert rejected.status_code == 200, rejected.text

    with SessionLocal() as db:
        review = db.scalar(
            select(Review)
            .where(Review.stage_run_id == run_id, Review.reviewer_type == "user")
            .order_by(Review.id.desc())
        )
        assert review is not None
        stored = json.loads(review.checklist_json)
        assert stored["req-trace"]["verdict"] == "failed"


def test_approve_passes_when_no_failed_items(client, project_folder):
    run_id = _run_awaiting_review(client, project_folder)
    resp = client.post(
        f"/api/stage-runs/{run_id}/approve",
        json={
            "comment": "通过",
            "checklist": {
                "req-scope": {"verdict": "passed", "note": ""},
                "req-honest": {"verdict": "na", "note": "无新增功能"},
            },
        },
    )
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        run = db.get(StageRun, run_id)
        assert run.status == "approved"
        events = [event.message for event in run_activity(db, run_id)]
        assert any("清单核对" in message for message in events)


def run_activity(db, run_id: int):
    from app.models.stage_run import ActivityEvent

    return list(
        db.scalars(
            select(ActivityEvent).where(ActivityEvent.stage_run_id == run_id)
        )
    )
