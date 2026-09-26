"""Git 集成接线的执行链验证。

覆盖两件事：
1. Git 能力真的暴露给了编码 Agent（工具注册 + 权限拦截生效）；
2. 阶段产物落盘后自动提交，提交信息能还原过程模型的执行轨迹。
"""

import json
import os
import uuid
from pathlib import Path

from app.db.session import SessionLocal
from app.models.stage_run import Artifact, StageRun
from app.services.agents import get_agent_permissions
from app.services.code_service import (
    commit_project_changes,
    ensure_git_repo,
    git_log,
)
from app.services.coding_agent import TOOLS, execute_tool
from app.services.stage_service import commit_stage_progress

GIT_TOOL_NAMES = {"git_status", "git_diff", "git_log", "git_commit"}


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _write_agents_config(folder: str, payload: dict) -> None:
    target = Path(folder) / ".sdlc"
    target.mkdir(parents=True, exist_ok=True)
    (target / "agents.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _setup_project(client, project_folder: str, agents_config: dict | None = None):
    """注册用户 + 创建项目，返回 (headers, project_id)。"""
    reg = client.post(
        "/api/auth/register",
        json={"username": unique_name("git_owner"), "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Git 集成测试",
            "process_model_code": "waterfall",
            "folder": project_folder,
        },
    ).json()
    if agents_config is not None:
        _write_agents_config(project_folder, agents_config)
    return headers, project["id"]


def test_git_tools_are_registered_for_the_coding_agent():
    names = {tool["function"]["name"] for tool in TOOLS}
    assert GIT_TOOL_NAMES <= names


def test_git_permission_deny_blocks_git_tools(client, project_folder):
    """agents.json 把 git 设为 deny 时，Git 工具应被拦下。"""
    _, project_id = _setup_project(
        client,
        project_folder,
        {"agents": {"developer": {"permissions": {"git": "deny"}}}},
    )
    assert get_agent_permissions(project_id, "developer")["git"] == "deny"

    result = execute_tool(project_id, "git_status", {}, agent_name="developer")
    assert result["ok"] is False
    assert "git" in result["error"]


def test_git_tools_default_to_allowed_and_report_repo_state(client, project_folder):
    """默认权限下 Git 工具可用；未初始化仓库时应如实报告 is_repo=False。"""
    _, project_id = _setup_project(client, project_folder)

    result = execute_tool(project_id, "git_status", {}, agent_name="developer")
    assert result["ok"] is True
    assert result["is_repo"] is False


def test_git_commit_tool_initializes_repo_and_rejects_empty_message(
    client, project_folder
):
    _, project_id = _setup_project(client, project_folder)
    (Path(project_folder) / "sample.txt").write_text("hello\n", encoding="utf-8")

    empty = execute_tool(
        project_id, "git_commit", {"message": "   "}, agent_name="developer"
    )
    assert empty["ok"] is False
    assert "提交说明" in empty["error"]

    committed = execute_tool(
        project_id, "git_commit", {"message": "agent 主动提交"}, agent_name="developer"
    )
    assert committed["ok"] is True
    assert committed["created"] is True
    assert committed["commit"]


def test_ensure_git_repo_is_idempotent(client, project_folder):
    _, project_id = _setup_project(client, project_folder)

    assert ensure_git_repo(project_id) is True
    assert ensure_git_repo(project_id) is False
    assert (Path(project_folder) / ".git").exists()


def test_commit_project_changes_skips_when_nothing_changed(client, project_folder):
    _, project_id = _setup_project(client, project_folder)
    code_dir = Path(project_folder) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "main.py").write_text("print('hi')\n", encoding="utf-8")

    first = commit_project_changes(project_id, "首次提交")
    assert first["created"] is True

    second = commit_project_changes(project_id, "重复提交")
    assert second["created"] is False

    log = git_log(project_id, 5)
    assert log
    assert log[0]["subject"] == "首次提交"
    assert not any(entry["subject"] == "重复提交" for entry in log)


def test_commit_stage_progress_encodes_process_model_and_progress(
    client, project_folder
):
    """提交信息应形如 [waterfall 1/5] 需求分析 · 文档已生成。"""
    _, project_id = _setup_project(client, project_folder)
    docs_dir = Path(project_folder) / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "需求分析 - 需求分析文档.md").write_text("# 需求\n", encoding="utf-8")

    with SessionLocal() as db:
        commit_stage_progress(db, project_id, "requirements", "文档已生成")

    log = git_log(project_id, 5)
    assert log
    subject = log[0]["subject"]
    assert "[waterfall 1/5]" in subject
    assert "需求分析" in subject
    assert "文档已生成" in subject


def test_manual_artifact_edit_enters_git_trajectory(client, project_folder):
    """人工修订产物也应产生一次提交，便于回溯改动。"""
    headers, project_id = _setup_project(client, project_folder)
    flow = client.get(f"/api/projects/{project_id}/flow", headers=headers).json()
    stage_id = flow["stages"][0]["stage"]["id"]

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
            title="需求分析文档",
            content_md="初版内容",
            current_version=1,
            status="awaiting_review",
        )
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id

    edited = client.patch(
        f"/api/artifacts/{artifact_id}",
        headers=headers,
        json={"content_md": "修订后的内容"},
    )
    assert edited.status_code == 200

    log = git_log(project_id, 5)
    assert any("人工修订已保存" in entry["subject"] for entry in log)
