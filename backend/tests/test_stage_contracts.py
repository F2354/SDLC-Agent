"""阶段契约测试：过程模型必须产生真实的行为差异。

V 模型的灵魂是「开发↔验证逐层配对」。此前验证阶段与其它模型的测试阶段
行为完全一样（读全部前置产物、通用提示词），配对只存在于 description 文本。
本组测试验证：契约真实驱动上下文裁剪、提示词与 flow 视图。
"""

import uuid

from sqlalchemy import select

from app.services.stage_contracts import (
    DEFAULT_CONTRACTS,
    contract_context_text,
    stage_contract,
)
from app.services.stage_service import _previous_artifacts_text


def _headers(client) -> dict:
    username = f"contract_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _create_project(client, headers, model_code: str, folder: str) -> int:
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": f"契约测试_{model_code}",
            "process_model_code": model_code,
            "folder": folder,
        },
    )
    assert project.status_code in (200, 201), project.text
    return project.json()["id"]


# ---------------------------------------------------------------- 契约解析


def test_v_model_validation_lanes_have_pairing():
    """V 模型三条验证通道必须绑定配对设计阶段。"""
    unit = stage_contract("v-model", "unit-test")
    integration = stage_contract("v-model", "integration-test")
    system = stage_contract("v-model", "system-test")

    assert unit.pair_stage == "detailed-design"
    assert integration.pair_stage == "detailed-design"
    assert system.pair_stage == "requirements"

    # 验证依据 = 配对设计产物 + 被测代码
    assert set(unit.inputs) == {"coding", "detailed-design"}
    assert set(system.inputs) == {"coding", "requirements"}


def test_waterfall_falls_back_to_default_contract():
    """瀑布模型没有验证通道专属契约，回落通用契约（无配对）。"""
    contract = stage_contract("waterfall", "testing")
    assert contract.pair_stage is None
    assert contract.inputs is None
    assert contract.outputs  # 通用契约仍要求产出 TC


def test_every_seeded_stage_resolves_to_a_contract(client):
    """任何模型的任何阶段都能解析出契约，不因缺定义而崩溃。"""
    from app.db.session import SessionLocal
    from app.models.process_model import ProcessModel, Stage

    client.get("/api/health")  # 触发应用启动，确保建表与种子数据就绪
    with SessionLocal() as db:
        models = list(db.scalars(select(ProcessModel)))
        assert models, "过程模型种子数据缺失"
        for model in models:
            for stage in db.scalars(
                select(Stage).where(Stage.process_model_id == model.id)
            ):
                contract = stage_contract(model.code, stage.code)
                assert contract is not None
                assert isinstance(contract.outputs, dict)


def test_unknown_stage_gets_neutral_contract():
    """未登记的阶段返回中性契约：不裁剪、无配额、无配对。"""
    contract = stage_contract("v-model", "sprint-retrospective")
    assert contract.inputs is None
    assert contract.outputs == {}
    assert contract.pair_stage is None


# ---------------------------------------------------------------- 提示词


def test_contract_text_states_pairing_and_inputs():
    text = contract_context_text(stage_contract("v-model", "unit-test"))
    assert "配对验证" in text and "detailed-design" in text
    assert "输入契约" in text and "coding" in text

    start = contract_context_text(DEFAULT_CONTRACTS["requirements"])
    assert "流程起点" in start


def test_stage_prompt_embeds_contract_text():
    from app.services.prompts import build_stage_prompt

    system, user = build_stage_prompt(
        stage_code="unit-test",
        stage_name="单元测试",
        project_name="示例项目",
        project_description="示例",
        previous_artifacts="### 详细设计\nMOD-001 接口定义",
        contract_text=contract_context_text(stage_contract("v-model", "unit-test")),
    )
    assert "本阶段契约" in user
    assert "配对验证" in user
    assert "MOD-001" in user


# ---------------------------------------------------------------- 上下文裁剪


def _seed_artifacts(db, project_id: int, stage_code_to_run: dict[str, int]) -> None:
    from app.models.stage_run import Artifact

    for stage_code, run_id in stage_code_to_run.items():
        db.add(
            Artifact(
                project_id=project_id,
                stage_run_id=run_id,
                type="document",
                title=f"{stage_code} 产物",
                content_md=f"# {stage_code} 的产物内容",
            )
        )
    db.commit()


def test_previous_artifacts_filtered_by_contract_inputs(client, project_folder):
    """V 模型单元测试只读 coding 与 detailed-design 的产物。"""
    from app.db.session import SessionLocal
    from app.models.process_model import ProcessModel, Stage
    from app.models.project import Project
    from app.models.stage_run import StageRun
    from sqlalchemy import select

    headers = _headers(client)
    project_id = _create_project(client, headers, "v-model", project_folder)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stages = {
            s.code: s
            for s in db.scalars(
                select(Stage).where(
                    Stage.process_model_id == project.process_model_id
                )
            )
        }
        stage_run_ids = {}
        for seq, code in enumerate(["requirements", "architecture", "detailed-design", "coding"], start=1):
            run = StageRun(
                project_id=project_id,
                stage_id=stages[code].id,
                status="approved",
            )
            db.add(run)
            db.flush()
            stage_run_ids[code] = run.id
        _seed_artifacts(db, project_id, stage_run_ids)

        unit_stage = stages["unit-test"]
        text = _previous_artifacts_text(db, project, unit_stage)
        assert "coding 的产物内容" in text
        assert "detailed-design 的产物内容" in text
        # 契约之外的产物被裁掉
        assert "requirements 的产物内容" not in text
        assert "architecture 的产物内容" not in text


def test_previous_artifacts_falls_back_when_nothing_matches(client, project_folder):
    """契约指定了 inputs 但尚无匹配产物时，回退全量（防御首轮缺产物）。"""
    from app.db.session import SessionLocal
    from app.models.process_model import Stage
    from app.models.project import Project
    from app.models.stage_run import StageRun
    from sqlalchemy import select

    headers = _headers(client)
    project_id = _create_project(client, headers, "v-model", project_folder)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stages = {
            s.code: s
            for s in db.scalars(
                select(Stage).where(
                    Stage.process_model_id == project.process_model_id
                )
            )
        }
        run = StageRun(project_id=project_id, stage_id=stages["coding"].id, status="approved")
        db.add(run)
        db.flush()
        _seed_artifacts(db, project_id, {"coding": run.id})

        # unit-test 契约要求 coding + detailed-design，detailed-design 缺席，
        # 但 coding 有产物 → 过滤结果非空，仍按契约裁剪
        text = _previous_artifacts_text(db, project, stages["unit-test"])
        assert "coding 的产物内容" in text
        assert "requirements 的产物内容" not in text


def test_previous_artifacts_keeps_all_when_contract_is_none(client, project_folder):
    """inputs=None 的阶段保持旧行为：全量拼接。"""
    from app.db.session import SessionLocal
    from app.models.process_model import Stage
    from app.models.project import Project
    from app.models.stage_run import StageRun
    from sqlalchemy import select

    headers = _headers(client)
    project_id = _create_project(client, headers, "waterfall", project_folder)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stages = {
            s.code: s
            for s in db.scalars(
                select(Stage).where(
                    Stage.process_model_id == project.process_model_id
                )
            )
        }
        run_ids = {}
        for code in ["requirements", "architecture"]:
            run = StageRun(project_id=project_id, stage_id=stages[code].id, status="approved")
            db.add(run)
            db.flush()
            run_ids[code] = run.id
        _seed_artifacts(db, project_id, run_ids)

        # coding 契约 inputs=None → 两个产物都在
        text = _previous_artifacts_text(db, project, stages["coding"])
        assert "requirements 的产物内容" in text
        assert "architecture 的产物内容" in text


# ---------------------------------------------------------------- flow 视图


def test_flow_exposes_contract_with_pair_name(client, project_folder):
    """flow 接口返回契约摘要，配对阶段带中文名。"""
    headers = _headers(client)
    project_id = _create_project(client, headers, "v-model", project_folder)

    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers).json()
    by_code = {item["stage"]["code"]: item for item in flow["stages"]}

    unit = by_code["unit-test"]["contract"]
    assert unit["pair_stage"] == "detailed-design"
    assert unit["pair_stage_name"] == "详细设计"
    assert set(unit["inputs"]) == {"coding", "detailed-design"}

    req = by_code["requirements"]["contract"]
    assert req["inputs"] == []
    assert req["outputs"]["RQ"] >= 3

    waterfall_headers = _headers(client)
    wf_id = _create_project(client, waterfall_headers, "waterfall", project_folder)
    wf_flow = client.get(f"/api/projects/{wf_id}/flow", headers=waterfall_headers).json()
    wf_testing = next(
        item["contract"] for item in wf_flow["stages"] if item["stage"]["code"] == "testing"
    )
    assert wf_testing["pair_stage"] is None
