"""Пользователи, токены, согласия на обработку данных, почта и журнал аудита."""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow

ROLES = ("candidate", "employer", "admin")

_PUBLIC_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_public_id() -> str:
    """Короткий псевдоним кандидата для работодателей: UUID наружу не отдаётся."""
    return "C-" + "".join(secrets.choice(_PUBLIC_ALPHABET) for _ in range(7))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    email_verified: Mapped[bool] = mapped_column(default=False)
    # sub из внешнего провайдера (Keycloak), если вход идёт через него
    external_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    public_id: Mapped[str] = mapped_column(String(12), unique=True, default=new_public_id)
    is_active: Mapped[bool] = mapped_column(default=True)
    # учётная запись демо-данных (seed_demo): её нельзя удалить и сменить ей пароль,
    # чтобы посетители демо-стенда не сломали сценарий друг другу
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    candidate_profile = relationship("CandidateProfile", back_populates="user", uselist=False)


class EmailToken(Base):
    """Одноразовый токен подтверждения адреса; хранится только хеш."""

    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RefreshToken(Base):
    """
    Refresh-токен с ротацией.

    Каждый обмен выдаёт новый токен той же «семьи» и гасит предыдущий.
    Предъявление уже погашенного токена означает утечку: отзывается вся семья.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Consent(Base):
    """
    История согласий (152-ФЗ): каждое изменение — новая запись.

    kind: pd_processing — обработка персональных данных;
          profile_publication — показ профиля работодателям;
          fsp_data — получение сведений о достижениях из реестра ФСП.
    """

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    granted: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_consents_user_kind", "user_id", "kind", "created_at"),)


class OutboxEmail(Base):
    """
    Копии отправленных писем в базе платформы (не в почтовом ящике
    получателя). Хранятся outbox_retention_days дней и удаляются вместе с
    учётной записью адресата.
    """

    __tablename__ = "outbox_emails"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    to_email: Mapped[str] = mapped_column(String(254))
    # назначение письма: verify_email, password_reset, guardian_consent, notice…
    kind: Mapped[str | None] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    """Журнал значимых действий: раскрытие контактов, выгрузка и удаление данных."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
