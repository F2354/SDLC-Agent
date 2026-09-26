"""过程模型视图（Agent 活动展示）的验证。

验证 flow 接口能把「谁用哪个模型、调了哪些工具、与谁并行」挂到阶段节点上，
以及工具调用摘要与统计的解析逻辑。
"""

import json
import uuid

from app.api.routes.projects import _parse_tool_usage
from app.db.session import SessionLocal
from app.models.stage_run import StageRun
from app.services.coding_agent import _summarize_tool_call


def _setup_project(client, project_folder: str, model: str = "waterfall") -> tuple[dict, int, dict]:
    reg = client.post(
        "/api/auth/register",
        json={"username": f"flow_{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "过程模型活动测试",
            "process_model_code": model,
            "folder": project_folder,
        },
    ).json()
    flow = client.get(f"/api/projects/{project['id']}/flow", headers=headers).json()
    stage_ids = {item["stage"]["code"]: item["stage"]["id"] for item in flow["stages"]}
    return headers, project["id"], stage_ids


def _flow_stage(client, headers: dict, project_id: int, stage_code: str) -> dict:
    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers).json()
    return next(item for item in flow["stages"] if item["stage"]["code"] == stage_code)


def test_flow_stage_exposes_agent_role_and_model(client, project_folder):
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    with SessionLocal() as db:
        db.add(
            StageRun(
                project_id=project_id,
                stage_id=stage_ids["requirements"],
                status="awaiting_review",
                mode="auto",
                agent_code="requirements_analyst",
                model_name="deepseek-reasoner",
            )
        )
        db.commit()

    item = _flow_stage(client, headers, project_id, "requirements")
    assert item["agent_role"] == "requirements_analyst"
    assert item["agent_role_name"] == "需求分析师"
    assert item["model"] == "deepseek-reasoner"


def test_flow_stage_exposes_tool_usage(client, project_folder):
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    with SessionLocal() as db:
        db.add(
            StageRun(
                project_id=project_id,
                stage_id=stage_ids["coding"],
                status="approved",
                mode="auto",
                agent_code="developer",
                model_name="mimo-v2.5",
                tool_usage_json=json.dumps(
                    {"write_file": 5, "run_tests": 2, "git_status": 1}
                ),
            )
        )
        db.commit()

    item = _flow_stage(client, headers, project_id, "coding")
    assert item["tool_call_count"] == 8
    # 按次数降序排列，便于前端优先展示高频工具。
    assert [entry["tool"] for entry in item["tool_usage"]] == [
        "write_file",
        "run_tests",
        "git_status",
    ]
    assert item["tool_usage"][0]["count"] == 5


def test_flow_stage_exposes_parallel_peers_only_where_applicable(
    client, project_folder
):
    headers, project_id, stage_ids = _setup_project(client, project_folder, "v-model")

    unit = _flow_stage(client, headers, project_id, "unit-test")
    assert set(unit["parallel_peers"]) == {"integration-test", "system-test"}

    # 瀑布链上的阶段没有并行同侪。
    client.patch(f"/api/projects/{project_id}", headers=headers, json={"name": "x"})
    coding = _flow_stage(client, headers, project_id, "coding")
    assert coding["parallel_peers"] == []


def test_unrun_stage_has_empty_agent_fields(client, project_folder):
    headers, project_id, _ = _setup_project(client, project_folder)

    item = _flow_stage(client, headers, project_id, "requirements")
    assert item["status"] == "pending"
    assert item["agent_role"] is None
    assert item["model"] is None
    assert item["tool_usage"] == []
    assert item["tool_call_count"] == 0


def test_parse_tool_usage_tolerates_bad_payloads():
    assert _parse_tool_usage(None) == []
    assert _parse_tool_usage("") == []
    assert _parse_tool_usage("not json") == []
    assert _parse_tool_usage("[1, 2]") == []
    assert _parse_tool_usage('{"a": "x"}') == []
    assert _parse_tool_usage('{"a": 0}') == []

    parsed = _parse_tool_usage('{"b": 2, "a": 2, "c": 7}')
    # 次数降序；同次数按名称稳定排序。
    assert [(item.tool, item.count) for item in parsed] == [("c", 7), ("a", 2), ("b", 2)]


def test_tool_call_summaries_are_human_readable():
    assert _summarize_tool_call("write_file", {"path": "app/main.py"}, {}) == "写入 app/main.py"
    assert _summarize_tool_call("read_file", {"path": "a.py"}, {}) == "读取 a.py"
    assert (
        _summarize_tool_call("write_files", {}, {"count": 5}) == "批量写入 5 个文件"
    )
    assert (
        _summarize_tool_call("edit_files", {}, {"count": 3}) == "跨文件替换 3 个文件"
    )
    assert (
        _summarize_tool_call("list_files", {"target": "tests"}, {"files": ["a", "b"]})
        == "列出 tests/ 下 2 个文件"
    )
    assert _summarize_tool_call("run_tests", {}, {"ok": True}) == "运行测试：通过"
    assert _summarize_tool_call("run_tests", {}, {"ok": False}) == "运行测试：未通过"
    assert _summarize_tool_call("git_commit", {}, {}) == "提交改动"
    assert _summarize_tool_call("run_command", {"command": "pytest -q"}, {}) == "执行命令：pytest -q"
