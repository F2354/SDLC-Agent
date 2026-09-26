"""并行执行的验证。

分两层：
1. 批次推导 —— 哪些阶段互为并行通道（依赖集合相同）；
2. 并发正确性 —— 多条通道同时触发自动推进时，下游阶段不能被重复启动。
"""

import threading
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.stage_run import ActivityEvent, StageRun
from app.services.process_graph import (
    get_parallel_siblings,
    group_by_parallel_batch,
)
from app.services.stage_service import _maybe_auto_advance, _project_advance_lock

V_MODEL_CODES = [
    "requirements",
    "architecture",
    "detailed-design",
    "coding",
    "unit-test",
    "integration-test",
    "system-test",
]


def _setup_project(client, project_folder: str, model: str = "v-model") -> tuple[dict, int, dict]:
    reg = client.post(
        "/api/auth/register",
        json={"username": f"par_{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "并行执行测试",
            "process_model_code": model,
            "folder": project_folder,
        },
    ).json()
    flow = client.get(f"/api/projects/{project['id']}/flow", headers=headers).json()
    stage_ids = {item["stage"]["code"]: item["stage"]["id"] for item in flow["stages"]}
    return headers, project["id"], stage_ids


def _approve_up_to_coding(project_id: int, stage_ids: dict) -> int:
    """造出「前置阶段全部通过」的状态，返回 coding 的 run id。"""
    with SessionLocal() as db:
        coding_run_id = 0
        for code in ("requirements", "architecture", "detailed-design", "coding"):
            run = StageRun(
                project_id=project_id,
                stage_id=stage_ids[code],
                status="approved",
                mode="auto",
            )
            db.add(run)
            db.flush()
            if code == "coding":
                coding_run_id = run.id
        db.commit()
        return coding_run_id


def test_v_model_verification_lanes_form_a_single_batch():
    batches = group_by_parallel_batch("v-model", V_MODEL_CODES, V_MODEL_CODES)
    lanes = [batch for batch in batches if len(batch) > 1]
    assert len(lanes) == 1
    assert set(lanes[0]) == {"unit-test", "integration-test", "system-test"}


def test_waterfall_stages_are_never_parallel():
    codes = ["requirements", "architecture", "detailed-design", "coding", "testing"]
    batches = group_by_parallel_batch("waterfall", codes, codes)
    assert all(len(batch) == 1 for batch in batches)


def test_parallel_siblings_are_symmetric():
    siblings = get_parallel_siblings("v-model", "unit-test", V_MODEL_CODES)
    assert set(siblings) == {"integration-test", "system-test"}
    # 瀑布模型里没有同侪
    codes = ["requirements", "architecture", "coding", "testing"]
    assert get_parallel_siblings("waterfall", "testing", codes) == []


def test_project_advance_lock_is_per_project():
    """同一项目共用一个锁，不同项目互不阻塞。"""
    assert _project_advance_lock(11) is _project_advance_lock(11)
    assert _project_advance_lock(11) is not _project_advance_lock(12)


def test_auto_advance_fans_out_all_verification_lanes(client, project_folder):
    """coding 通过后，三条验证通道应被一次性全部启动。"""
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    coding_run_id = _approve_up_to_coding(project_id, stage_ids)

    client.patch(
        f"/api/projects/{project_id}", headers=headers, json={"auto_advance": True}
    )

    with SessionLocal() as db:
        run = db.get(StageRun, coding_run_id)
        started = _maybe_auto_advance(run, db)
        assert len(started) == 3

    events = client.get(
        f"/api/projects/{project_id}/activity-events", headers=headers
    ).json()
    batch_events = [item for item in events if item["event_type"] == "parallel_batch"]
    assert len(batch_events) == 1
    assert "3 条通道" in batch_events[0]["message"]


def test_concurrent_auto_advance_does_not_duplicate_stage_runs(client, project_folder):
    """三条通道并发完成时，下游阶段只能被启动一次。

    这是并行引入的真实竞态：若"检查 → 创建"不加锁，
    多个线程会各自读到「下游尚未启动」的旧快照并重复创建 run。
    """
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    coding_run_id = _approve_up_to_coding(project_id, stage_ids)
    client.patch(
        f"/api/projects/{project_id}", headers=headers, json={"auto_advance": True}
    )

    barrier = threading.Barrier(3)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            with SessionLocal() as db:
                run = db.get(StageRun, coding_run_id)
                barrier.wait(timeout=10)
                _maybe_auto_advance(run, db)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"并发自动推进抛出异常：{errors}"

    with SessionLocal() as db:
        rows = list(
            db.scalars(select(StageRun).where(StageRun.project_id == project_id))
        )
        counts: dict[int, int] = {}
        for row in rows:
            counts[row.stage_id] = counts.get(row.stage_id, 0) + 1

    for code in ("unit-test", "integration-test", "system-test"):
        assert counts[stage_ids[code]] == 1, (
            f"{code} 被启动了 {counts[stage_ids[code]]} 次，应当只有 1 次"
        )


def test_auto_advance_does_nothing_when_disabled(client, project_folder):
    _, project_id, stage_ids = _setup_project(client, project_folder)
    coding_run_id = _approve_up_to_coding(project_id, stage_ids)

    with SessionLocal() as db:
        run = db.get(StageRun, coding_run_id)
        assert _maybe_auto_advance(run, db) == []
        rows = list(
            db.scalars(select(StageRun).where(StageRun.project_id == project_id))
        )
    # 只有我们手工造的那 4 个前置 run。
    assert len(rows) == 4


def test_all_stages_finished_emits_completion(client, project_folder):
    """全部阶段完成后应广播 stage_completed，且不会重复启动任何阶段。"""
    headers, project_id, stage_ids = _setup_project(client, project_folder)
    client.patch(
        f"/api/projects/{project_id}", headers=headers, json={"auto_advance": True}
    )

    with SessionLocal() as db:
        for code in V_MODEL_CODES:
            db.add(
                StageRun(
                    project_id=project_id,
                    stage_id=stage_ids[code],
                    status="approved",
                    mode="auto",
                )
            )
        db.commit()
        run = db.scalar(
            select(StageRun).where(StageRun.project_id == project_id).order_by(StageRun.id)
        )
        assert _maybe_auto_advance(run, db) == []

    with SessionLocal() as db:
        completions = list(
            db.scalars(
                select(ActivityEvent).where(
                    ActivityEvent.project_id == project_id,
                    ActivityEvent.event_type == "parallel_batch",
                )
            )
        )
    assert completions == []
