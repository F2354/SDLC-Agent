"""多文件协同编辑的验证。

重点在于原子性：
- 批量写入中途失败要回滚，不留半成品；
- 跨文件替换全部校验通过才落盘，是全有或全无；
- 不可越出工作区。
"""

import uuid
from pathlib import Path

from app.services.agent_roles import role_tool_names
from app.services.code_service import edit_many_files, write_many_files
from app.services.coding_agent import TOOLS, execute_tool, tools_for_agent

MULTI_FILE_TOOLS = {"write_files", "edit_files"}


def _setup_project(client, project_folder: str) -> int:
    reg = client.post(
        "/api/auth/register",
        json={"username": f"multi_{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "多文件编辑测试",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    ).json()
    return project["id"]


def test_multi_file_tools_are_exposed_and_role_gated():
    names = {tool["function"]["name"] for tool in TOOLS}
    assert MULTI_FILE_TOOLS <= names

    # 有写权限的角色自动获得批量工具，只读角色拿不到。
    assert MULTI_FILE_TOOLS <= role_tool_names("developer")
    assert MULTI_FILE_TOOLS <= role_tool_names("tester")
    assert MULTI_FILE_TOOLS <= role_tool_names("architect")
    assert not (MULTI_FILE_TOOLS & role_tool_names("reviewer"))

    reviewer_tools = {t["function"]["name"] for t in tools_for_agent("reviewer")}
    assert not (MULTI_FILE_TOOLS & reviewer_tools)


def test_write_many_files_creates_all_files(client, project_folder):
    project_id = _setup_project(client, project_folder)

    result = write_many_files(
        project_id,
        [
            {"path": "app/main.py", "content": "print('main')\n"},
            {"path": "app/models.py", "content": "MODELS = []\n"},
            {"path": "README.md", "content": "# 项目\n"},
        ],
    )

    assert result["count"] == 3
    assert set(result["files"]) == {"app/main.py", "app/models.py", "README.md"}
    for relative in result["files"]:
        assert (Path(project_folder) / "code" / relative).is_file()


def test_write_many_files_rolls_back_new_files_on_failure(client, project_folder):
    """中途失败时，本次新建的文件必须被删除。"""
    project_id = _setup_project(client, project_folder)
    code_dir = Path(project_folder) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    # 制造一个会写入失败的目标：同名的目录。
    (code_dir / "blocked").mkdir()

    try:
        write_many_files(
            project_id,
            [
                {"path": "fresh.py", "content": "print('fresh')\n"},
                {"path": "blocked", "content": "无法写入目录\n"},
            ],
        )
    except ValueError as exc:
        assert "已回滚" in str(exc)
    else:  # pragma: no cover - 失败路径必须被触发
        raise AssertionError("应当因为写入目录而失败")

    assert not (code_dir / "fresh.py").exists()


def test_write_many_files_restores_overwritten_content_on_failure(
    client, project_folder
):
    """中途失败时，被覆盖的既有文件必须还原为原内容。"""
    project_id = _setup_project(client, project_folder)
    code_dir = Path(project_folder) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    original = code_dir / "existing.py"
    original.write_text("原始内容\n", encoding="utf-8")
    (code_dir / "blocked").mkdir()

    try:
        write_many_files(
            project_id,
            [
                {"path": "existing.py", "content": "被改写的内容\n"},
                {"path": "blocked", "content": "无法写入目录\n"},
            ],
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("应当因为写入目录而失败")

    assert original.read_text(encoding="utf-8") == "原始内容\n"


def test_write_many_files_rejects_path_outside_workspace(client, project_folder):
    project_id = _setup_project(client, project_folder)

    try:
        write_many_files(project_id, [{"path": "../escaped.py", "content": "x"}])
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("越界路径应当被拒绝")

    assert not (Path(project_folder) / "escaped.py").exists()


def test_write_many_files_validates_entry_shape(client, project_folder):
    project_id = _setup_project(client, project_folder)

    for bad in ([], [{"path": "a.py"}], [{"content": "x"}], "not-a-list"):
        try:
            write_many_files(project_id, bad)
        except ValueError:
            continue
        raise AssertionError(f"非法入参应当被拒绝：{bad!r}")


def test_edit_many_files_applies_across_files(client, project_folder):
    project_id = _setup_project(client, project_folder)
    code_dir = Path(project_folder) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "a.py").write_text("def old_name():\n    pass\n", encoding="utf-8")
    (code_dir / "b.py").write_text("from a import old_name\n", encoding="utf-8")

    result = edit_many_files(
        project_id,
        [
            {"path": "a.py", "old_string": "old_name", "new_string": "new_name"},
            {"path": "b.py", "old_string": "old_name", "new_string": "new_name"},
        ],
    )

    assert result["count"] == 2
    assert "new_name" in (code_dir / "a.py").read_text(encoding="utf-8")
    assert "new_name" in (code_dir / "b.py").read_text(encoding="utf-8")


def test_edit_many_files_is_all_or_nothing(client, project_folder):
    """任一替换目标不存在时，所有文件都不应被改动。"""
    project_id = _setup_project(client, project_folder)
    code_dir = Path(project_folder) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    (code_dir / "b.py").write_text("beta = 2\n", encoding="utf-8")

    try:
        edit_many_files(
            project_id,
            [
                {"path": "a.py", "old_string": "alpha", "new_string": "ALPHA"},
                {"path": "b.py", "old_string": "不存在的文本", "new_string": "X"},
            ],
        )
    except ValueError as exc:
        assert "未在 b.py 中找到" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当因为找不到替换目标而失败")

    # a.py 的替换虽然在列表前面，也必须保持原样。
    assert (code_dir / "a.py").read_text(encoding="utf-8") == "alpha = 1\n"
    assert (code_dir / "b.py").read_text(encoding="utf-8") == "beta = 2\n"


def test_edit_many_files_requires_existing_file(client, project_folder):
    project_id = _setup_project(client, project_folder)

    try:
        edit_many_files(
            project_id,
            [{"path": "missing.py", "old_string": "a", "new_string": "b"}],
        )
    except FileNotFoundError as exc:
        assert "missing.py" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("文件不存在应当报错")


def test_execute_tool_write_files_writes_to_role_target(client, project_folder):
    """测试角色的批量写入应落在 tests/ 目录。"""
    project_id = _setup_project(client, project_folder)

    result = execute_tool(
        project_id,
        "write_files",
        {"files": [{"path": "test_app.py", "content": "def test_ok():\n    assert True\n"}]},
        agent_name="tester",
    )

    assert result["ok"] is True
    assert result["target"] == "tests"
    assert (Path(project_folder) / "tests" / "test_app.py").is_file()


def test_execute_tool_edit_files_through_kernel(client, project_folder):
    project_id = _setup_project(client, project_folder)
    code_dir = Path(project_folder) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "app.py").write_text("VERSION = '1'\n", encoding="utf-8")

    result = execute_tool(
        project_id,
        "edit_files",
        {"edits": [{"path": "app.py", "old_string": "'1'", "new_string": "'2'"}]},
        agent_name="developer",
    )

    assert result["ok"] is True
    assert "VERSION = '2'" in (code_dir / "app.py").read_text(encoding="utf-8")


def test_execute_tool_rejects_batch_write_for_reviewer(client, project_folder):
    """评审角色即使显式请求批量写入，也会被内核拒绝。"""
    project_id = _setup_project(client, project_folder)

    result = execute_tool(
        project_id,
        "write_files",
        {"files": [{"path": "x.py", "content": "x"}]},
        agent_name="reviewer",
    )

    assert result["ok"] is False
    assert "不允许使用工具" in result["error"]
    assert not (Path(project_folder) / "code" / "x.py").exists()
