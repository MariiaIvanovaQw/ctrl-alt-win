"""Компания, потребности (они же вакансии) и сохранённые подборки."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    inn: Mapped[str | None] = mapped_column(String(12))
    industry: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    # защита от недобросовестных работодателей (app/services/trust.py)
    # Добровольная метка доверия: компания запрашивает проверку, модератор
    # сверяет ИНН и название с ЕГРЮЛ и сайтом. Основной сценарий не блокирует.
    verified: Mapped[bool] = mapped_column(default=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="none")  # none | requested | verified | rejected
    verification_comment: Mapped[str | None] = mapped_column(Text)
    verification_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    complaints: Mapped[int] = mapped_column(Integer, default=0)
    review_status: Mapped[str] = mapped_column(String(20), default="active")  # active | on_review | blocked
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Complaint(Base):
    """
    Жалоба кандидата на работодателя: на приглашение или на вакансию.
    Отказ от приглашения с причиной «подозрительное предложение» тоже
    создаёт жалобу. По числу жалоб компания автоматически уходит на проверку.
    """

    __tablename__ = "complaints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invitations.id", ondelete="SET NULL"))
    need_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_complaints_company", "company_id", "created_at"),)


class Need(Base):
    """
    Описание потребности работодателя.

    Неопубликованная потребность используется только для подборки
    кандидатов; опубликованная становится вакансией, на которую можно
    откликнуться. Вилка зарплаты обязательна в обоих случаях.
    """

    __tablename__ = "needs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    specialization: Mapped[str] = mapped_column(String(20))
    level: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text, default="")
    team_description: Mapped[str | None] = mapped_column(Text)
    stack: Mapped[list] = mapped_column(default=list)
    work_format: Mapped[str] = mapped_column(String(20), default="any")
    city: Mapped[str | None] = mapped_column(String(100))
    salary_from: Mapped[int] = mapped_column(Integer)
    salary_to: Mapped[int] = mapped_column(Integer)
    is_published: Mapped[bool] = mapped_column(default=False)
    # подходит для несовершеннолетних (15–17 лет): лёгкий труд, сокращённое время, без вредных условий
    suitable_for_minors: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    profile: Mapped[dict] = mapped_column(default=dict)  # извлечённый профиль: компетенции и навыки
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (Index("ix_needs_published", "is_published", "status", "specialization"),)


class Selection(Base):
    """
    Сохранённая подборка: параметры и снимок результата с обоснованиями.

    Уточнение фильтров создаёт новую подборку со ссылкой на родителя, поэтому
    ранее полученный результат не теряется.
    """

    __tablename__ = "selections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    need_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("selections.id", ondelete="SET NULL"))
    params: Mapped[dict] = mapped_column(default=dict)
    results: Mapped[list] = mapped_column(default=list)
    summary: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
