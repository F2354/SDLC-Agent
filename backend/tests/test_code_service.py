import uuid

from app.services.code_service import parse_code_files


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_parse_code_files():
    content = (
        "[FILE] app/main.py\n"
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n"
        "[FILE] requirements.txt\n"
        "fastapi\nuvicorn\n"
    )
    entries = parse_code_files(content)
    assert len(entries) == 2
    assert entries[0][0] == "app/main.py"
    assert "FastAPI" in entries[0][1]
    assert entries[1][0] == "requirements.txt"


def test_code_tree_and_run_without_code(client, project_folder):
    username = unique_name("code_owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "代码验证项目",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    )
    project_id = project.json()["id"]

    tree = client.get(f"/api/projects/{project_id}/code/tree", headers=headers)
    assert tree.status_code == 200
    assert tree.json()["exists"] is False

    run = client.post(f"/api/projects/{project_id}/code/run", headers=headers)
    assert run.status_code == 200
    assert run.json()["ok"] is False


def test_code_editor_and_git_endpoints(client, project_folder):
    username = unique_name("code_editor")
    reg = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post("/api/projects", headers=headers, json={"name": "编辑器项目", "process_model_code": "waterfall", "folder": project_folder})
    project_id = project.json()["id"]

    saved = client.post(f"/api/projects/{project_id}/code/file", headers=headers, json={"path": "app.py", "content": "print('ok')"})
    assert saved.status_code == 200
    content = client.get(f"/api/projects/{project_id}/code/file", headers=headers, params={"path": "app.py"})
    assert content.text == "print('ok')"

    status = client.get(f"/api/projects/{project_id}/code/git/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["is_repo"] is False

    rejected = client.post(f"/api/projects/{project_id}/code/file", headers=headers, json={"path": "../escape.py", "content": "bad"})
    assert rejected.status_code == 400


def test_project_skills_endpoint(client, project_folder):
    username = unique_name("skills")
    reg = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post("/api/projects", headers=headers, json={"name": "Skills 项目", "process_model_code": "waterfall", "folder": project_folder})
    project_id = project.json()["id"]
    skill_dir = __import__("pathlib").Path(project_folder) / ".sdlc" / "skills" / "python-style"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: python-style\ndescription: Python coding rules\n---\n# Rules\nUse type hints.", encoding="utf-8")

    listed = client.get(f"/api/projects/{project_id}/skills", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "python-style"
    detail = client.get(f"/api/projects/{project_id}/skills/python-style", headers=headers)
    assert detail.status_code == 200
    assert "type hints" in detail.json()["content"]


def test_git_full_workflow(client, project_folder):
    username = unique_name("git_workflow")
    reg = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post("/api/projects", headers=headers, json={"name": "Git 工作流项目", "process_model_code": "waterfall", "folder": project_folder})
    project_id = project.json()["id"]

    client.post(f"/api/projects/{project_id}/code/file", headers=headers, json={"path": "README.md", "content": "# Demo\n"})
    initialized = client.post(f"/api/projects/{project_id}/code/git/init", headers=headers)
    assert initialized.status_code == 200
    assert initialized.json()["is_repo"] is True

    committed = client.post(f"/api/projects/{project_id}/code/git/commit", headers=headers, json={"message": "Initial workspace"})
    assert committed.status_code == 200
    assert committed.json()["created"] is True

    status = client.get(f"/api/projects/{project_id}/code/git/status", headers=headers)
    assert status.json()["clean"] is True
    log = client.get(f"/api/projects/{project_id}/code/git/log", headers=headers)
    assert log.status_code == 200
    assert log.json()[0]["subject"] == "Initial workspace"


def test_project_mcp_config_and_discovery_listing(client, project_folder):
    username = unique_name("mcp")
    reg = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post("/api/projects", headers=headers, json={"name": "MCP 项目", "process_model_code": "waterfall", "folder": project_folder})
    project_id = project.json()["id"]
    config = __import__("pathlib").Path(project_folder) / ".sdlc" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"filesystem": {"type": "local", "command": ["python", "server.py"], "enabled": true, "environment": {"TOKEN": "secret"}}}', encoding="utf-8")

    listed = client.get(f"/api/projects/{project_id}/mcp", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body[0]["name"] == "filesystem"
    assert body[0]["env_keys"] == ["TOKEN"]
    assert "secret" not in listed.text

    discovered = client.post(f"/api/projects/{project_id}/mcp/filesystem/discover", headers=headers)
    assert discovered.status_code == 200
    assert discovered.json()["error"]


def test_project_agent_profiles_and_permissions(client, project_folder):
    username = unique_name("agents")
    reg = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post("/api/projects", headers=headers, json={"name": "Agent 配置项目", "process_model_code": "waterfall", "folder": project_folder})
    project_id = project.json()["id"]
    config = __import__("pathlib").Path(project_folder) / ".sdlc" / "agents.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"agents": {"developer": {"mode": "primary", "description": "Writes code", "permissions": {"edit": "allow", "bash": "deny"}}}}', encoding="utf-8")

    response = client.get(f"/api/projects/{project_id}/agents", headers=headers)
    assert response.status_code == 200
    assert response.json()[0]["permissions"]["bash"] == "deny"


def test_subprocess_env_keeps_windows_system_vars(client, project_folder):
    r"""子进程环境必须保留 SystemDrive 等系统变量。

    缺 SystemDrive 时，Windows 组件会把 "%SystemDrive%\ProgramData\..."
    当字面量路径、在子进程 CWD 下建出真实目录（已在真实运行中复现）。
    """
    import os

    from app.services.code_service import subprocess_env

    username = unique_name("env_owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "子进程环境项目",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    )
    env = subprocess_env(project.json()["id"])

    for key in ("SystemDrive", "SystemRoot", "COMSPEC", "TEMP"):
        if os.environ.get(key) is not None:
            assert env.get(key) == os.environ[key], f"子进程环境缺少 {key}"


def test_git_degrades_when_unavailable(client, project_folder, monkeypatch):
    """宿主机未安装 Git 时，Git 功能应降级为不可用，而不是抛错。"""
    from app.services import code_service

    monkeypatch.setattr(code_service, "git_available", lambda: False)

    username = unique_name("git_missing")
    reg = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "无 Git 项目", "process_model_code": "waterfall", "folder": project_folder},
    )
    project_id = project.json()["id"]

    status = client.get(f"/api/projects/{project_id}/code/git/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["available"] is False
    assert status.json()["is_repo"] is False

    log = client.get(f"/api/projects/{project_id}/code/git/log", headers=headers)
    assert log.status_code == 200
    assert log.json() == []

    diff = client.get(f"/api/projects/{project_id}/code/git/diff", headers=headers)
    assert diff.status_code == 200
    assert "未检测到 Git" in diff.text

    init = client.post(f"/api/projects/{project_id}/code/git/init", headers=headers)
    assert init.status_code == 400

    # 阶段自动提交应静默跳过，不抛异常。
    result = code_service.commit_project_changes(project_id, "msg")
    assert result["created"] is False
