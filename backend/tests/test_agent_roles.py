"""Agent 角色分工的机制验证。

重点不是"角色表里有 7 条记录"，而是：
- 每个角色有确定的工具子集，且与阶段绑定；
- 只读角色在**机制上**拿不到写工具（不是靠提示词自觉）；
- 全部声明为"需真实写盘验证"的阶段都真的绑定了可执行角色。
"""

import uuid

from app.services.agent_roles import (
    WRITE_TOOLS,
    all_roles,
    get_role_spec,
    role_tool_names,
    role_write_target,
)
from app.services.coding_agent import TOOLS, execute_tool, resolve_target, tools_for_agent
from app.services.seed import AGENT_ROLES
from app.services.stage_service import (
    CODE_STAGE_CODES,
    STAGE_AGENT_CODE,
    TOOL_LOOP_ROLES,
)

SHELL_TOOLS = {"run_command", "run_tests"}


def _setup_project(client, project_folder: str) -> int:
    reg = client.post(
        "/api/auth/register",
        json={"username": f"role_{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "角色分工测试",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    ).json()
    return project["id"]


def test_every_seeded_role_has_a_spec():
    """seed 表里的 7 个角色都必须在注册表中有定义，避免角色只在数据库里存在。"""
    seeded = {code for code, _name, _desc in AGENT_ROLES}
    registered = {spec.code for spec in all_roles()}
    assert seeded == registered
    assert len(registered) == 7


def test_every_stage_binding_points_to_a_registered_role():
    """阶段 → 角色 的绑定不能指向不存在的角色。"""
    registered = {spec.code for spec in all_roles()}
    unknown = {
        stage: role
        for stage, role in STAGE_AGENT_CODE.items()
        if role not in registered
    }
    assert not unknown, f"存在指向未注册角色的阶段绑定：{unknown}"


def test_all_code_stages_are_bound_to_a_tool_loop_role():
    """声明需要真实写盘验证的阶段，必须都绑定到可执行角色。

    此前 CODE_STAGE_CODES 声明 7 个阶段，实际只有 coding 走了工具循环。
    """
    assert set(TOOL_LOOP_ROLES) == set(CODE_STAGE_CODES)
    for role in TOOL_LOOP_ROLES.values():
        spec = get_role_spec(role)
        assert spec.can_write, f"角色 {role} 没有写权限，无法完成写盘验证"
        assert spec.can_run_shell, f"角色 {role} 无法运行验证命令"


def test_reviewer_and_coordinator_are_read_only():
    """评审与统筹必须只读：评审不可修改被评审的产物，也不能产生提交。"""
    for code in ("reviewer", "coordinator"):
        toolset = role_tool_names(code)
        assert not (toolset & WRITE_TOOLS), f"{code} 不应拥有写工具"
        assert not (toolset & SHELL_TOOLS), f"{code} 不应拥有命令工具"
        assert "git_commit" not in toolset, f"{code} 不应能产生提交"
        assert "read_file" in toolset
        assert "git_log" in toolset


def test_document_roles_cannot_execute_commands():
    """需求 / 架构 / 设计角色只做设计文档，不应能执行命令。"""
    for code in ("requirements_analyst", "architect", "designer"):
        toolset = role_tool_names(code)
        assert toolset & WRITE_TOOLS, f"{code} 需要写文档"
        assert not (toolset & SHELL_TOOLS), f"{code} 不应能执行命令"


def test_developer_has_full_toolset_and_writes_code():
    spec = get_role_spec("developer")
    assert spec.toolset == frozenset(t["function"]["name"] for t in TOOLS)
    assert spec.write_target == "code"


def test_tester_can_run_tests_and_writes_to_tests():
    spec = get_role_spec("tester")
    assert {"run_tests", "run_command"} <= spec.toolset
    assert spec.write_target == "tests"


def test_tools_for_agent_filters_by_role():
    reviewer_tools = {tool["function"]["name"] for tool in tools_for_agent("reviewer")}
    assert "write_file" not in reviewer_tools
    assert "run_command" not in reviewer_tools
    assert "read_file" in reviewer_tools

    developer_tools = {
        tool["function"]["name"] for tool in tools_for_agent("developer")
    }
    assert "write_file" in developer_tools
    assert "run_tests" in developer_tools


def test_reviewer_write_attempt_is_rejected_at_the_kernel(client, project_folder):
    """机制层面的保证：评审角色调用写工具会被内核直接拒绝。"""
    project_id = _setup_project(client, project_folder)

    result = execute_tool(
        project_id,
        "write_file",
        {"path": "sneaky.py", "content": "print('should not happen')"},
        agent_name="reviewer",
    )
    assert result["ok"] is False
    assert "不允许使用工具" in result["error"]


def test_document_role_command_attempt_is_rejected(client, project_folder):
    project_id = _setup_project(client, project_folder)

    result = execute_tool(
        project_id,
        "run_command",
        {"command": "python main.py"},
        agent_name="requirements_analyst",
    )
    assert result["ok"] is False
    assert "不允许使用工具" in result["error"]


def test_resolve_target_prefers_explicit_value_then_role_default():
    # 显式指定优先
    assert resolve_target("developer", {"target": "tests"}) == "tests"
    # 非法值被忽略，回退角色默认
    assert resolve_target("developer", {"target": "etc"}) == "code"
    # 测试角色默认写 tests/
    assert resolve_target("tester", {}) == "tests"
    # 只读角色无写入目标，回退 code/
    assert resolve_target("reviewer", {}) == "code"
    assert role_write_target("reviewer") == ""


def test_document_role_writes_folder_is_documented_target():
    """文档类角色虽然不跑工具循环，但写入目标应为 docs，便于后续扩展。"""
    for code in ("requirements_analyst", "architect", "designer"):
        assert role_write_target(code) == "docs"
