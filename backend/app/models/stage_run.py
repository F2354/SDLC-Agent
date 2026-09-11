from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.llm_provider import LLMProvider
    from app.models.process_model import Stage
    from app.models.project import Project


# 阶段运行被删除时，其下所有制品、消息、评审一并级联删除。
_STAGE_RUN_CASCADE = "all, delete-orphan"


class StageRun(Base):
    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_providers.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="pending")
    mode: Mapped[str] = mapped_column(String(20), default="auto")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="stage_runs")
    stage: Mapped["Stage"] = relationship()
    provider: Mapped["LLMProvider | None"] = relationship()
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="stage_run", cascade=_STAGE_RUN_CASCADE
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="stage_run", cascade=_STAGE_RUN_CASCADE
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="stage_run", cascade=_STAGE_RUN_CASCADE
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage_run_id: Mapped[int] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    content_md: Mapped[str] = mapped_column(Text, default="")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="artifacts")
    stage_run: Mapped["StageRun"] = relationship(back_populates="artifacts")
    versions: Mapped[list["ArtifactVersion"]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="ArtifactVersion.version_no",
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer)
    content_md: Mapped[str] = mapped_column(Text)
    change_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    artifact: Mapped["Artifact"] = relationship(back_populates="versions")


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("stage_runs.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="activity_events")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage_run_id: Mapped[int] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    agent_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="messages")
    stage_run: Mapped["StageRun"] = relationship(back_populates="messages")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage_run_id: Mapped[int] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True, index=True
    )
    reviewer_type: Mapped[str] = mapped_column(String(20), default="user")
    result: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stage_run: Mapped["StageRun"] = relationship(back_populates="reviews")
    artifact: Mapped["Artifact | None"] = relationship(back_populates="reviews")


class TraceabilityLink(Base):
    """实体追溯关系：从需求到用例、模块、测试用例的显式关联。"""

    __tablename__ = "traceability_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True, index=True
    )
    from_type: Mapped[str] = mapped_column(String(20))
    from_key: Mapped[str] = mapped_column(String(50), index=True)
    to_type: Mapped[str] = mapped_column(String(20))
    to_key: Mapped[str] = mapped_column(String(50), index=True)
    relation: Mapped[str] = mapped_column(String(30), default="derives")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="traceability_links")
