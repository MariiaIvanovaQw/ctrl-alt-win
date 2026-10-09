"""Регулярные короткие задания от работодателей."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow

TASK_KINDS = ("choice", "numeric", "approach")


class EmployerTask(Base):
    """
    Короткая задача: с проверяемым ответом (choice, numeric) или открытая —
    «предложите подход» (approach), которую оценивает сам работодатель.
    """

    __tablename__ = "employer_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    need_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    specialization: Mapped[str] = mapped_column(String(20))
    level_min: Mapped[str] = mapped_column(String(10), default="junior")
    level_max: Mapped[str] = mapped_column(String(10), default="senior")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    options: Mapped[list] = mapped_column(default=list)
    answer: Mapped[dict | None] = mapped_column()  # для choice и numeric
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TaskAssignment(Base):
    __tablename__ = "task_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employer_tasks.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="assigned")  # assigned | submitted | reviewed | expired
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    answer: Mapped[dict | None] = mapped_column()
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    auto_correct: Mapped[bool | None] = mapped_column()
    employer_score: Mapped[int | None] = mapped_column(Integer)  # 1..5
    employer_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # антиплагиат: самый похожий ответ другого кандидата {"candidate_id", "share"}
    similarity: Mapped[dict | None] = mapped_column()

    __table_args__ = (
        Index("ix_task_assignments_candidate", "candidate_user_id", "assigned_at"),
        # одно и то же задание кандидат получает не больше одного раза — и при
        # двух одновременных выдачах (кабинет открыт в двух вкладках) тоже
        Index("uq_task_assignments_task_candidate", "task_id", "candidate_user_id", unique=True),
    )
