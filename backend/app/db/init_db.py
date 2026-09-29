from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import AgentRole, ProcessModel, Project, Stage, User  # noqa: F401
from app.services.seed import seed_all


def _ensure_project_columns() -> None:
    """为既有 SQLite 库补齐新增列（create_all 不会修改已存在的表）。"""
    with engine.begin() as conn:
        columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(projects)")
        ]
        if not columns:
            return
        if "folder" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN folder VARCHAR(500)"
            )
        if "auto_advance" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN auto_advance BOOLEAN DEFAULT 0"
            )


def _ensure_stage_run_columns() -> None:
    """为既有 SQLite 库补齐 stage_runs 的新增列。"""
    with engine.begin() as conn:
        columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(stage_runs)")
        ]
        if not columns:
            return
        if "agent_code" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE stage_runs ADD COLUMN agent_code VARCHAR(50)"
            )
        if "model_name" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE stage_runs ADD COLUMN model_name VARCHAR(120)"
            )
        if "tool_usage_json" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE stage_runs ADD COLUMN tool_usage_json TEXT"
            )


def _ensure_llm_call_log_columns() -> None:
    """为既有 SQLite 库补齐 llm_call_logs 的关联与用途列。"""
    with engine.begin() as conn:
        columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(llm_call_logs)")
        ]
        if not columns:
            return
        if "project_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE llm_call_logs ADD COLUMN project_id INTEGER"
            )
        if "stage_run_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE llm_call_logs ADD COLUMN stage_run_id INTEGER"
            )
        if "purpose" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE llm_call_logs ADD COLUMN purpose VARCHAR(60)"
            )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_project_columns()
    _ensure_stage_run_columns()
    _ensure_llm_call_log_columns()
    with SessionLocal() as db:
        seed_all(db)
