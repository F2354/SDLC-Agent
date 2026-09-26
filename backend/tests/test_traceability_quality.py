"""追溯覆盖率做实的验证。

此前的问题：18 个真实产物中 UC 检出恒为 0，追溯覆盖率永远是 0。
修复分三处，这里逐一验证：
1. 实体配额进入提示词（与校验共用同一常量）；
2. 文档校验（复用重试回路）强制模型产出实体；
3. 覆盖率按可达性计算（需求经用例落到模块也算覆盖）。
"""

import uuid

from app.db.session import SessionLocal
from app.models.stage_run import Artifact, StageRun
from app.services.prompts import build_stage_prompt, entity_requirement_text
from app.services.stage_service import validate_document
from app.services.traceability import STAGE_ENTITY_REQUIREMENTS

_FILLER = "本系统面向高校教务场景，需支持考试组织、题库维护与成绩统计等能力。" * 6

REQUIREMENTS_DOC = (
    "# 需求规格说明书\n\n"
    "## 验收标准\n\n" + _FILLER + "\n\n"
    "### 需求条目 RQ-001\n用户可以注册账号。\n\n"
    "### 需求条目 RQ-002\n用户可以登录系统。\n\n"
    "### 需求条目 RQ-003\n管理员可以查看考试记录。\n\n"
    "### 用例 UC-001\n邮箱注册用例。来源：RQ-001\n\n"
    "### 用例 UC-002\n登录用例。来源：RQ-002\n\n"
    "### 用例 UC-003\n记录查询用例。来源：RQ-003\n"
)

ARCHITECTURE_DOC = (
    "# 概要设计说明书\n\n"
    "## 系统架构\n\n" + _FILLER + "\n\n"
    "### 模块 MOD-001\n账号模块。实现：RQ-001、UC-001\n\n"
    "### 模块 MOD-002\n考试模块。实现：RQ-003、UC-003\n\n"
    "### 模块 MOD-003\n鉴权模块。实现：RQ-002、UC-002\n"
)

TESTING_DOC = (
    "# 测试计划与用例\n\n"
    "## 测试策略\n\n按模块逐层覆盖。" + _FILLER + "\n\n"
    "### 测试用例 TC-001\n验证邮箱注册。验证：RQ-001、MOD-001\n\n"
    "### 测试用例 TC-002\n验证登录。验证：RQ-002、MOD-003\n\n"
    "### 测试用例 TC-003\n验证记录查询。验证：RQ-003、MOD-002\n"
)


def _setup_project(client, project_folder: str) -> tuple[dict, int, dict]:
    reg = client.post(
        "/api/auth/register",
        json={"username": f"trace_{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "追溯质量测试",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    ).json()
    flow = client.get(f"/api/projects/{project['id']}/flow", headers=headers).json()
    stage_ids = {item["stage"]["code"]: item["stage"]["id"] for item in flow["stages"]}
    return headers, project["id"], stage_ids


def _seed_artifacts(project_id: int, stage_ids: dict, docs: dict[str, str]) -> None:
    with SessionLocal() as db:
        for stage_code, content in docs.items():
            run = StageRun(
                project_id=project_id,
                stage_id=stage_ids[stage_code],
                status="awaiting_review",
                mode="auto",
            )
            db.add(run)
            db.flush()
            db.add(
                Artifact(
                    project_id=project_id,
                    stage_run_id=run.id,
                    type=stage_code,
                    title=f"{stage_code} 文档",
                    content_md=content,
                    current_version=1,
                    status="awaiting_review",
                )
            )
        db.commit()


def test_entity_requirements_exist_for_key_stages():
    for stage_code in ("requirements", "architecture", "detailed-design", "testing"):
        assert STAGE_ENTITY_REQUIREMENTS.get(stage_code), f"{stage_code} 缺少实体配额"
    # 需求阶段必须同时要求 RQ 与 UC —— 缺 UC 正是此前追溯断裂的根因。
    assert set(STAGE_ENTITY_REQUIREMENTS["requirements"]) == {"RQ", "UC"}


def test_prompt_states_entity_quota():
    text = entity_requirement_text("requirements")
    assert "RQ" in text and "UC" in text

    _, user_prompt = build_stage_prompt(
        "requirements", "需求分析", "在线考试系统", "考试平台", ""
    )
    assert "至少 3 条" in user_prompt
    assert "来源：RQ-001" in user_prompt


def test_validation_rejects_document_without_use_cases():
    """需求文档只有 RQ 没有 UC 时，校验必须打回，从而触发重试补齐。"""
    without_uc = REQUIREMENTS_DOC.split("### 用例 UC-001")[0]
    assert len(without_uc) >= 300

    reason = validate_document("requirements", without_uc)
    assert reason, "缺少用例的文档不应通过校验"
    assert "UC" in reason


def test_validation_passes_when_entities_are_complete():
    assert validate_document("requirements", REQUIREMENTS_DOC) == ""
    assert validate_document("architecture", ARCHITECTURE_DOC) == ""
    assert validate_document("testing", TESTING_DOC) == ""


def test_validation_requires_modules_in_architecture():
    # 含"架构"与"模块"关键词、但没有任何 MOD 编号实体。
    without_mod = "# 概要设计说明书\n\n## 系统架构\n\n本系统划分为若干模块。\n\n" + _FILLER * 2
    assert len(without_mod) >= 300
    reason = validate_document("architecture", without_mod)
    assert "MOD" in reason


def test_coverage_is_complete_for_contract_following_documents(client, project_folder):
    """文档遵守实体契约时，追溯覆盖率应当是满的、且无未定义引用。

    这是"追溯覆盖率做实"的验收测试：完整跑通 RQ → UC → MOD → TC。
    """
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    _seed_artifacts(
        project_id,
        stage_ids,
        {
            "requirements": REQUIREMENTS_DOC,
            "architecture": ARCHITECTURE_DOC,
            "testing": TESTING_DOC,
        },
    )

    body = client.get(f"/api/projects/{project_id}/traceability", headers=headers).json()
    coverage = body["coverage"]

    assert coverage["rq_total"] == 3
    assert coverage["rq_with_uc"] == 3
    assert coverage["rq_with_mod"] == 3
    assert coverage["rq_with_tc"] == 3
    assert coverage["mod_total"] == 3
    assert coverage["mod_with_tc"] == 3
    assert coverage["tc_total"] == 3
    assert coverage["unresolved"] == []
    assert body["warnings"] == ["追溯关系完整，未发现缺失覆盖"]


def test_requirement_reaches_module_through_use_case(client, project_folder):
    """需求没有直接标注模块，但经用例可达时也应算作已覆盖。"""
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    docs = {
        "requirements": REQUIREMENTS_DOC,
        # 模块只关联用例，不直接写需求编号。
        "architecture": (
            "# 概要设计说明书\n\n## 系统架构\n\n模块划分如下。\n\n"
            "### 模块 MOD-001\n账号模块。实现：UC-001\n\n"
            "### 模块 MOD-002\n考试模块。实现：UC-003\n\n"
            "### 模块 MOD-003\n鉴权模块。实现：UC-002\n"
        ),
    }
    _seed_artifacts(project_id, stage_ids, docs)

    body = client.get(f"/api/projects/{project_id}/traceability", headers=headers).json()
    # RQ-001 → UC-001 → MOD-001 两跳可达。
    assert body["coverage"]["rq_with_mod"] == 3
    assert body["coverage"]["unresolved"] == []


def test_missing_use_cases_surface_as_actionable_warning(client, project_folder):
    """用例确实缺失时，告警要说明影响，而不是静默显示为 0。"""
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    _seed_artifacts(
        project_id,
        stage_ids,
        {"requirements": REQUIREMENTS_DOC.split("### 用例 UC-001")[0]},
    )

    body = client.get(f"/api/projects/{project_id}/traceability", headers=headers).json()
    assert body["coverage"]["rq_with_uc"] == 0
    assert any("用例缺失" in warning for warning in body["warnings"])
