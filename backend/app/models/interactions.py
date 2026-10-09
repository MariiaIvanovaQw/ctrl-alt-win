"""Приглашения работодателя, отклики кандидата и журнал событий по ним."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow

INVITATION_STATUSES = ("sent", "viewed", "accepted", "declined", "withdrawn", "expired")
APPLICATION_STATUSES = ("sent", "viewed", "invited", "rejected", "withdrawn")
DECLINE_REASONS = {
    "salary": "Не устраивает уровень зарплаты",
    "format": "Не подходит формат работы или город",
    "stack": "Не интересен стек или задачи",
    "not_looking": "Сейчас не ищу работу",
    "company": "Не интересна компания",
    "suspicious": "Предложение выглядит недобросовестным",
    "other": "Другое",
}


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    need_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    selection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("selections.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    salary_from: Mapped[int] = mapped_column(Integer)
    salary_to: Mapped[int] = mapped_column(Integer)
    work_format: Mapped[str | None] = mapped_column(String(20))
    contact_method: Mapped[str] = mapped_column(String(255))
    # работодатель подтвердил, что предложение подходит для несовершеннолетних (15–17 лет) (лёгкий труд, неполный день)
    suitable_for_minors: Mapped[bool] = mapped_column(default=False)
    match: Mapped[dict | None] = mapped_column()  # обоснование: почему пригласили
    status: Mapped[str] = mapped_column(String(20), default="sent")
    decline_reason: Mapped[str | None] = mapped_column(String(20))
    decline_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # кандидат закрыл компании доступ к контактам после принятия
    contacts_revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        Index("ix_invitations_company", "company_id", "created_at"),
        Index("ix_invitations_candidate", "candidate_user_id", "created_at"),
        # одно действующее приглашение на пару «компания — кандидат»
        Index("uq_invitations_active", "company_id", "candidate_user_id", unique=True,
              sqlite_where=text("status IN ('sent', 'viewed')"), postgresql_where=text("status IN ('sent', 'viewed')")),
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("needs.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    employer_comment: Mapped[str | None] = mapped_column(Text)
    contacts_revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_applications_need", "need_id", "created_at"),
        # один действующий отклик кандидата на вакансию
        Index("uq_applications_active", "need_id", "candidate_user_id", unique=True,
              sqlite_where=text("status <> 'withdrawn'"), postgresql_where=text("status <> 'withdrawn'")),
    )


class InteractionEvent(Base):
    """Хронология взаимодействия, которую видят обе стороны."""

    __tablename__ = "interaction_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))  # invitation | application
    ref_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor: Mapped[str] = mapped_column(String(20))  # candidate | employer | system
    event: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Message(Base):
    """Сообщение в переписке по приглашению или отклику."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))  # invitation | application
    ref_id: Mapped[uuid.UUID] = mapped_column()
    sender: Mapped[str] = mapped_column(String(20))  # candidate | employer
    sender_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (Index("ix_messages_thread", "kind", "ref_id", "created_at"),)
