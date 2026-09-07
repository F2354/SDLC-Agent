from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.process_model import ProcessModel
    from app.models.stage_run import ActivityEvent, Artifact, Message, StageRun
    from app.models.user import User


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    process_model_id: Mapped[int] = mapped_column(
        ForeignKey("process_models.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    folder: Mapped[str | None] = mapped_column(String(500), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    process_model: Mapped["ProcessModel"] = relationship(back_populates="projects")

    # 删除项目时级联清理所有关联数据，避免产生孤儿记录。
    stage_runs: Mapped[list["StageRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    activity_events: Mapped[list["ActivityEvent"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
