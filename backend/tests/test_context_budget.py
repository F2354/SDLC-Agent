"""上下文预算与结构化裁剪测试。

背景：前置产物此前全文注入，项目越往后注入量越大；实测出现模型"淹没"
（编码阶段反复读文件、写不出东西）。这里验证预算分配、结构化裁剪与
上下文规模的可观测性。
"""

import uuid

from app.services.context_budget import (
    DEFAULT_BUDGET,
    allocate,
    budget_for,
    compose_context,
    trim_document,
)


def _long_doc(size: int, entity: bool = False) -> str:
    body = "说明" * (size // 2)
    head = "### 模块 MOD-001\n" if entity else "## 背景\n"
    return f"# 文档\n{head}{body}\n"


def test_budget_per_stage_has_default():
    assert budget_for("requirements") > 0
    assert budget_for("coding") >= budget_for("requirements")
    assert budget_for("nope-stage") == DEFAULT_BUDGET


def test_allocate_reflows_unused_quota():
    """短文档用不完的额度会回流给长文档。"""
    sizes = [500, 50_000]
    quotas = allocate(sizes, 10_000)
    assert quotas[0] >= 500  # 至少覆盖短文档
    assert quotas[1] > quotas[0]  # 长文档拿到更多
    assert quotas[1] <= 6000  # 单份上限

    # 全部文档都很短时不强行占满预算
    small = allocate([100, 200], 10_000)
    assert all(quota <= 6000 for quota in small)


def test_allocate_empty_input():
    assert allocate([], 5000) == []


def test_trim_document_keeps_structure_when_over_budget():
    content = (
        "# 详细设计\n\n## 类设计\n" + "甲" * 3000 + "\n\n"
        "### 模块 MOD-001\n" + "乙" * 3000 + "\n\n## 接口定义\n" + "丙" * 3000
    )
    trimmed, changed = trim_document(content, 2000)
    assert changed is True
    assert len(trimmed) < len(content)
    # 章节骨架与实体编号都要保留下来
    assert "类设计" in trimmed
    assert "MOD-001" in trimmed
    assert "接口定义" in trimmed
    assert "结构化裁剪" in trimmed  # 明确告知模型这是节选


def test_trim_document_passthrough_when_within_budget():
    content = "# 小文档\n内容"
    trimmed, changed = trim_document(content, 1000)
    assert changed is False
    assert trimmed == content


def test_compose_context_prioritizes_paired_stage():
    """配对阶段的产物优先占用预算：它拿到的额度不低于其他文档。"""
    paired = _long_doc(20_000, entity=True)
    other = _long_doc(20_000)
    text, stats = compose_context(
        [("coding", "编码产物", other), ("detailed-design", "详细设计", paired)],
        stage_code="unit-test",
        priority=["detailed-design", "coding"],
        budget=4000,
    )
    assert stats.trimmed_documents == 2
    assert stats.total_chars <= 4000 + 400  # 含截断提示的少量溢出
    by_stage = {entry.stage_code: entry for entry in stats.entries}
    assert by_stage["detailed-design"].used_chars >= by_stage["coding"].used_chars
    assert "详细设计" in text


def test_compose_context_records_budget_and_note():
    text, stats = compose_context(
        [("requirements", "需求文档", _long_doc(30_000))],
        stage_code="architecture",
        priority=["requirements"],
    )
    assert stats.budget == budget_for("architecture")
    assert stats.trimmed_documents == 1
    assert "预算" in stats.note()
    payload = stats.to_json()
    assert payload["trimmed_documents"] == 1
    assert payload["entries"][0]["stage"] == "requirements"


def test_compose_context_without_documents():
    text, stats = compose_context([], stage_code="requirements", priority=[])
    assert text == ""
    assert stats.total_chars == 0


def test_previous_artifacts_keeps_only_latest_per_stage(client, project_folder):
    """同一阶段打回重跑会留下多份产物：上下文只应注入最新那一份。"""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.process_model import Stage
    from app.models.project import Project
    from app.models.stage_run import Artifact, StageRun
    from app.services.stage_service import _previous_artifacts_text

    username = "ctxbudget_" + str(uuid.uuid4().hex[:8])
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project_id = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "上下文去重",
            "description": "示例",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    ).json()["id"]

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stages = {
            stage.code: stage
            for stage in db.scalars(
                select(Stage).where(Stage.process_model_id == project.process_model_id)
            )
        }
        # requirements 跑两次（模拟打回重跑），architecture 跑一次
        for code, content in (
            ("requirements", "旧版需求内容 OLD"),
            ("requirements", "新版需求内容 NEW"),
            ("architecture", "架构内容"),
        ):
            run = StageRun(project_id=project_id, stage_id=stages[code].id, status="approved")
            db.add(run)
            db.flush()
            db.add(
                Artifact(
                    project_id=project_id,
                    stage_run_id=run.id,
                    type=code,
                    title=f"{code} 产物",
                    content_md=content,
                )
            )
        db.commit()

        target = stages["detailed-design"]
        text, stats = _previous_artifacts_text(db, project, target)
        assert len(stats.entries) == 2  # requirements 只保留一份
        assert "新版需求内容 NEW" in text
        assert "旧版需求内容 OLD" not in text
        assert "架构内容" in text
