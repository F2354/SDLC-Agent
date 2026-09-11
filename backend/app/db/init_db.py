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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_project_columns()
    with SessionLocal() as db:
        seed_all(db)
