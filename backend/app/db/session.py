from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_IS_SQLITE = settings.database_url.startswith("sqlite")

if _IS_SQLITE:
    db_file = settings.database_url.replace("sqlite:///", "")
    db_dir = Path(db_file).parent
    db_dir.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if _IS_SQLITE else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


if _IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        """SQLite 并发与外键约束设置：WAL 提升读写并发，busy_timeout 减少锁冲突。"""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
