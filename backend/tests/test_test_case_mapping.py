"""测试用例映射（TC mapping）测试：接通工具循环与追溯链的最后一跳。

工具循环阶段的产物是机器拼装的，不含 TC-xxx 实体，追溯的
「模块→测试」一跳因此永远为 0。_test_case_mapping_md 把已落盘的
pytest 测试映射为规范的 TC 用例（标注验证的 MOD/RQ 编号）。
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal

from app.models.llm_provider import LLMProvider
from app.models.process_model import Stage
from app.models.project import Project
from app.models.stage_run import Artifact, StageRun
from app.services.code_service import write_code_file
from app.services.stage_contracts import stage_contract
from app.services.stage_service import (
    _paired_stage_entities,
    _test_case_mapping_md,
    _tests_dir_snapshot,
)


def _headers(client) -> dict:
    username = f"tcmap_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _vmodel_project(client, headers, folder: str) -> int:
    resp = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "TC映射测试",
            "description": "简单示例",
            "process_model_code": "v-model",
            "folder": folder,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _seed_stage_run_with_artifact(db, project_id: int, stage_code: str, content: str):
    project = db.get(Project, project_id)
    stage = db.scalar(
        select(Stage).where(
            Stage.process_model_id == project.process_model_id,
            Stage.code == stage_code,
        )
    )
    run = StageRun(project_id=project_id, stage_id=stage.id, status="approved")
    db.add(run)
    db.flush()
    artifact = Artifact(
        project_id=project_id,
        stage_run_id=run.id,
        type=stage_code,
        title=f"{stage_code}产物",
        content_md=content,
    )
    db.add(artifact)
    db.commit()


def test_tests_dir_snapshot_reads_written_files(client, project_folder):
    headers = _headers(client)
    project_id = _vmodel_project(client, headers, project_folder)

    write_code_file(
        project_id,
        "test_app.py",
        "def test_login():\n    assert True\n",
        "tests",
    )
    snapshot = _tests_dir_snapshot(project_id)
    assert "test_app.py" in snapshot
    assert "def test_login" in snapshot


def test_paired_stage_entities_reads_latest_artifact(client, project_folder):
    headers = _headers(client)
    project_id = _vmodel_project(client, headers, project_folder)

    with SessionLocal() as db:
        _seed_stage_run_with_artifact(
            db,
            project_id,
            "detailed-design",
            "### 模块 MOD-001\nA\n\n### 模块 MOD-002\nB\n",
        )
        project = db.get(Project, project_id)
        entities = _paired_stage_entities(db, project, "detailed-design")

    assert set(entities.get("MOD", [])) == {"MOD-001", "MOD-002"}


def test_mapping_md_generated_and_validated(client, project_folder, monkeypatch):
    """映射生成成功且经过实体校验；首次不合格会重试。"""
    from app.db.session import SessionLocal
    from app.services import stage_service as ss

    headers = _headers(client)
    project_id = _vmodel_project(client, headers, project_folder)

    good = (
        "### 测试用例 TC-001\n验证：MOD-001\n覆盖登录。\n\n"
        "### 测试用例 TC-002\n验证：MOD-001\n覆盖登出。\n"
    )
    calls = {"n": 0}

    def fake_llm(provider, system, user, max_tokens=0, model_name=None, **kwargs):
        calls["n"] += 1
        return good if calls["n"] >= 2 else "（不合格输出）"

    monkeypatch.setattr(ss, "_invoke_llm", fake_llm)

    with SessionLocal() as db:
        _seed_stage_run_with_artifact(
            db, project_id, "detailed-design", "### 模块 MOD-001\nA\n"
        )
        write_code_file(
            project_id,
            "test_unit.py",
            "def test_create():\n    assert True\n\n\ndef test_delete():\n    assert True\n",
            "tests",
        )
        project = db.get(Project, project_id)
        stage = db.scalar(
            select(Stage).where(
                Stage.process_model_id == project.process_model_id,
                Stage.code == "unit-test",
            )
        )
        contract = stage_contract("v-model", "unit-test")
        provider = LLMProvider(
            name="fake",
            type="openai_compatible",
            base_url="http://x",
            api_key_enc="x",
            default_model="m",
            enabled=True,
        )
        result = _test_case_mapping_md(db, project, stage, contract, provider, None)

    assert "TC-001" in result
    assert "验证：MOD-001" in result
    assert calls["n"] == 2  # 第一次不合格，重试后通过

