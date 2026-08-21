from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import AgentRole, ProcessModel, Project, Stage, User  # noqa: F401
from app.services.seed import seed_all


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_all(db)
