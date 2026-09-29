"""工具循环的断点续跑测试。

背景：coding 失败后重试此前从零开始 —— 实测连续三次失败都重新通读工作区，
既浪费 token 也浪费轮次。这里验证会话快照的写入、读取与续跑消息构造。
"""

import json
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.process_model import Stage
from app.models.project import Project
from app.models.stage_run import StageRun
from app.services.coding_agent import (
    _PERSIST_MSG_CHARS,
    build_harness_messages,
    load_resume_state,
    persist_harness_state,
)


def _project_with_stage(client, folder: str, model_code: str = "waterfall") -> tuple[int, str]:
    username = f"resume_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project_id = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "断点续跑测试",
            "description": "示例",
            "process_model_code": model_code,
            "folder": folder,
        },
    ).json()["id"]
    return project_id, "coding"


# ---------------------------------------------------------------- 消息构造


def test_build_messages_fresh_run():
    messages, resumed = build_harness_messages(
        system="SYS", user="首次任务", resume_messages=None, resume_turns=0
    )
    assert resumed is None
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[1]["content"] == "首次任务"


def test_build_messages_resumed_run_appends_instruction():
    previous = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "首次任务"},
        {"role": "assistant", "content": "我读了 app/main.py"},
    ]
    messages, resumed = build_harness_messages(
        system="SYS", user="首次任务", resume_messages=previous, resume_turns=4
    )
    assert resumed == 4
    # 沿用上次会话（不重复插入 system/user），只追加一条续跑指令
    assert messages[:3] == previous
    assert len(messages) == 4
    assert "[续跑]" in messages[-1]["content"]
    assert "第 4 轮" in messages[-1]["content"]


# ---------------------------------------------------------------- 快照存取


def test_persist_and_load_round_trip(client, project_folder):
    project_id, stage_code = _project_with_stage(client, project_folder)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stage = db.scalar(
            select(Stage).where(
                Stage.process_model_id == project.process_model_id,
                Stage.code == stage_code,
            )
        )
        failed_run = StageRun(
            project_id=project_id, stage_id=stage.id, status="verification_failed"
        )
        db.add(failed_run)
        db.commit()

        persist_harness_state(
            db,
            failed_run.id,
            [{"role": "user", "content": "任务"}, {"role": "assistant", "content": "进展"}],
            turn=5,
            tool_usage={"write_files": 2},
            tool_log=["批量写入 2 个文件"],
        )
        db.refresh(failed_run)
        assert failed_run.harness_json

        messages, turns = load_resume_state(db, project_id, stage.id)
        assert turns == 5
        assert messages[0]["content"] == "任务"

        # 传 exclude_run_id（本次新运行）时仍能取到上一次失败的快照
        messages2, turns2 = load_resume_state(
            db, project_id, stage.id, exclude_run_id=failed_run.id
        )
        assert messages2 is None and turns2 == 0


def test_load_resume_state_ignores_successful_runs(client, project_folder):
    """通过了的运行不该被当作续跑起点。"""
    project_id, stage_code = _project_with_stage(client, project_folder)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stage = db.scalar(
            select(Stage).where(
                Stage.process_model_id == project.process_model_id,
                Stage.code == stage_code,
            )
        )
        ok_run = StageRun(project_id=project_id, stage_id=stage.id, status="approved")
        db.add(ok_run)
        db.commit()
        persist_harness_state(
            db, ok_run.id, [{"role": "user", "content": "任务"}], 3, {}, []
        )
        messages, turns = load_resume_state(db, project_id, stage.id)
        assert messages is None
        assert turns == 0


def test_persist_truncates_long_messages(client, project_folder):
    project_id, stage_code = _project_with_stage(client, project_folder)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        stage = db.scalar(
            select(Stage).where(
                Stage.process_model_id == project.process_model_id,
                Stage.code == stage_code,
            )
        )
        run = StageRun(project_id=project_id, stage_id=stage.id, status="failed")
        db.add(run)
        db.commit()

        persist_harness_state(
            db,
            run.id,
            [{"role": "user", "content": "长" * (_PERSIST_MSG_CHARS * 2)}],
            turn=1,
            tool_usage={},
            tool_log=[],
        )
        db.refresh(run)
        payload = json.loads(run.harness_json)
        assert len(payload["messages"][0]["content"]) == _PERSIST_MSG_CHARS


def test_persist_is_safe_without_session():
    """无 db 或无 run id 时静默返回，不影响循环。"""
    persist_harness_state(None, None, [{"role": "user", "content": "x"}], 1, {}, [])
    persist_harness_state(None, 123, [{"role": "user", "content": "x"}], 1, {}, [])
